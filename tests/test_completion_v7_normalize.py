"""Adoption-order checks for scripts/completion_v7/normalize.py (no solver runs)."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("normalize_v7", ROOT / "scripts/completion_v7/normalize.py")
NORM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NORM)


def v6(h, m, status, cpu):
    return {"instance": h, "method": m, "status": status, "cpu_seconds": cpu, "time_kind": "measured_process_tree_cpu",
            "source_run_id": "fixture", "verified": status == "solved", "measurement_valid": True, "origin": "v6"}


def v7(h, m, kind, status, cpu, formal=None, action=None, stage="stage1"):
    r = {"instance": h, "method": m, "kind": kind, "status": status, "cpu": cpu, "id": f"{h}{m}", "_stage": stage,
         "host": "x", "stop_reason": None if status == "solved" else "budget"}
    if formal is not None:
        r["formal_cpu"], r["action"] = formal, action
    return r


class AdoptionOrderTests(unittest.TestCase):
    def test_v6_solve_has_priority_and_derived_formal_d(self):
        P = ["a", "b"]
        old = {("a", "D"): v6("a", "D", "solved", 10), ("b", "D"): v6("b", "D", "censored", 300),
               ("a", "P1_M05_long"): v6("a", "P1_M05_long", "solved", 11),
               ("b", "P1_M05_long"): v6("b", "P1_M05_long", "censored", 300)}
        wrap = {"b": v7("b", "P1_M05_long", "wrapper", "solved", 905.0, formal=904.9, action="D")}
        out = {(r["instance"], r["method"]): r for r in NORM.adopt(P, old, {}, wrap)}
        self.assertEqual(out[("a", "D")]["cpu_seconds"], 10)
        self.assertEqual(out[("b", "D")]["cpu_seconds"], 904.9)
        self.assertTrue(out[("b", "D")]["source_run_id"].endswith("formal_subprocess"))
        self.assertEqual(out[("b", "P1_M05_long")]["cpu_seconds"], 905.0)

    def test_standalone_long_run_beats_derived_and_v6_bound(self):
        P = ["a"]
        old = {("a", "D"): v6("a", "D", "censored", 300)}
        fixed = {("a", "D"): v7("a", "D", "fixed", "censored", 4000.0)}
        wrap = {"a": v7("a", "P1_M05_long", "wrapper", "censored", 4000.1, formal=3999.0, action="D")}
        out = {(r["instance"], r["method"]): r for r in NORM.adopt(P, old, fixed, wrap)}
        self.assertEqual(out[("a", "D")]["cpu_seconds"], 4000.0)
        self.assertEqual(out[("a", "D")]["status"], "censored")

    def test_non_d_choice_is_not_a_d_measurement(self):
        P = ["a"]
        old = {("a", "D"): v6("a", "D", "censored", 300)}
        wrap = {"a": v7("a", "P1_M05_long", "wrapper", "solved", 240.0, formal=236.0, action="Fp")}
        out = {(r["instance"], r["method"]): r for r in NORM.adopt(P, old, {}, wrap)}
        self.assertEqual(out[("a", "D")]["cpu_seconds"], 300)
        self.assertEqual(out[("a", "D")]["status"], "censored")

    def test_missing_everything_is_missing(self):
        out = NORM.adopt(["a"], {}, {}, {})
        self.assertTrue(all(r["status"] == "missing" for r in out))


if __name__ == "__main__":
    unittest.main()
