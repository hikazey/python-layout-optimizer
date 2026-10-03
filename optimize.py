"""Simulated annealing over symbol positions (letters and digits stay fixed).

Usage: python optimize.py [--config config.toml] [--set cost.shift=2.5] [--restarts 8] [--iters 200000]
Writes layouts/<name>/layout.json and prints the best layout next to the baselines. The name defaults
to the language and base layout ("Python Programmer Dvorak" -> layouts/python-programmer-dvorak/);
set --name for variants. Then run export.py on that folder.
"""
import argparse
import dataclasses
import json
import math
import time
from pathlib import Path

import numpy as np

from config import DEFAULT_PATH, load
from model import BASE_NAMES, LAYOUTS_DIR, Evaluator, Problem, render, slug


def random_pos(problem: Problem, rng: np.random.Generator) -> np.ndarray:
    pos = problem.start_pos()
    pos[problem.free_idx] = rng.permutation(problem.free_slots)
    return pos


def pair_placements(ev: Evaluator) -> list[np.ndarray]:
    """For each bracket pair, the (open slot, close slot) placements that keep it learnable."""
    free = np.zeros(len(ev.bracket_ok), bool)
    free[ev.problem.free_slots] = True
    ok = np.argwhere(ev.bracket_ok & free[:, None] & free[None, :])
    return [ok for _ in ev.brackets]


def place(pos: np.ndarray, ch: int, slot: int) -> None:
    """Put char ch on slot, swapping with whatever is there."""
    other = np.flatnonzero(pos == slot)[0]
    pos[ch], pos[other] = pos[other], pos[ch]


def move_pair(pos: np.ndarray, pair: tuple[int, int], slots: np.ndarray) -> np.ndarray:
    new = pos.copy()
    place(new, pair[0], slots[0])
    place(new, pair[1], slots[1])
    return new


def anneal(ev: Evaluator, pos: np.ndarray, iters: int, t0: float, t1: float,
           rng: np.random.Generator, pair_moves: float = 0.1) -> tuple[np.ndarray, float]:
    """Swap two symbols, or (with probability pair_moves) move a whole bracket pair to another
    learnable placement, so pairs don't freeze where they first got together."""
    free = ev.problem.free_idx
    placements = pair_placements(ev)
    pos = pos.copy()
    cur = ev.cost(pos)
    best, best_pos = cur, pos.copy()
    pairs = rng.integers(0, len(free), size=(iters, 2))
    accept = rng.random(iters)
    kind = rng.random(iters)
    for i in range(iters):
        if ev.brackets and kind[i] < pair_moves:
            k = rng.integers(len(ev.brackets))
            new_pos = move_pair(pos, ev.brackets[k], placements[k][rng.integers(len(placements[k]))])
        else:
            a, b = free[pairs[i, 0]], free[pairs[i, 1]]
            if a == b:
                continue
            new_pos = pos.copy()
            new_pos[a], new_pos[b] = pos[b], pos[a]
        t = t0 * (t1 / t0) ** (i / iters)
        new = ev.cost(new_pos)
        if new <= cur or accept[i] < math.exp((cur - new) / t):
            pos, cur = new_pos, new
            if cur < best:
                best, best_pos = cur, pos.copy()
    return best_pos, best


def polish(ev: Evaluator, pos: np.ndarray) -> tuple[np.ndarray, float]:
    """Greedy pairwise swaps and bracket-pair moves until none improves: a local optimum."""
    free = ev.problem.free_idx
    placements = pair_placements(ev)
    pos = pos.copy()
    cur = ev.cost(pos)
    improved = True
    while improved:
        improved = False
        for i in range(len(free)):
            for j in range(i + 1, len(free)):
                a, b = free[i], free[j]
                pos[a], pos[b] = pos[b], pos[a]
                new = ev.cost(pos)
                if new < cur - 1e-12:
                    cur, improved = new, True
                else:
                    pos[a], pos[b] = pos[b], pos[a]
        for pair, options in zip(ev.brackets, placements):
            for slots in options:
                new_pos = move_pair(pos, pair, slots)
                new = ev.cost(new_pos)
                if new < cur - 1e-12:
                    pos, cur, improved = new_pos, new, True
    return pos, cur


def print_stats(name: str, stats: dict[str, float]) -> None:
    print(f"{name:20s} " + "  ".join(f"{k} {v:.3f}" if k == "cost" else f"{k} {v:.1f}"
                                     for k, v in stats.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE",
                    help="override a config value, e.g. --set cost.shift=2.5 (repeatable)")
    ap.add_argument("--name", help="layout name; default: language + base layout")
    ap.add_argument("--dir", type=Path, default=LAYOUTS_DIR, help="where layout folders go")
    ap.add_argument("--restarts", type=int, default=8)
    ap.add_argument("--iters", type=int, default=200_000)
    ap.add_argument("--t0", type=float, default=0.02)
    ap.add_argument("--t1", type=float, default=1e-5)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    cfg = load(args.config, args.set)
    problem = cfg.problem()
    counts = json.loads(cfg.counts.read_text())
    if counts.get("language", "python") != cfg.language:
        print(f"note: {cfg.counts} was counted from {counts['language']}, config says {cfg.language}")
    ev = Evaluator(problem, counts["unigrams"], counts["bigrams"], cfg.params, counts.get("trigrams"))
    rng = np.random.default_rng(args.seed)

    baseline_pos = {name: problem.layout_to_pos(lay) for name, lay in cfg.baseline_layouts(problem).items()}
    for name, pos in baseline_pos.items():
        print_stats(name, ev.stats(pos))
    results = []
    start = time.time()
    names = list(baseline_pos)
    for r in range(args.restarts):
        # first restarts begin from the baselines, the rest from random permutations
        init = baseline_pos[names[r]] if r < len(names) else random_pos(problem, rng)
        pos, cost = anneal(ev, init, args.iters, args.t0, args.t1, rng)
        pos, cost = polish(ev, pos)
        results.append((cost, pos))
        print(f"restart {r + 1}/{args.restarts}: {cost:.4f}  ({time.time() - start:.0f}s)")

    results.sort(key=lambda x: x[0])
    best_cost, best_pos = results[0]
    near = sum(c - best_cost < 1e-3 for c, _ in results)
    print(f"\nbest {best_cost:.4f}; {near}/{len(results)} restarts within 0.001 of it; "
          f"spread {results[-1][0] - best_cost:.4f}\n")
    layout = problem.pos_to_layout(best_pos)
    print(render(layout), "\n")
    print_stats("optimized", ev.stats(best_pos))

    name = args.name or f"{cfg.language.title()} {BASE_NAMES[cfg.base]}"
    out = args.dir / slug(name) / "layout.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "name": name,
        "cost": best_cost,
        "config": {"language": cfg.language, "base": cfg.base, "digits": cfg.digits,
                   "params": dataclasses.asdict(cfg.params), "overrides": args.set},
        "restarts": [c for c, _ in results],
        "stats": ev.stats(best_pos),
        "baselines": {n: ev.stats(p) for n, p in baseline_pos.items()},
        "layout": layout,
    }, indent=1))
    print(f"\nwrote {out}\nexport it with: python export.py --layout {out.parent}")


if __name__ == "__main__":
    main()
