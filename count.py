"""Turn source code into weighted character, bigram and trigram counts of what a person types.

Each character gets a weight in [0, 1] modelling how often it is actually keyed:
- comments and docstrings/doc comments are down-weighted relative to code,
- closing brackets and closing quotes are discounted (editors auto-close them),
- identifier characters past the first few are discounted (autocomplete),
- whitespace and indentation are dropped and break bigram chains.

Python is tokenized with the standard tokenizer; other languages use a small regex lexer
driven by their comment and quote syntax (LANGUAGES).

Usage: python count.py corpus/raw [more dirs...] [--config config.toml] [--lang python]
Each immediate subdirectory of an input dir is one source (one repo) and is capped at
--max-chars so large repos don't dominate.
"""
import argparse
import hashlib
import io
import json
import random
import re
import tokenize
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Weights:
    comment: float = 0.6
    docstring: float = 0.4
    close_discount: float = 0.3      # closing ) ] } and closing quotes
    autocomplete_after: int = 4      # identifier chars typed in full before completion
    autocomplete_factor: float = 0.3


@dataclass(frozen=True)
class Language:
    extensions: tuple[str, ...]
    line_comments: tuple[str, ...] = ("//",)
    block_comments: tuple[tuple[str, str], ...] = (("/*", "*/"),)
    doc_prefixes: tuple[str, ...] = ("/**", "///", "//!")  # comments counted as docs
    quotes: str = "\"'"           # strings that end on the same line
    multiline_quotes: str = ""    # strings that may span lines


LANGUAGES = {
    "python": Language((".py",), line_comments=("#",), block_comments=(), doc_prefixes=()),
    "javascript": Language((".js", ".jsx", ".mjs", ".cjs"), multiline_quotes="`"),
    "typescript": Language((".ts", ".tsx", ".mts", ".cts"), multiline_quotes="`"),
    "c": Language((".c", ".h")),
    "cpp": Language((".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h")),
    "java": Language((".java",)),
    "csharp": Language((".cs",)),
    "go": Language((".go",), multiline_quotes="`"),
    # ' is left out: lifetimes ('a) would read as unterminated char literals
    "rust": Language((".rs",), quotes='"'),
    "ruby": Language((".rb",), line_comments=("#",), block_comments=(("=begin", "=end"),),
                     doc_prefixes=()),
}

Run = list[tuple[str, float]]

# --- Python ---------------------------------------------------------------------------
QUOTE_RE = re.compile(r"^[A-Za-z]*('''|\"\"\"|'|\")")
STRING_TYPES = {"STRING"}
OPEN_STRING_TYPES = {"FSTRING_START", "TSTRING_START"}
CLOSE_STRING_TYPES = {"FSTRING_END", "TSTRING_END"}
BREAK_TYPES = {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}


def typeable(ch: str) -> bool:
    return 33 <= ord(ch) <= 126


def identifier_weights(n: int, base: float, w: Weights) -> list[float]:
    return [base * (w.autocomplete_factor if i >= w.autocomplete_after else 1.0) for i in range(n)]


def token_weights(tok: tokenize.TokenInfo, kind: str, w: Weights) -> list[float]:
    """Per-character weight for one Python token's text."""
    text = tok.string
    base = {"comment": w.comment, "docstring": w.docstring}.get(kind, 1.0)
    weights = [base] * len(text)
    name = tokenize.tok_name[tok.type]
    if tok.type == tokenize.NAME:
        weights = identifier_weights(len(text), base, w)
    elif tok.type == tokenize.OP:
        for i, ch in enumerate(text):
            if ch in ")]}":
                weights[i] *= w.close_discount
    elif name in STRING_TYPES:
        m = QUOTE_RE.match(text)
        if m and text.endswith(m.group(1)) and len(text) >= m.end() + len(m.group(1)):
            for i in range(len(text) - len(m.group(1)), len(text)):
                weights[i] *= w.close_discount
    elif name in CLOSE_STRING_TYPES:
        weights = [x * w.close_discount for x in weights]
    return weights


class RunBuilder:
    """Collects (char, weight) into runs; untypeable chars (whitespace, non-ASCII) end a run."""

    def __init__(self):
        self.out: list[Run] = []
        self.cur: Run = []

    def add(self, text: str, weights: list[float]) -> None:
        for ch, wt in zip(text, weights):
            if typeable(ch):
                self.cur.append((ch, wt))
            else:
                self.end()

    def end(self) -> None:
        if self.cur:
            self.out.append(self.cur)
            self.cur = []


def python_runs(source: str, w: Weights) -> list[Run]:
    """Split a Python file into runs of consecutively typed characters with weights."""
    rb = RunBuilder()
    prev_end = None
    prev_sig = None  # previous significant token type, for docstring detection
    fstring_depth = 0
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        name = tokenize.tok_name[tok.type]
        if tok.type in BREAK_TYPES:
            rb.end()
            prev_end = None
            if tok.type != tokenize.NL:
                prev_sig = tok.type
            continue
        if tok.start != prev_end:
            rb.end()
        if tok.type == tokenize.COMMENT:
            kind = "comment"
        elif (name in STRING_TYPES and fstring_depth == 0
              and prev_sig in (None, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)):
            kind = "docstring"
        else:
            kind = "code"
        rb.add(tok.string, token_weights(tok, kind, w))
        if name in OPEN_STRING_TYPES:
            fstring_depth += 1
        elif name in CLOSE_STRING_TYPES:
            fstring_depth -= 1
        if tok.type != tokenize.COMMENT:
            prev_sig = tok.type
        prev_end = tok.end
    rb.end()
    return rb.out


