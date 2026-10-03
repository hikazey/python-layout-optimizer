"""Keyboard geometry, the typing-cost model, and the layouts to compare.

A layout assigns all 94 printable ASCII characters to 94 slots (47 keys x unshifted/shifted).
Letters stay where the base layout (QWERTY, Dvorak, Colemak-DH, ...) has them and digits stay on
the 1-0 keys in order (unshifted, or shifted as in Programmer Dvorak), so only the 32 symbols
move; they fill the 32 remaining slots.

Cost of a text = sum over keystrokes of slot effort (+ Shift) + sum over bigrams of a pair cost
(same-finger bigrams, row jumps, rolls, held Shift) + optionally a trigram cost (redirects).
Reported per keystroke, plus a flat penalty per bracket pair that isn't placed learnably.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# --- geometry -----------------------------------------------------------------------
# (QWERTY label, AHK scan code) for the 47 keys, by row
ROWS = [
    [("`", "SC029"), ("1", "SC002"), ("2", "SC003"), ("3", "SC004"), ("4", "SC005"), ("5", "SC006"),
     ("6", "SC007"), ("7", "SC008"), ("8", "SC009"), ("9", "SC00A"), ("0", "SC00B"), ("-", "SC00C"),
     ("=", "SC00D")],
    [("q", "SC010"), ("w", "SC011"), ("e", "SC012"), ("r", "SC013"), ("t", "SC014"), ("y", "SC015"),
     ("u", "SC016"), ("i", "SC017"), ("o", "SC018"), ("p", "SC019"), ("[", "SC01A"), ("]", "SC01B"),
     ("\\", "SC02B")],
    [("a", "SC01E"), ("s", "SC01F"), ("d", "SC020"), ("f", "SC021"), ("g", "SC022"), ("h", "SC023"),
     ("j", "SC024"), ("k", "SC025"), ("l", "SC026"), (";", "SC027"), ("'", "SC028")],
    [("z", "SC02C"), ("x", "SC02D"), ("c", "SC02E"), ("v", "SC02F"), ("b", "SC030"), ("n", "SC031"),
     ("m", "SC032"), (",", "SC033"), (".", "SC034"), ("/", "SC035")],
]
ROW_OFFSET = [0.0, 0.5, 0.75, 1.25]  # stagger, so column distances are roughly physical
# fingers 0-3 = left pinky..index, 4-7 = right index..pinky; 6 is typed by the left index
FINGERS = [
    [0, 0, 1, 2, 3, 3, 3, 4, 5, 6, 7, 7, 7],
    [0, 1, 2, 3, 3, 4, 4, 5, 6, 7, 7, 7, 7],
    [0, 1, 2, 3, 3, 4, 4, 5, 6, 7, 7],
    [0, 1, 2, 3, 3, 4, 4, 5, 6, 7],
]
EFFORT = [
    [4.0, 3.4, 2.8, 2.5, 2.5, 3.0, 3.6, 2.5, 2.5, 2.8, 3.4, 3.8, 4.4],
    [2.0, 1.5, 1.2, 1.2, 1.7, 1.9, 1.2, 1.2, 1.5, 2.0, 2.8, 3.6, 4.0],
    [1.1, 1.0, 1.0, 1.0, 1.5, 1.5, 1.0, 1.0, 1.0, 1.1, 2.0],
    [2.2, 1.9, 1.6, 1.5, 2.2, 1.5, 1.5, 1.6, 1.9, 2.2],
]
# column sums for mirrored keys: 1<->0 on the number row, q<->p, a<->;, z<->/ below
MIRROR_SUM = [11, 9, 9, 9]


@dataclass(frozen=True)
class Key:
    label: str
    scancode: str
    row: int
    col: int
    x: float
    finger: int
    effort: float

    @property
    def hand(self) -> int:
        return 0 if self.finger < 4 else 1


class Keyboard:
    """The 47 keys with a finger and an effort each (both overridable from the config)."""

    def __init__(self, fingers: list[list[int]] = FINGERS, effort: list[list[float]] = EFFORT):
        for name, grid in (("fingers", fingers), ("effort", effort)):
            if [len(r) for r in grid] != [len(r) for r in ROWS]:
                raise ValueError(f"{name} must have rows of {[len(r) for r in ROWS]} keys")
        self.keys = [Key(lab, sc, r, c, c + ROW_OFFSET[r], fingers[r][c], effort[r][c])
                     for r, row in enumerate(ROWS) for c, (lab, sc) in enumerate(row)]
        self.index = {k.label: i for i, k in enumerate(self.keys)}


N_SLOTS = 94  # slot = key * 2 + shifted
CHARS = [chr(c) for c in range(33, 127)]
CHAR_INDEX = {c: i for i, c in enumerate(CHARS)}
assert len(CHARS) == N_SLOTS == 2 * sum(len(r) for r in ROWS)


@dataclass(frozen=True)
class Params:
    shift: float = 1.5           # extra cost of a shifted keystroke
    held_shift: float = 0.75     # refund when consecutive shifted chars use the same Shift key
    sfb: float = 2.5             # same finger, different key
    sfb_per_unit: float = 1.0    # ... plus per key-width of travel
    row_jump: float = 0.6        # same hand, different fingers, per row beyond 1
    inward_roll: float = -0.3    # same hand, same row, adjacent fingers moving toward the index
    alternation: float = -0.1    # hand switch
    redirect: float = 0.0        # one-hand trigram that changes direction (needs trigram counts)
    bracket_pairs: tuple[str, ...] = ()  # pairs to keep learnable, e.g. ("()", "[]", "{}")
    bracket_allow: tuple[str, ...] = ("adjacent", "mirrored")
    bracket_penalty: float = 1.0  # added to cost/key per pair placed otherwise


def slot_tables(kb: Keyboard, p: Params = Params()) -> tuple[np.ndarray, np.ndarray]:
    """Per-slot base cost and slot-pair cost matrices."""
    base = np.zeros(N_SLOTS)
    pair = np.zeros((N_SLOTS, N_SLOTS))
    for ka, a in enumerate(kb.keys):
        for sa in (0, 1):
            base[2 * ka + sa] = a.effort + p.shift * sa
            for kb_, b in enumerate(kb.keys):
                for sb in (0, 1):
                    c = 0.0
                    if a.hand != b.hand:
                        c += p.alternation
                    elif ka != kb_:
                        if a.finger == b.finger:
                            dist = ((a.row - b.row) ** 2 + (a.x - b.x) ** 2) ** 0.5
                            c += p.sfb + p.sfb_per_unit * dist
                        else:
                            c += p.row_jump * max(0, abs(a.row - b.row) - 1)
                            if a.row == b.row and abs(a.finger - b.finger) == 1 and is_inward(a, b):
                                c += p.inward_roll
                    if sa and sb and a.hand == b.hand:  # same Shift key stays held
                        c -= p.held_shift
                    pair[2 * ka + sa, 2 * kb_ + sb] = c
    return base, pair


def is_inward(a: Key, b: Key) -> bool:
    """Roll toward the index finger (pinky -> index on either hand)."""
    return b.finger > a.finger if a.hand == 0 else b.finger < a.finger


def redirect_fingers() -> np.ndarray:
    """bool[f1, f2, f3]: three fingers of one hand whose movement changes direction."""
    f = np.arange(8)
    f1, f2, f3 = f[:, None, None], f[None, :, None], f[None, None, :]
    one_hand = ((f1 >= 4) == (f2 >= 4)) & ((f2 >= 4) == (f3 >= 4))
    return one_hand & (f1 != f2) & (f2 != f3) & ((f2 - f1) * (f3 - f2) < 0)


def slot_fingers(kb: Keyboard) -> np.ndarray:
    return np.array([kb.keys[s // 2].finger for s in range(N_SLOTS)])


def redirect_table(kb: Keyboard) -> np.ndarray:
    """bool[s1, s2, s3]: redirect_fingers() by slot."""
    f = slot_fingers(kb)
    return redirect_fingers()[np.ix_(f, f, f)]


class Redirects:
    """Weighted redirect count of a layout, from trigram counts.

    Redirects depend only on the three fingers, so trigrams are grouped by how many of their
    chars can move: none -> a constant, one -> a char x finger table, two -> an 8x8 finger
    table per char pair, three -> kept as a list. That keeps the annealing loop fast.
    """

    def __init__(self, problem: "Problem", trigrams: dict[str, float]):
        r = redirect_fingers().astype(float)
        self.slot_finger = slot_fingers(problem.kb)
        fixed = {CHAR_INDEX[ch]: self.slot_finger[s] for ch, s in problem.fixed.items()}
        self.const = 0.0
        self.total = 0.0
        self.one = np.zeros((len(CHARS), 8))
        two: dict[tuple[int, int], np.ndarray] = {}
        three = []
        for t, w in trigrams.items():
            if not all(ch in CHAR_INDEX for ch in t):
                continue
            idx = [CHAR_INDEX[ch] for ch in t]
            free = [i for i in range(3) if idx[i] not in fixed]
            sub = w * r[tuple(slice(None) if i in free else fixed[idx[i]] for i in range(3))]
            self.total += w
            if not free:
                self.const += float(sub)
            elif len(free) == 1:
                self.one[idx[free[0]]] += sub
            elif len(free) == 2:
                key = (idx[free[0]], idx[free[1]])
                two[key] = two.get(key, 0) + sub
            else:
                three.append((*idx, w))
        self.one_idx = problem.free_idx
        self.two_a = np.array([a for a, _ in two], int)
        self.two_b = np.array([b for _, b in two], int)
        self.two = np.array(list(two.values())).reshape(-1, 8, 8)
        self.two_rows = np.arange(len(two))
        a, b, c, w = zip(*three) if three else ((), (), (), ())
        self.three = (np.array(a, int), np.array(b, int), np.array(c, int), np.array(w, float))
        self.r = r

    def weight(self, pos: np.ndarray) -> float:
        f = self.slot_finger[pos]
        a, b, c, w = self.three
        return (self.const + self.one[self.one_idx, f[self.one_idx]].sum()
                + self.two[self.two_rows, f[self.two_a], f[self.two_b]].sum()
                + w @ self.r[f[a], f[b], f[c]])


def bracket_tables(kb: Keyboard) -> dict[str, np.ndarray]:
    """bool[open slot, close slot] per learnable placement of a bracket pair.

    adjacent: same row and layer, close directly right of open.
    mirrored: same row and layer, open on the left hand, close on the mirrored right-hand key.
    """
    adjacent = np.zeros((N_SLOTS, N_SLOTS), bool)
    mirrored = np.zeros((N_SLOTS, N_SLOTS), bool)
    for i, a in enumerate(kb.keys):
        for j, b in enumerate(kb.keys):
            if a.row != b.row:
                continue
            for s in (0, 1):
                if b.col == a.col + 1:
                    adjacent[2 * i + s, 2 * j + s] = True
                if a.hand == 0 and b.hand == 1 and a.col + b.col == MIRROR_SUM[a.row]:
                    mirrored[2 * i + s, 2 * j + s] = True
    return {"adjacent": adjacent, "mirrored": mirrored}


# --- layouts ------------------------------------------------------------------------
def layout_from_rows(rows: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Build a layout from 'unshifted' and 'shifted' strings per QWERTY row (47 keys)."""
    out = {}
    for r, row in enumerate(ROWS):
        lo, hi = rows[f"r{r}"], rows[f"r{r}s"]
        for (label, _), a, b in zip(row, lo, hi, strict=True):
            out[label] = (a, b)
    return out


