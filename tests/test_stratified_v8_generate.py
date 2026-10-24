"""Generator checks for scripts/stratified_v8/generate.py (tiny instances, PySAT's own solver; no formal runs).

Run with the v8 generator venv inside the container:
  /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python -m unittest tests/test_stratified_v8_generate.py
"""
import importlib.util
import itertools
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gen_v8", ROOT / "scripts/stratified_v8/generate.py")
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


def decode_and_check(T, seed, model):
    """Rebuild the assignment instance's structure and check the solver model against it."""
    import random
    g = GEN.GEN["assign"]
    R, L = g["resources"], g["list_size"]
    rng = random.Random(seed)
    lists = [sorted(rng.sample(range(R), L)) for _ in range(T)]
    M = round(g["conflicts_per_task"] * T)
    edges = set()
    while len(edges) < M:
        u, v = rng.sample(range(T), 2)
        edges.add((min(u, v), max(u, v)))
    cap = math.ceil(g["capacity_slack"] * T / R)
    var, nv = {}, 0
    for t in range(T):
        for r in lists[t]:
            nv += 1
            var[(t, r)] = nv
    pos = {v for v in model if v > 0}
    choice = {}
    for t in range(T):
        chosen = [r for r in lists[t] if var[(t, r)] in pos]
        if len(chosen) != 1:
            return False
        choice[t] = chosen[0]
    for r in range(R):
        if sum(1 for t in range(T) if choice[t] == r) > cap:
            return False
    return all(choice[u] != choice[v] for u, v in edges)


def brute_force_sat(T, seed):
    import random
    g = GEN.GEN["assign"]
    R, L = g["resources"], g["list_size"]
    rng = random.Random(seed)
    lists = [sorted(rng.sample(range(R), L)) for _ in range(T)]
    M = round(g["conflicts_per_task"] * T)
    edges = set()
    while len(edges) < M:
        u, v = rng.sample(range(T), 2)
        edges.add((min(u, v), max(u, v)))
    cap = math.ceil(g["capacity_slack"] * T / R)
    for ch in itertools.product(*lists):
        if all(ch[u] != ch[v] for u, v in edges) and all(ch.count(r) <= cap for r in range(R)):
            return True
    return False


class GeneratorTests(unittest.TestCase):
    def test_assign_encoding_matches_brute_force(self):
        from pysat.solvers import Minisat22
        seen = set()
        for seed in range(30):
            T = 10
            _, (nv, clauses), _ = GEN.gen_assign(T, seed)
            with Minisat22(bootstrap_with=clauses) as s:
                sat = s.solve()
                model = s.get_model() if sat else None
            self.assertEqual(sat, brute_force_sat(T, seed), seed)
            if sat:
                self.assertTrue(decode_and_check(T, seed, model), seed)
            seen.add(sat)
        self.assertEqual(seen, {True, False})  # both outcomes occur at this tiny size

    def test_deterministic_and_comment_free(self):
        for t, p in (("rand3", 20), ("col3", 15), ("assign", 12)):
            a = GEN.GENERATORS[t](p, 123)
            b = GEN.GENERATORS[t](p, 123)
            self.assertEqual(GEN.dimacs(*a[1]), GEN.dimacs(*b[1]))
            self.assertTrue(GEN.dimacs(*a[1]).startswith("p cnf "))
            c = GEN.GENERATORS[t](p, 124)
            self.assertNotEqual(GEN.canonical_hash(a[1][1]), GEN.canonical_hash(c[1][1]))

    def test_sizes(self):
        _, (nv, cl), prm = GEN.gen_rand3(100, 1)
        self.assertEqual((nv, len(cl)), (100, 426))
        self.assertTrue(all(len(c) == 3 for c in cl))
        _, (nv, cl), prm = GEN.gen_col3(100, 1)
        self.assertEqual(nv, 300)
        self.assertEqual(len(cl), 100 + 3 * 100 + 3 * 230)  # ALO + pairwise AMO + edges x colours


if __name__ == "__main__":
    unittest.main()