# --- other languages ------------------------------------------------------------------
def lexer(lang: Language) -> re.Pattern:
    parts = []
    for i, (start, end) in enumerate(lang.block_comments):
        parts.append(f"(?P<block{i}>{re.escape(start)}.*?{re.escape(end)})")
    for marker in lang.line_comments:
        parts.append(f"(?P<line{len(parts)}>{re.escape(marker)}[^\\n]*)")
    for q in lang.quotes:
        parts.append(f"(?P<str{len(parts)}>{q}(?:\\\\.|[^{q}\\\\\\n])*{q})")
    for q in lang.multiline_quotes:
        parts.append(f"(?P<str{len(parts)}>{q}(?:\\\\.|[^{q}\\\\])*{q})")
    parts += [r"(?P<ident>[A-Za-z_][A-Za-z0-9_]*)", r"(?P<num>[0-9][A-Za-z0-9_.]*)",
              r"(?P<other>.)"]
    return re.compile("|".join(parts), re.DOTALL)


LEXERS: dict[str, re.Pattern] = {}


def generic_runs(source: str, w: Weights, lang: Language) -> list[Run]:
    """Runs for a C-like language: comments, strings, identifiers and single symbols."""
    pattern = LEXERS.get(repr(lang)) or LEXERS.setdefault(repr(lang), lexer(lang))
    rb = RunBuilder()
    for m in pattern.finditer(source):
        text, group = m.group(), m.lastgroup
        if group.startswith(("block", "line")):
            base = w.docstring if text.startswith(lang.doc_prefixes) else w.comment
            rb.add(text, [base] * len(text))
        elif group.startswith("str"):
            rb.add(text, [1.0] * (len(text) - 1) + [w.close_discount])
        elif group == "ident":
            rb.add(text, identifier_weights(len(text), 1.0, w))
        else:
            rb.add(text, [w.close_discount if text in ")]}" else 1.0] * len(text))
    rb.end()
    return rb.out


def runs(source: str, w: Weights, lang: str = "python") -> list[Run]:
    if lang == "python":
        return python_runs(source, w)
    return generic_runs(source, w, LANGUAGES[lang])


def count_source(source: str, w: Weights, uni: Counter, bi: Counter, tri: Counter | None = None,
                 lang: str = "python") -> int:
    """Add one file's counts; return the number of typeable chars seen.

    An n-gram's weight is the smallest weight of its characters.
    """
    n = 0
    for run in runs(source, w, lang):
        n += len(run)
        for ch, wt in run:
            uni[ch] += wt
        for (a, wa), (b, wb) in zip(run, run[1:]):
            bi[a + b] += min(wa, wb)
        if tri is not None:
            for (a, wa), (b, wb), (c, wc) in zip(run, run[1:], run[2:]):
                tri[a + b + c] += min(wa, wb, wc)
    return n


def main() -> None:
    from config import DEFAULT_PATH, load  # config imports this module

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--config", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE")
    ap.add_argument("--lang", choices=list(LANGUAGES), help="overrides [corpus] language")
    ap.add_argument("--out", type=Path, help="overrides [corpus] counts")
    ap.add_argument("--max-chars", type=int, default=3_000_000, help="cap per source (repo)")
    ap.add_argument("--min-trigram", type=float, default=2.0,
                    help="drop rarer trigrams from the output (keeps the file small)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    # the Python tokenizer warns about invalid escapes in the corpus's own code
    warnings.filterwarnings("ignore", category=SyntaxWarning)

    cfg = load(args.config, args.set)
    lang = args.lang or cfg.language
    out = args.out or cfg.counts
    w = cfg.weights
    uni: Counter = Counter()
    bi: Counter = Counter()
    tri: Counter = Counter()
    seen: set[str] = set()
    rng = random.Random(args.seed)
    exts = LANGUAGES[lang].extensions
    sources = [s for d in args.dirs for s in sorted(d.iterdir()) if s.is_dir()]
    for src in sources:
        files = sorted(f for f in src.rglob("*") if f.suffix in exts and f.is_file())
        rng.shuffle(files)
        chars = used = 0
        for f in files:
            if chars >= args.max_chars:
                break
            text = f.read_text(encoding="utf-8", errors="replace")
            digest = hashlib.sha1(text.encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            try:
                chars += count_source(text, w, uni, bi, tri, lang)
                used += 1
            except (tokenize.TokenError, SyntaxError, IndentationError):
                continue
        print(f"{src.name:40s} {used:6d} files {chars:>10,d} chars")

    out.parent.mkdir(parents=True, exist_ok=True)
    kept_tri = {t: round(v, 2) for t, v in tri.most_common() if v >= args.min_trigram}
    out.write_text(json.dumps({
        "language": lang,
        "weights": w.__dict__,
        "sources": [s.name for s in sources],
        "unigrams": {k: round(v, 2) for k, v in uni.most_common()},
        "bigrams": {k: round(v, 2) for k, v in bi.most_common()},
        "trigrams": kept_tri,
    }, indent=0))
    total = sum(uni.values())
    tri_share = sum(kept_tri.values()) / max(sum(tri.values()), 1)
    print(f"\nwrote {out}: {total:,.0f} weighted keystrokes, {len(bi):,} bigrams, "
          f"{len(kept_tri):,} of {len(tri):,} trigrams ({tri_share:.1%} of trigram weight)")
    print("top symbols:", " ".join(f"{c}{uni[c] / total:.1%}" for c, _ in uni.most_common()
                                   if not c.isalnum())[:200])


if __name__ == "__main__":
    main()
