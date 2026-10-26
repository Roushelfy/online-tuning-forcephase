"""Per-run CPU timeout (configs/run_timeout_policy.json) with controlled subprocesses, no SAT solver:
a fake 'cadical' burns CPU or prints a model for a trivial CNF. The v9 runner is run as a subprocess with a
1.5 s test policy (FP_RUN_TIMEOUT_POLICY), a temporary FP_DATA / work dir and FP_FORMAL_OVERRIDE.
Answers are still verified by the real build/tools/checkmodel.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_timeout_policy  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import resource, sys
cnf = [a for a in sys.argv[1:] if a.endswith(".cnf")][0]
spec = [l for l in open(cnf).read().splitlines() if l.startswith("c FAKE")][0].split()
def cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime
if spec[2] == "burn":
    while True:
        pass
while cpu() < float(spec[3]):
    pass
print("s SATISFIABLE", flush=True)
print("v 1 0", flush=True)
sys.exit(10)
'''
LIMIT = 1.5


class RunTimeoutPolicyTests(unittest.TestCase):
    def test_apply_caps_ordinary_jobs_and_keeps_shorter_oracle_bounds(self):
        pol = {"policy_id": "p", "per_instance_method_cpu_seconds": 3600, "project_cpu_hours_cap": None,
               "stage_cpu_hours_cap": None}
        plan = {"jobs": [{"instance": "a", "cap_cpu": None},
                         {"instance": "b", "cap_cpu": 900},  # legacy pilot/formal cap -> uniform 3600
                         {"instance": "c", "cap_cpu": 500, "cap_kind": "oracle_noncompetitive_bound"},
                         {"instance": "d", "cap_cpu": 9000, "cap_kind": "oracle_noncompetitive_bound"}]}
        eff = run_timeout_policy.apply(plan, pol)
        caps = [(j["cap_cpu"], j["cap_kind"]) for j in eff["jobs"]]
        self.assertEqual(caps, [(3600, "policy_timeout"), (3600, "policy_timeout"),
                                (500, "oracle_noncompetitive_bound"), (3600, "policy_timeout")])
        self.assertTrue(all(j["run_policy_id"] == "p" for j in eff["jobs"]))
        self.assertIsNone(plan["jobs"][0]["cap_cpu"])  # input untouched
        self.assertEqual(run_timeout_policy.classify_after_cap(True, 3601.0, eff["jobs"][0], "solved"), "policy_timeout")
        self.assertEqual(run_timeout_policy.classify_after_cap(True, 3599.0, eff["jobs"][0], "solved"), "solved")
        # kernel SIGXCPU at the cap counts as a timeout even if the reported CPU is a little below cap - 0.5 s
        self.assertTrue(run_timeout_policy.is_timeout(3599.07, eff["jobs"][0], -24))
        self.assertFalse(run_timeout_policy.is_timeout(3599.07, eff["jobs"][0], -15))
        self.assertFalse(run_timeout_policy.is_timeout(10.0, {"cap_kind": None, "cap_cpu": None}, -24))

    def test_repository_policy_is_3600_and_aggregate_unlimited(self):
        pol = run_timeout_policy.load(ROOT)
        self.assertEqual(pol["per_instance_method_cpu_seconds"], 3600)
        self.assertIsNone(pol["project_cpu_hours_cap"])

    def test_v9_runner_with_controlled_subprocesses(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            fake = tmp / "cadical"
            fake.write_text(FAKE)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            cnfdir = tmp / "data" / "online_selection_v9" / "cnf"
            cnfdir.mkdir(parents=True)
            cnfs = {"burn": "c FAKE burn\np cnf 1 1\n1 0\n", "quick": "c FAKE answer 0.2\np cnf 1 1\n1 0\n"}
            sha = {}
            for name, text in cnfs.items():
                (cnfdir / f"t-{name}.cnf").write_text(text)
                sha[name] = hashlib.sha256(text.encode()).hexdigest()
            strat = tmp / "presolve.json"
            strat.write_text(json.dumps({"name": "t", "kind": "presolve", "tau": 0.5, "fallback": "Fp"}))
            pol = tmp / "policy.json"
            pol.write_text(json.dumps({"policy_id": "test-1.5s", "per_instance_method_cpu_seconds": LIMIT,
                                       "project_cpu_hours_cap": None, "stage_cpu_hours_cap": None}))
            jobs = []
            for name in cnfs:
                b = {"instance": f"t-{name}", "sha256": sha[name], "rep": 0}
                jobs += [dict(b, method="D"), dict(b, method="W", strategy=str(strat))]
            plan = tmp / "plan.json"
            plan.write_text(json.dumps({"stage": "t", "jobs": jobs}))
            env = dict(os.environ, FP_DATA=str(tmp / "data"), V9_WORK=str(tmp / "work"), FP_RUN_TIMEOUT_POLICY=str(pol),
                       FP_FORMAL_OVERRIDE=str(fake))
            r = subprocess.run([sys.executable, str(ROOT / "scripts/online_selection_v9/runner.py"), "--plan", str(plan),
                                "--stage", "t"], env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            recs = {}
            for p in (tmp / "data/runs/online_selection_v9/t").glob("*.json"):
                if p.name in ("progress.json", "effective_plan.json"):
                    continue
                x = json.loads(p.read_text())
                recs[(x["instance"], x["method"])] = x
            # fixed arm that never answers: stopped at the per-run limit -> policy_timeout, actual CPU kept
            d = recs[("t-burn", "D")]
            self.assertEqual(d["status"], "policy_timeout")
            self.assertGreaterEqual(d["cpu"], LIMIT)
            self.assertLess(d["cpu"], LIMIT + 1.5)
            # wrapper: probe (0.5 s window) + restart share ONE limit (not probe + a fresh limit)
            w = recs[("t-burn", "W")]
            self.assertEqual(w["status"], "policy_timeout")
            self.assertEqual(w["decision"]["path"], "fallback")
            self.assertGreaterEqual(w["decision"]["probe"]["cpu"], 0.5)
            self.assertGreaterEqual(w["cpu"], LIMIT)
            self.assertLess(w["cpu"], LIMIT + 1.5)
            # answers within the limit are verified by the real checker; the probe's answer is reused
            for m in ("D", "W"):
                q = recs[("t-quick", m)]
                self.assertEqual(q["status"], "solved", q.get("verification"))
                self.assertTrue(q["verification"]["ok"])
            self.assertEqual(recs[("t-quick", "W")]["decision"]["path"], "probe_solved")
            eff = json.loads((tmp / "data/runs/online_selection_v9/t/effective_plan.json").read_text())
            self.assertTrue(all(j["cap_cpu"] == LIMIT and j["cap_kind"] == "policy_timeout" for j in eff["jobs"]))

    def _fake(self, tmp):
        fake = tmp / "cadical"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        pol = tmp / "policy.json"
        pol.write_text(json.dumps({"policy_id": "test-1.5s", "per_instance_method_cpu_seconds": LIMIT,
                                   "project_cpu_hours_cap": None, "stage_cpu_hours_cap": None}))
        return fake, pol

    def _records(self, d):
        out = {}
        for p in pathlib.Path(d).glob("*.json"):
            if p.name in ("progress.json", "effective_plan.json"):
                continue
            x = json.loads(p.read_text())
            out[(x["instance"], x["method"])] = x
        return out

    def test_v8_runner_fixed_arms_with_controlled_subprocesses(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            fake, pol = self._fake(tmp)
            cnfdir = tmp / "data" / "stratified_v8" / "cnf"
            cnfdir.mkdir(parents=True)
            jobs = []
            for name, text in (("burn", "c FAKE burn\np cnf 1 1\n1 0\n"), ("quick", "c FAKE answer 0.2\np cnf 1 1\n1 0\n")):
                (cnfdir / f"t-{name}.cnf").write_text(text)
                jobs.append({"instance": f"t-{name}", "sha256": hashlib.sha256(text.encode()).hexdigest(), "method": "D",
                             "rep": 0, "cap_cpu": 900})  # legacy cap -> replaced by the policy cap
            plan = tmp / "plan.json"
            plan.write_text(json.dumps({"stage": "t8", "jobs": jobs}))
            env = dict(os.environ, FP_DATA=str(tmp / "data"), V8_WORK=str(tmp / "work"), FP_RUN_TIMEOUT_POLICY=str(pol),
                       FP_FORMAL_OVERRIDE=str(fake))
            r = subprocess.run([sys.executable, str(ROOT / "scripts/stratified_v8/runner.py"), "--plan", str(plan),
                                "--stage", "t8"], env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            recs = self._records(tmp / "data/runs/stratified_v8/t8")
            self.assertEqual(recs[("t-burn", "D")]["status"], "policy_timeout")
            self.assertLess(recs[("t-burn", "D")]["cpu"], LIMIT + 1.5)
            self.assertEqual(recs[("t-quick", "D")]["status"], "solved")

    def test_v7_longrun_fixed_arms_with_controlled_subprocesses(self):
        import lzma
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            fake, pol = self._fake(tmp)
            cnfdir = tmp / "data" / "benchmarks" / "cnf"
            cnfdir.mkdir(parents=True)
            jobs = []
            for h, text in (("aaaa", "c FAKE burn\np cnf 1 1\n1 0\n"), ("bbbb", "c FAKE answer 0.2\np cnf 1 1\n1 0\n")):
                with lzma.open(cnfdir / f"{h}.cnf.xz", "wt") as f:
                    f.write(text)
                jobs.append({"instance": h, "method": "D", "kind": "fixed"})
            plan = tmp / "plan.json"
            plan.write_text(json.dumps({"stage": "t7", "jobs": jobs}))
            env = dict(os.environ, FP_DATA=str(tmp / "data"), FP_LOCAL=str(tmp / "local"), V7_WORK=str(tmp / "work"),
                       FP_RUN_TIMEOUT_POLICY=str(pol), FP_FORMAL_OVERRIDE=str(fake))
            r = subprocess.run([sys.executable, str(ROOT / "scripts/completion_v7/longrun.py"), "--plan", str(plan),
                                "--stage", "t7"], env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            recs = self._records(tmp / "data/runs/completion_v7/t7")
            self.assertEqual(recs[("aaaa", "D")]["status"], "policy_timeout")
            self.assertLess(recs[("aaaa", "D")]["cpu"], LIMIT + 2.5)
            self.assertEqual(recs[("bbbb", "D")]["status"], "solved")

    def test_wrapper_enforces_the_cap_on_its_whole_tree_without_a_controller(self):
        import resource as res
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            fake, _ = self._fake(tmp)
            cnf = tmp / "burn.cnf"
            cnf.write_text("c FAKE burn\np cnf 1 1\n1 0\n")
            strat = tmp / "s.json"
            strat.write_text(json.dumps({"name": "t", "kind": "presolve", "tau": 0.5, "fallback": "Fp"}))
            env = dict(os.environ, FP_FORMAL_OVERRIDE=str(fake), FP_RUN_CPU_LIMIT="2.0")
            p = subprocess.Popen([sys.executable, str(ROOT / "scripts/online_selection_v9/presolve.py"), "--strategy", str(strat),
                                  "--cnf", str(cnf), "--workdir", str(tmp / "w")], env=env)
            _, status, ru = os.wait4(p.pid, 0)
            p.returncode = os.waitstatus_to_exitcode(status)  # reaped here
            cpu = ru.ru_utime + ru.ru_stime
            self.assertNotEqual(os.waitstatus_to_exitcode(status), 0)  # killed by SIGXCPU, no answer
            self.assertGreaterEqual(cpu, 2.0 - 0.05)
            self.assertLess(cpu, 2.0 + 1.5)  # probe (0.5 s) + restart together, RLIMIT_CPU has 1 s granularity
            dec = json.loads((tmp / "w" / "decision.json").read_text())
            self.assertEqual(dec["path"], "fallback")

    def test_v9_historical_run_ids_unchanged(self):
        spec = importlib.util.spec_from_file_location("v9runner", ROOT / "scripts/online_selection_v9/runner.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.sha = lambda p: "x"
        job = {"instance": "a", "sha256": "s", "method": "D", "rep": 0}
        key, rid = mod.job_key(job, "st")
        self.assertNotIn("run_policy_id", key)
        new = dict(job, run_policy_id="p", cap_cpu=3600, cap_kind="policy_timeout", resource_policy_id="r")
        self.assertNotEqual(mod.job_key(new, "st")[1], rid)


if __name__ == "__main__":
    unittest.main()
