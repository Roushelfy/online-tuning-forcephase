"""v9 generator checks (tiny instances; PySAT's own solver; no formal runs).

  /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python -m unittest tests/test_online_selection_v9.py
"""
import importlib.util
import itertools
import math
import random
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gen_v9", ROOT / "scripts/online_selection_v9/generate.py")
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


def structure_of(st_name):
    return GEN.GEN["assign2"]["structures"][st_name] if st_name else \
        {k: GEN.GEN["assign0"][k] for k in ("resources", "list_size", "conflicts_per_task", "capacity_slack", "lower_gap")}


def brute(T, seed, st):
    R, L = st["resources"], st["list_size"]
    rng = random.Random(seed)
    lists = [sorted(rng.sample(range(R), L)) for _ in range(T)]
    edges = GEN.sample_gnm(T, round(st["conflicts_per_task"] * T), rng)
    cap = math.ceil(st["capacity_slack"] * T / R)
    low = None if st.get("lower_gap") is None else max(0, T // R - st["lower_gap"])
    for ch in itertools.product(*lists):
        if any(ch[u] == ch[v] for u, v in edges):
            continue
        cnt = [ch.count(r) for r in range(R)]
        if all(c <= cap for c in cnt) and (low is None or all(c >= low for c in cnt)):
            return True
    return False


class V9GeneratorTests(unittest.TestCase):
    def test_assignment_structures_match_brute_force(self):
        from pysat.solvers import Minisat22
        for st_name in ("A", "B", "C", None):
            st = structure_of(st_name)
            seen = set()
            for seed in range(25):
                T = 9
                (nv, clauses), _ = GEN.assignment(T, seed, st)
                with Minisat22(bootstrap_with=clauses) as s:
                    sat = s.solve()
                self.assertEqual(sat, brute(T, seed, st), (st_name, seed))
                seen.add(sat)
            self.assertTrue(seen, st_name)

    def test_invariant_hash_ignores_renaming_but_not_content(self):
        _, (nv, cl), _ = GEN.gen_rand3(60, 5)
        perm = list(range(1, nv + 1))
        random.Random(1).shuffle(perm)
        mp = {v: perm[v - 1] for v in range(1, nv + 1)}
        cl2 = [[(mp[abs(l)] if l > 0 else -mp[abs(l)]) for l in c] for c in reversed(cl)]
        self.assertEqual(GEN.invariant_hash(nv, cl), GEN.invariant_hash(nv, cl2))
        self.assertNotEqual(GEN.canonical_hash(cl), GEN.canonical_hash(cl2))
        _, (nv3, cl3), _ = GEN.gen_rand3(60, 6)
        self.assertNotEqual(GEN.invariant_hash(nv, cl), GEN.invariant_hash(nv3, cl3))

    def test_deterministic(self):
        for t, p, s in (("rand3", 30, None), ("col3", 20, None), ("assign2", 20, "C"), ("assign0", 20, None)):
            a = GEN.GENERATORS[t](p, 11, s)
            b = GEN.GENERATORS[t](p, 11, s)
            self.assertEqual(GEN.dimacs(*a[1]), GEN.dimacs(*b[1]))

    def test_assign0_equals_v8_assign(self):
        spec = importlib.util.spec_from_file_location("gen_v8", ROOT / "scripts/stratified_v8/generate.py")
        v8 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(v8)
        _, a, _ = v8.gen_assign(40, 3)
        _, b, _ = GEN.gen_assign0(40, 3)
        self.assertEqual(v8.dimacs(*a), GEN.dimacs(*b))


if __name__ == "__main__":
    unittest.main()
