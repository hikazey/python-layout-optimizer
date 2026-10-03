import numpy as np

from model import CHAR_INDEX, LAYOUTS, Evaluator, Params, Problem
from optimize import move_pair, pair_placements, polish

PD = Problem("programmer-dvorak", "shifted")
P = Params(bracket_pairs=("()", "[]", "{}"))


def test_move_pair_keeps_a_valid_layout_and_places_both_chars():
    ev = Evaluator(PD, {"a": 1.0}, {}, P)
    pos = PD.layout_to_pos(LAYOUTS["programmer-dvorak"])
    o, c = ev.brackets[0]
    for slots in pair_placements(ev)[0][:50]:
        new = move_pair(pos, (o, c), slots)
        assert (new[o], new[c]) == tuple(slots)
        PD.layout_to_pos(PD.pos_to_layout(new))  # raises if a fixed char moved


def test_polish_fixes_broken_pairs():
    ev = Evaluator(PD, {"(": 5.0, ")": 5.0, "a": 1.0}, {"a(": 1.0}, P)
    pos = PD.layout_to_pos(LAYOUTS["programmer-dvorak"])  # two pairs off-rule
    pos, cost = polish(ev, pos)
    assert ev.bracket_violations(pos) == 0
    assert np.isclose(cost, ev.cost(pos))
    assert CHAR_INDEX["("] in ev.brackets[0]
