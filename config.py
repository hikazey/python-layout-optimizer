"""Load settings from a TOML file (config.toml): corpus, counting weights, layout, cost model.

Every value can be overridden on the command line with --set section.key=value, where value
is a TOML literal: --set cost.shift=2.5  --set layout.base='"qwerty"'  --set brackets.pairs=[]
"""
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from count import LANGUAGES, Weights
from model import EFFORT, FINGERS, LAYOUTS, Keyboard, Params, Problem

DEFAULT_PATH = Path("config.toml")
# config [cost] / [brackets] keys -> Params fields
BRACKET_KEYS = {"pairs": "bracket_pairs", "allow": "bracket_allow", "penalty": "bracket_penalty"}


@dataclass
class Config:
    language: str = "python"
    counts: Path = Path("results/counts.json")
    weights: Weights = Weights()
    base: str = "qwerty"
    digits: str = "unshifted"
    baselines: list[str] | None = None  # None = every known layout with the same letters/digits
    params: Params = Params()
    fingers: list[list[int]] | None = None
    effort: list[list[float]] | None = None

    def problem(self) -> Problem:
        return Problem(self.base, self.digits, Keyboard(self.fingers or FINGERS, self.effort or EFFORT))

    def baseline_layouts(self, problem: Problem) -> dict:
        ok = problem.compatible()
        if self.baselines is None:
            return ok
        bad = [n for n in self.baselines if n not in ok]
        if bad:
            raise ValueError(f"baselines {bad} don't keep the letters/digits of {self.base!r} "
                             f"with {self.digits} digits")
        return {n: ok[n] for n in self.baselines}


def parse_override(text: str) -> tuple[str, str, object]:
    key, sep, value = text.partition("=")
    section, dot, name = key.strip().partition(".")
    if not sep or not dot:
        raise ValueError(f"--set expects section.key=value, got {text!r}")
    return section, name, tomllib.loads(f"v = {value}")["v"]


def load(path: Path | None = DEFAULT_PATH, overrides: list[str] = ()) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}
    for text in overrides:
        section, name, value = parse_override(text)
        data.setdefault(section, {})[name] = value

    def take(section: str, allowed: set[str]) -> dict:
        got = dict(data.pop(section, {}))
        unknown = set(got) - allowed
        if unknown:
            raise ValueError(f"unknown key(s) in [{section}]: {', '.join(sorted(unknown))}")
        return got

    corpus = take("corpus", {"language", "counts"})
    counting = take("counting", {f.name for f in fields(Weights)})
    layout = take("layout", {"base", "digits", "baselines"})
    cost = take("cost", {f.name for f in fields(Params)} - set(BRACKET_KEYS.values()))
    brackets = take("brackets", set(BRACKET_KEYS))
    keyboard = take("keyboard", {"fingers", "effort"})
    if data:
        raise ValueError(f"unknown section(s): {', '.join(data)}")

    cfg = Config(
        language=corpus.get("language", "python"),
        counts=Path(corpus.get("counts", "results/counts.json")),
        weights=Weights(**counting),
        base=layout.get("base", "qwerty"),
        digits=layout.get("digits", "unshifted"),
        baselines=layout.get("baselines"),
        params=Params(**cost, **{BRACKET_KEYS[k]: tuple(v) if isinstance(v, list) else v
                                 for k, v in brackets.items()}),
        fingers=keyboard.get("fingers"),
        effort=keyboard.get("effort"),
    )
    if cfg.language not in LANGUAGES:
        raise ValueError(f"unknown language {cfg.language!r}; choose from {', '.join(LANGUAGES)}")
    if cfg.base not in LAYOUTS:
        raise ValueError(f"unknown base layout {cfg.base!r}; choose from {', '.join(LAYOUTS)}")
    return cfg
