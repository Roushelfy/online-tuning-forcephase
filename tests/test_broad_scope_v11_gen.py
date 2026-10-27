"""v11 generators: on tiny instances the CNF (solved by PySAT's MiniSat 2.2, independent of CaDiCaL) is satisfiable
exactly when the problem itself is (brute-force enumeration), every model decodes to a valid solution, and the
alternative encodings agree. Needs the generator venv (cnfgen, python-sat):
  $GENPY -m pytest tests/test_broad_scope_v11_gen.py
"""
import os
import sys

try:
    import pytest
except ImportError:  # generator venv
    pytest = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "broad_scope_v11"))
if pytest is not None:
    pytest.importorskip("pysat")
from pysat.solvers import Minisat22  # noqa: E402
import gen  # noqa: E402
import semantic as SEM  # noqa: E402

TINY = {"vcover": [(8, {}), (10, {})], "jssp": [(2, {"dmax": 4}), (3, {"dmax": 3})], "bwplan": [(3, {"gamma": 1.0}), (4, {"gamma": 1.0}), (4, {})],
        "factor": [(3, {}), (4, {}), (5, {})], "qcp": [(3, {}), (4, {}), (5, {})], "col3": [(6, None), (8, None)]}
ENCS = {"vcover": ["seqcounter", "totalizer"], "jssp": ["order", "time"], "bwplan": ["seq"], "factor": ["array"],
        "qcp": ["minimal", "extended"], "col3": ["direct", "log"]}


def solve(cnf):
    nv, cl = cnf
    if any(len(c) == 0 for c in cl):
        return False, None
    with Minisat22(bootstrap_with=cl) as s:
        if s.solve():
            return True, set(l for l in s.get_model() if l > 0)
        return False, None


def check_family(fam):
    seen = {True: 0, False: 0}
    for size, extra in TINY[fam]:
        for seed in range(12):
            row = {"id": "t", "family": fam, "size": size, "seed": seed}
            if extra:
                row["params"] = extra
            ans = {}
            for enc in ENCS[fam]:
                _, cnf, _, sem = gen.build(row, enc)
                sat, model = solve(cnf)
                ans[enc] = sat
                if sat:
                    ck = "col3log" if (fam == "col3" and enc == "log") else fam
                    assert SEM.check(ck, sem, model), (fam, enc, size, seed)
            truth = SEM.brute("col3" if fam == "col3" else fam, sem)
            assert set(ans.values()) == {truth}, (fam, size, seed, ans, truth)
            seen[truth] += 1
            if fam == "factor":
                assert truth == (sem["task"] == "semiprime")
    assert seen[True] > 0 and seen[False] > 0, (fam, seen)  # both answers occur
    return seen


if __name__ == "__main__":  # the generator venv has no pytest
    for f in sorted(TINY):
        print(f, check_family(f))



def test_families_tiny():
    for f in sorted(TINY):
        print(f, check_family(f))


def test_jssp_dispatch_upper_bound():
    """Every dispatch-rule makespan is achievable (brute force finds a schedule within it)."""
    import families as FAM
    for n in (2, 3):
        for seed in range(10):
            jobs, lb, _ = FAM.jssp_instance(n, seed, {"dmax": 5, "rho": 1.0})
            for rule in ("est_mwkr", "est_spt", "gt_mwkr"):
                ub = FAM.dispatch_makespan(jobs, rule)
                assert ub >= lb
                assert SEM.brute("jssp", {"jobs": jobs, "T": ub})


if __name__ == "__main__":
    test_jssp_dispatch_upper_bound()
    print("jssp dispatch ok")