# Each layout: QWERTY key label -> (unshifted, shifted).
LAYOUTS = {
    "qwerty": layout_from_rows({
        "r0": "`1234567890-=", "r0s": "~!@#$%^&*()_+",
        "r1": "qwertyuiop[]\\", "r1s": "QWERTYUIOP{}|",
        "r2": "asdfghjkl;'", "r2s": 'ASDFGHJKL:"',
        "r3": "zxcvbnm,./", "r3s": "ZXCVBNM<>?",
    }),
    "dvorak": layout_from_rows({
        "r0": "`1234567890[]", "r0s": "~!@#$%^&*(){}",
        "r1": "',.pyfgcrl/=\\", "r1s": '"<>PYFGCRL?+|',
        "r2": "aoeuidhtns-", "r2s": "AOEUIDHTNS_",
        "r3": ";qjkxbmwvz", "r3s": ":QJKXBMWVZ",
    }),
    "colemak-dh": layout_from_rows({
        "r0": "`1234567890-=", "r0s": "~!@#$%^&*()_+",
        "r1": "qwfpbjluy;[]\\", "r1s": "QWFPBJLUY:{}|",
        "r2": "arstgmneio'", "r2s": 'ARSTGMNEIO"',
        "r3": "zxcdvkh,./", "r3s": "ZXCDVKH<>?",
    }),
    # Programmer Dvorak with the digits in order on Shift (the author's variant)
    "programmer-dvorak": layout_from_rows({
        "r0": "$&[{}(=*)+]!#", "r0s": "~1234567890%`",
        "r1": ";,.pyfgcrl/@\\", "r1s": ":<>PYFGCRL?^|",
        "r2": "aoeuidhtns-", "r2s": "AOEUIDHTNS_",
        "r3": "'qjkxbmwvz", "r3s": '"QJKXBMWVZ',
    }),
    # the author's hand-designed Python layout on Programmer Dvorak letters
    "python-hand": layout_from_rows({
        "r0": "#![{(=*)}]+%@", "r0s": "`1234567890^&",
        "r1": ":,.pyfgcrl/~\\", "r1s": ";<>PYFGCRL?$|",
        "r2": "aoeuidhtns_", "r2s": "AOEUIDHTNS-",
        "r3": '"qjkxbmwvz', "r3s": "'QJKXBMWVZ",
    }),
}
DIGIT_MODES = ("unshifted", "shifted")
BASE_NAMES = {"qwerty": "QWERTY", "dvorak": "Dvorak", "colemak-dh": "Colemak-DH",
              "programmer-dvorak": "Programmer Dvorak", "python-hand": "Python Hand"}
