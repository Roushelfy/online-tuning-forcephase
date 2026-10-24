"""Resource policy integration checks without launching a SAT solver."""
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import resource_policy


def load_module(relative, data):
    fprun = types.ModuleType("fprun")
    fprun.DATA = str(data)
    fprun.physical_cores = lambda: list(range(6))
    spec = importlib.util.spec_from_file_location(
        "test_" + relative.replace("/", "_").replace(".", "_"), ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"fprun": fprun, "twlib": types.ModuleType("twlib")}):
        spec.loader.exec_module(module)
    return module


class FakeJob:
    instances = []

    def __init__(self, spec, stage, core=None):
        self.spec, self.id, self.core = spec, spec["instance"], core
        self.started, self.done = False, False
        self.cpu, self.calls = 0, 0
        self.stop_reason, self.exit_code = None, 10
        self.terminated = []
        self.instances.append(self)

    def launch(self, core=None):
        self.started = True
        if core is not None:
            self.core = core

    def poll(self):
        self.cpu = 1_000_000
        self.calls += 1
        if self.calls >= 2:
            self.done = True
        return self.done

    def term(self, reason):
        self.stop_reason = reason
        self.terminated.append(reason)

    def kill_if_late(self):
        pass


class ResourcePolicyTests(unittest.TestCase):
    def test_legacy_stage_and_run_caps_cannot_limit_current_plan(self):
        policy = resource_policy.load_policy(ROOT)
        original = {"budget_cpu_hours": 0.001,
                    "jobs": [{"instance": "a", "cap_cpu": 900}]}
        effective = resource_policy.prepare_plan(original, policy)
        self.assertIsNone(effective["budget_cpu_hours"])
        self.assertIsNone(effective["jobs"][0]["cap_cpu"])
        self.assertEqual(original["jobs"][0]["cap_cpu"], 900)
        self.assertEqual(original["budget_cpu_hours"], 0.001)

    def test_explicit_oracle_certificate_retained_but_invalid_bound_rejected(self):
        policy = resource_policy.load_policy(ROOT)
        job = {"instance": "a", "cap_cpu": 500,
               "cap_kind": "oracle_noncompetitive_bound"}
        effective = resource_policy.prepare_plan({"jobs": [job]}, policy)
        self.assertEqual(effective["jobs"][0]["cap_cpu"], 500)
        for invalid in (0, -1, float("inf"), float("nan"), True):
            with self.assertRaises(ValueError):
                resource_policy.prepare_plan({"jobs": [{**job, "cap_cpu": invalid}]}, policy)

    def test_both_controllers_finish_jobs_with_no_budget_argument_or_zero_legacy_budget(self):
        for relative in ("scripts/stratified_v8/runner.py", "scripts/completion_v7/longrun.py"):
            for legacy_args in ([], ["--budget-cpu-hours", "0"]):
                with self.subTest(controller=relative, arguments=legacy_args), tempfile.TemporaryDirectory() as tmp:
                    tmp = pathlib.Path(tmp)
                    module = load_module(relative, tmp)
                    module.OUT = str(tmp / "runs")
                    plan = tmp / "plan.json"
                    plan.write_text(json.dumps({"jobs": [
                        {"instance": "a", "method": "D", "kind": "fixed", "cap_cpu": 900},
                        {"instance": "b", "method": "D", "kind": "fixed", "cap_cpu": 900},
                    ]}))
                    FakeJob.instances = []
                    finalized = []

                    def finalize(job, stage_dir):
                        result = {"instance": job.id, "method": job.spec["method"],
                                  "status": "solved", "cpu": job.cpu}
                        pathlib.Path(stage_dir, job.id + ".json").write_text(json.dumps(result))
                        finalized.append(result)
                        return result

                    argv = [relative, "--plan", str(plan), "--stage", "unlimited-test"] + legacy_args
                    with mock.patch.object(module, "Job", FakeJob), \
                            mock.patch.object(module, "finalize", finalize), \
                            mock.patch.object(module, "job_key", lambda job, stage: ({}, job["instance"])), \
                            mock.patch.object(module.os, "sched_setaffinity"), \
                            mock.patch.object(module.time, "sleep"), \
                            mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                        module.main()
                    self.assertEqual(len(finalized), 2)
                    self.assertTrue(all(job.done and not job.terminated for job in FakeJob.instances))
                    heartbeat = json.loads((tmp / "runs/unlimited-test/progress.json").read_text())
                    effective = json.loads((tmp / "runs/unlimited-test/effective_plan.json").read_text())
                    self.assertTrue(all(j["cap_cpu"] is None and j["resource_policy_id"] for j in effective["jobs"]))
                    self.assertIsNone(heartbeat["budget_cpu_hours"])
                    self.assertGreater(heartbeat["spent_cpu_hours"], 200)

    def test_historical_run_ids_remain_unchanged(self):
        for relative in ("scripts/stratified_v8/runner.py", "scripts/completion_v7/longrun.py"):
            with self.subTest(controller=relative), tempfile.TemporaryDirectory() as tmp:
                module = load_module(relative, tmp)
                module.sha = lambda path: "binary-sha"
                job = {"instance": "a", "method": "D", "kind": "fixed",
                       "sha256": "cnf-sha", "cap_cpu": 900}
                key, rid = module.job_key(job, "historical-stage")
                expected = {"schema": 1, "stage": "historical-stage", "instance": "a",
                            "method": "D", "formal_sha256": "binary-sha",
                            "mem_mb": 16000, "cap_cpu": 900, "seed": 0, "proof": "lrat",
                            "args": ["--lrat=1", "--phase=1", "--forcephase=0", "--fpc=1"]}
                if "stratified" in relative:
                    expected.update(cnf_sha256="cnf-sha", rep=0)
                else:
                    expected["kind"] = "fixed"
                expected_id = hashlib.sha1(json.dumps(expected, sort_keys=True).encode()).hexdigest()
                self.assertEqual(key, expected)
                self.assertEqual(rid, expected_id)
                new = resource_policy.prepare_plan({"jobs": [job]},
                                                   resource_policy.load_policy(ROOT))["jobs"][0]
                self.assertNotEqual(module.job_key(new, "historical-stage")[1], rid)

    def test_oracle_planner_no_longer_drops_jobs_for_a_stage_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            module = load_module("scripts/completion_v7/stage2_plan.py", tmp)
            module.RES = str(tmp)
            records = [{"instance": "a", "method": "D", "status": "solved", "cpu_seconds": 3600},
                       {"instance": "a", "method": "Fp", "status": "censored", "cpu_seconds": 300},
                       {"instance": "a", "method": "Fm", "status": "censored", "cpu_seconds": 300}]
            reuse = [{**r, "status": "censored", "cpu_seconds": 300} for r in records]
            (tmp / "normalized.json").write_text(json.dumps(records))
            (tmp / "reuse_records.json").write_text(json.dumps(reuse))
            out = tmp / "plan.json"
            args = ["stage2_plan.py", "--budget-cpu-hours", "0", "--out", str(out)]
            with mock.patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                module.main()
            plan = json.loads(out.read_text())
            self.assertEqual(len(plan["jobs"]), 2)
            self.assertFalse(plan["not_scheduled"])
            self.assertIsNone(plan["budget_cpu_hours"])
            self.assertTrue(all(j["cap_kind"] == "oracle_noncompetitive_bound" for j in plan["jobs"]))


if __name__ == "__main__":
    unittest.main()
