"""Scientific scoring checks: censoring, fixed denominators, and oracle certificates."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "completion_eval", ROOT / "scripts/completion_v7/evaluate.py")
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


def config():
    return {
        "metric": "mean_completed_cpu_seconds",
        "methods": ["D", "Fp", "Fm", "selector"],
        "oracle_actions": ["D", "Fp", "Fm"],
        "required_methods": ["D", "selector"],
        "baseline": "D",
        "require_oracle_complete": True,
    }


def run(instance, method, cpu, status="solved", verified=True):
    return {"instance": instance, "method": method, "status": status,
            "verified": verified, "measurement_valid": True, "cpu_seconds": cpu,
            "time_kind": "measured_process_tree_cpu", "source_run_id": "test-fixture"}


class CompletionMetricTests(unittest.TestCase):
    def test_real_completion_above_old_cutoff_and_arithmetic_mean(self):
        records = [run("a", m, t) for m, t in
                   [("D", 1000), ("Fp", 100), ("Fm", 200), ("selector", 110)]]
        records += [run("b", m, t) for m, t in
                    [("D", 20), ("Fp", 30), ("Fm", 10), ("selector", 25)]]
        result = EVAL.summarize(["a", "b"], records, config())
        self.assertTrue(result["primary_comparison_complete"])
        self.assertEqual(result["methods"]["D"]["mean_cpu_seconds"], 510)
        self.assertEqual(result["methods"]["selector"]["mean_cpu_seconds"], 67.5)
        self.assertEqual(result["oracle"]["mean_cpu_seconds"], 55)

    def test_timeout_600_is_not_a_completed_runtime(self):
        records = [run("a", "D", 600, "censored", False),
                   run("a", "Fp", 700), run("a", "Fm", 800),
                   run("a", "selector", 750)]
        result = EVAL.summarize(["a"], records, config())
        self.assertIsNone(result["methods"]["D"]["mean_cpu_seconds"])
        self.assertIsNone(result["oracle"]["mean_cpu_seconds"])
        self.assertIsNone(result["gain_percent_vs_baseline"]["selector"])
        self.assertFalse(result["primary_comparison_complete"])

    def test_no_solved_only_denominator(self):
        records = [run("a", "D", 10), run("b", "D", 300, "censored", False)]
        result = EVAL.summarize(["a", "b"], records, config())
        self.assertEqual(result["methods"]["D"]["completed"], 1)
        self.assertIsNone(result["methods"]["D"]["total_cpu_seconds"])
        self.assertIsNone(result["methods"]["D"]["mean_cpu_seconds"])

    def test_oracle_can_be_certified_without_finishing_slower_arms(self):
        records = [run("a", "D", 1000), run("a", "Fp", 100),
                   run("a", "Fm", 100, "noncompetitive_bound", False),
                   run("a", "selector", 110)]
        result = EVAL.summarize(["a"], records, config())
        self.assertEqual(result["oracle"]["mean_cpu_seconds"], 100)
        self.assertIsNone(result["methods"]["Fm"]["mean_cpu_seconds"])
        self.assertTrue(result["primary_comparison_complete"])

    def test_insufficient_bound_or_error_does_not_certify_oracle(self):
        for status in ("censored", "error"):
            records = [run("a", "D", 1000), run("a", "Fp", 700),
                       run("a", "Fm", 300, status, False)]
            result = EVAL.summarize(["a"], records, config())
            self.assertIsNone(result["oracle"]["mean_cpu_seconds"])
        records[-1] = run("a", "Fm", 900, "error", False)
        self.assertIsNone(EVAL.summarize(["a"], records, config())
                          ["oracle"]["mean_cpu_seconds"])

    def test_unverified_answer_is_incomplete(self):
        for valid in (True, False):
            record = run("a", "D", 10, verified=False)
            record["measurement_valid"] = valid
            self.assertIsNone(EVAL.summarize(["a"], [record], config())
                              ["methods"]["D"]["mean_cpu_seconds"])

    def test_rejects_duplicate_and_off_panel_measurements(self):
        for records in ([run("a", "D", 10), run("a", "D", 9)],
                        [run("b", "D", 10)]):
            with self.assertRaises(ValueError):
                EVAL.summarize(["a"], records, config())

    def test_rejects_penalized_time_source(self):
        record = run("a", "D", 600, "censored", False)
        record["time_kind"] = "PAR2"
        with self.assertRaises(ValueError):
            EVAL.summarize(["a"], [record], config())

    def test_rejects_changed_panel_size(self):
        cfg = config()
        cfg["panel_size"] = 55
        with self.assertRaises(ValueError):
            EVAL.summarize(["a"], [], cfg)

    def test_rejects_invalid_time(self):
        for value in (-1, float("inf"), float("nan"), True, "300"):
            with self.assertRaises(ValueError):
                EVAL.summarize(["a"], [run("a", "D", value)], config())


if __name__ == "__main__":
    unittest.main()