LAYOUTS_DIR = Path("layouts")  # one folder per layout: layout.json + every export


def slug(name: str) -> str:
    """Folder/file name for a layout name: "Python Colemak-DH" -> "python-colemak-dh"."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@dataclass
class Problem:
    """Which characters are fixed (base-layout letters, digits on 1-0) and which ones move."""
    base: str = "qwerty"
    digits: str = "unshifted"
    kb: Keyboard = field(default_factory=Keyboard)

    def __post_init__(self):
        if self.base not in LAYOUTS:
            raise ValueError(f"unknown base layout {self.base!r}; choose from {', '.join(LAYOUTS)}")
        if self.digits not in DIGIT_MODES:
            raise ValueError(f"digits must be one of {DIGIT_MODES}")
        self.fixed: dict[str, int] = {}
        for label, (lo, hi) in LAYOUTS[self.base].items():
            if lo.isalpha():
                self.fixed[lo] = 2 * self.kb.index[label]
                self.fixed[lo.upper()] = 2 * self.kb.index[label] + 1
        for d in "0123456789":
            self.fixed[d] = 2 * self.kb.index[d] + (self.digits == "shifted")
        self.free_chars = [c for c in CHARS if c not in self.fixed]
        self.free_slots = sorted(set(range(N_SLOTS)) - set(self.fixed.values()))
        assert len(self.free_chars) == len(self.free_slots) == 32
        self.free_idx = np.array([CHAR_INDEX[c] for c in self.free_chars])

    def start_pos(self) -> np.ndarray:
        """A valid pos: fixed chars in place, symbols in the free slots in ASCII order."""
        pos = np.zeros(len(CHARS), int)
        for ch, slot in self.fixed.items():
            pos[CHAR_INDEX[ch]] = slot
        pos[self.free_idx] = self.free_slots
        return pos

    def layout_to_pos(self, layout: dict[str, tuple[str, str]]) -> np.ndarray:
        """char index -> slot, validating that every char appears once and fixed chars stay put."""
        pos = np.full(len(CHARS), -1)
        for label, chars in layout.items():
            for shifted, ch in enumerate(chars):
                if pos[CHAR_INDEX[ch]] != -1:
                    raise ValueError(f"{ch!r} appears twice")
                pos[CHAR_INDEX[ch]] = 2 * self.kb.index[label] + shifted
        if (pos == -1).any():
            raise ValueError(f"missing chars: {[CHARS[i] for i in np.where(pos == -1)[0]]}")
        for ch, slot in self.fixed.items():
            if pos[CHAR_INDEX[ch]] != slot:
                raise ValueError(f"{ch!r} moved from its fixed slot")
        return pos

    def pos_to_layout(self, pos: np.ndarray) -> dict[str, tuple[str, str]]:
        slot_char = {int(s): CHARS[i] for i, s in enumerate(pos)}
        return {k.label: (slot_char[2 * i], slot_char[2 * i + 1]) for i, k in enumerate(self.kb.keys)}

    def compatible(self) -> dict[str, dict[str, tuple[str, str]]]:
        """The known layouts that keep this problem's letters and digits (usable as baselines)."""
        out = {}
        for name, layout in LAYOUTS.items():
            try:
                self.layout_to_pos(layout)
            except ValueError:
                continue
            out[name] = layout
        return out


