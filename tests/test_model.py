import numpy as np
import pytest

from model import (CHAR_INDEX, LAYOUTS, Evaluator, Keyboard, Params, Problem, Redirects,
                   bracket_tables, redirect_table, slot_tables)

PD = Problem("programmer-dvorak", "shifted")
KB = Keyboard()


def slot(label, shifted=0):
    return 2 * KB.index[label] + shifted


@pytest.mark.parametrize("name", ["programmer-dvorak", "python-hand"])
def test_baselines_are_valid_and_round_trip(name):
    pos = PD.layout_to_pos(LAYOUTS[name])
    assert sorted(pos) == list(range(94))
    assert PD.pos_to_layout(pos) == LAYOUTS[name]


@pytest.mark.parametrize("base", ["qwerty", "dvorak", "colemak-dh"])
def test_standard_layouts_are_their_own_baseline(base):
    problem = Problem(base, "unshifted")
    assert base in problem.compatible()
    assert "programmer-dvorak" not in problem.compatible()


def test_letters_follow_the_base_layout():
    assert Problem("colemak-dh").fixed["t"] == slot("f")
    assert Problem("dvorak").fixed["S"] == slot(";", 1)
    assert set(Problem("qwerty").free_chars) == set(Problem("dvorak").free_chars)


def test_moving_a_fixed_char_is_rejected():
    bad = dict(LAYOUTS["programmer-dvorak"])
    bad["q"], bad["w"] = bad["w"], ("a", bad["q"][1])  # put 'a' somewhere else
    with pytest.raises(ValueError):
        PD.layout_to_pos(bad)


def test_digit_modes():
    for d in "1234567890":
        assert PD.fixed[d] == slot(d, 1)
        assert Problem("qwerty", "unshifted").fixed[d] == slot(d)


def test_start_pos_is_valid():
    problem = Problem("colemak-dh", "shifted")
    layout = problem.pos_to_layout(problem.start_pos())
    problem.layout_to_pos(layout)  # raises if anything is off


def test_same_finger_bigram_costs_more_than_roll():
    _, pair = slot_tables(KB, Params())
    assert pair[slot("f"), slot("r")] > pair[slot("a"), slot("f")]  # f->r same finger; a->f roll-ish
    assert pair[slot("s"), slot("d")] < 0  # inward roll on home row
    assert pair[slot("d"), slot("s")] == 0  # outward: neutral


def test_shift_adds_base_cost_and_held_shift_refunds():
    p = Params()
    base, pair = slot_tables(KB, p)
    assert base[slot("a", 1)] - base[slot("a")] == pytest.approx(p.shift)
    assert pair[slot("a", 1), slot("s", 1)] == pytest.approx(pair[slot("a"), slot("s")] - p.held_shift)


def test_custom_keyboard_changes_costs():
    effort = [[1.0] * 13, [1.0] * 13, [1.0] * 11, [1.0] * 10]
    base, _ = slot_tables(Keyboard(effort=effort))
    assert base[slot("`")] == 1.0
    with pytest.raises(ValueError):
        Keyboard(effort=[[1.0] * 13])


def test_cost_prefers_putting_frequent_symbol_on_home_row():
    pos = PD.layout_to_pos(LAYOUTS["programmer-dvorak"])
    ev = Evaluator(PD, {"_": 100.0, "-": 1.0}, {})
    swapped = pos.copy()
    a, b = CHAR_INDEX["_"], CHAR_INDEX["-"]
    swapped[a], swapped[b] = swapped[b], swapped[a]  # '_' was shifted, now unshifted
    assert ev.cost(swapped) < ev.cost(pos)


def test_cost_is_per_keystroke():
    pos = PD.layout_to_pos(LAYOUTS["programmer-dvorak"])
    one = Evaluator(PD, {"a": 1.0}, {}).cost(pos)
    many = Evaluator(PD, {"a": 50.0}, {}).cost(pos)
    assert one == pytest.approx(many)
    assert np.isclose(one, slot_tables(KB)[0][slot("a")])


def test_redirects():
    r = redirect_table(KB)
    assert r[slot("f"), slot("s"), slot("d")]       # index, ring, middle: changes direction
    assert not r[slot("a"), slot("s"), slot("d")]   # pinky -> middle: a roll
    assert not r[slot("f"), slot("j"), slot("d")]   # two hands
    assert not r[slot("f"), slot("r"), slot("s")]   # same finger twice is an sfb, not a redirect


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # no bigrams: some stats are 0/0
def test_redirect_cost_uses_trigrams():
    pos = PD.layout_to_pos(LAYOUTS["programmer-dvorak"])
    # Programmer Dvorak: u on f, o on s, e on d -> "uoe" is a redirect; "aoe" isn't
    tri = {"uoe": 10.0, "aoe": 30.0}
    ev = Evaluator(PD, {"a": 1.0}, {}, Params(redirect=1.0), tri)
    assert ev.stats(pos)["redirects %"] == pytest.approx(25.0)
    assert ev.cost(pos) == pytest.approx(slot_tables(KB)[0][slot("a")] + 10.0)


def test_bracket_tables():
    t = bracket_tables(KB)
    assert t["adjacent"][slot("["), slot("]")]
    assert not t["adjacent"][slot("]"), slot("[")]          # close must be right of open
    assert not t["adjacent"][slot("["), slot("]", 1)]       # same layer
    assert t["mirrored"][slot("f", 1), slot("j", 1)]
    assert t["mirrored"][slot("4"), slot("7")]
    assert not t["mirrored"][slot("j"), slot("f")]
    assert not t["mirrored"][slot("5"), slot("6")]          # 6 is on the left hand here


def test_bracket_penalty_counts_broken_pairs():
    pos = PD.layout_to_pos(LAYOUTS["programmer-dvorak"])  # [{}( on 1-4 ... ) on 8, ] on 0
    p = Params(bracket_pairs=("()", "[]", "{}"), bracket_penalty=5.0)
    plain = Evaluator(PD, {"a": 1.0}, {})
    ev = Evaluator(PD, {"a": 1.0}, {}, p)
    assert ev.bracket_violations(pos) == 2  # { } adjacent; ( on 5 and ) on 8 aren't; [ ] neither
    assert ev.cost(pos) == pytest.approx(plain.cost(pos) + 10.0)


def test_grouped_redirects_match_brute_force():
    rng = np.random.default_rng(0)
    # trigrams with 0-3 movable chars, including repeated chars
    words = ["aoe", "u.e", "(_)", "._.", "((a", "uoe", "{[(", "h,t", "_-_", "s:="]
    tri = {w: float(rng.integers(1, 9)) for w in words}
    red = Redirects(PD, tri)
    table = redirect_table(KB)
    for _ in range(20):
        pos = PD.start_pos()
        pos[PD.free_idx] = rng.permutation(PD.free_slots)
        brute = sum(w * table[pos[CHAR_INDEX[t[0]]], pos[CHAR_INDEX[t[1]]], pos[CHAR_INDEX[t[2]]]]
                    for t, w in tri.items())
        assert red.weight(pos) == pytest.approx(brute)
    assert red.total == sum(tri.values())