# --- evaluation ---------------------------------------------------------------------
class Evaluator:
    def __init__(self, problem: Problem, unigrams: dict[str, float], bigrams: dict[str, float],
                 p: Params = Params(), trigrams: dict[str, float] | None = None):
        self.problem, self.p = problem, p
        self.uni = np.zeros(len(CHARS))
        self.bi = np.zeros((len(CHARS), len(CHARS)))
        for ch, w in unigrams.items():
            if ch in CHAR_INDEX:
                self.uni[CHAR_INDEX[ch]] += w
        for ab, w in bigrams.items():
            if ab[0] in CHAR_INDEX and ab[1] in CHAR_INDEX:
                self.bi[CHAR_INDEX[ab[0]], CHAR_INDEX[ab[1]]] += w
        self.total = self.uni.sum()
        self.base, self.pair = slot_tables(problem.kb, p)

        self.redirects = Redirects(problem, trigrams) if trigrams else None
        tables = bracket_tables(problem.kb)
        unknown = set(p.bracket_allow) - set(tables)
        if unknown:
            raise ValueError(f"unknown bracket placement {unknown}; choose from {', '.join(tables)}")
        self.bracket_ok = np.zeros((N_SLOTS, N_SLOTS), bool)
        for name in p.bracket_allow:
            self.bracket_ok |= tables[name]
        self.brackets = [(CHAR_INDEX[pr[0]], CHAR_INDEX[pr[1]]) for pr in p.bracket_pairs]

    def bracket_violations(self, pos: np.ndarray) -> int:
        return sum(not self.bracket_ok[pos[o], pos[c]] for o, c in self.brackets)

    def typing_cost(self, pos: np.ndarray) -> float:
        """Average cost per keystroke."""
        c = float(self.uni @ self.base[pos] + (self.bi * self.pair[np.ix_(pos, pos)]).sum())
        if self.redirects is not None and self.p.redirect:
            c += self.p.redirect * self.redirects.weight(pos)
        return c / self.total

    def cost(self, pos: np.ndarray) -> float:
        """What the optimizer minimizes: typing cost + bracket penalties."""
        c = self.typing_cost(pos)
        if self.brackets:
            c += self.p.bracket_penalty * self.bracket_violations(pos)
        return c

    def stats(self, pos: np.ndarray) -> dict[str, float]:
        kb = self.problem.kb
        keys = pos // 2
        shifted = pos % 2
        rows = np.array([kb.keys[k].row for k in keys])
        fingers = np.array([kb.keys[k].finger for k in keys])
        sfb = (fingers[:, None] == fingers[None, :]) & (keys[:, None] != keys[None, :])
        sym = np.isin(np.arange(len(CHARS)), self.problem.free_idx)
        out = {
            "cost": self.typing_cost(pos),
            "shifted %": 100 * float(self.uni @ shifted) / self.total,
            "number row %": 100 * float(self.uni @ (rows == 0)) / self.total,
            "home row %": 100 * float(self.uni @ (rows == 2)) / self.total,
            "same-finger bigrams %": 100 * float((self.bi * sfb).sum()) / self.bi.sum(),
            "symbols shifted %": 100 * float(self.uni[sym] @ shifted[sym]) / self.uni[sym].sum(),
        }
        if self.redirects is not None:
            out["redirects %"] = 100 * self.redirects.weight(pos) / self.redirects.total
        if self.brackets:
            out["bracket pairs off-rule"] = self.bracket_violations(pos)
        return out


def render(layout: dict[str, tuple[str, str]]) -> str:
    """Two-line-per-row picture: shifted above unshifted."""
    lines = []
    for r, row in enumerate(ROWS):
        indent = " " * int(ROW_OFFSET[r] * 4)
        lines.append(indent + " ".join(f" {layout[lab][1]} " for lab, _ in row))
        lines.append(indent + " ".join(f"[{layout[lab][0]}]" for lab, _ in row))
    return "\n".join(lines)
