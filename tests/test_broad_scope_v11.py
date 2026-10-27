"""Goal v11 wrapper and runner (v10 semantics + out-of-range rule, per-job wrapper, kept models) with controlled subprocesses (no SAT solver): a fake 'cadical' burns CPU or prints
a model; the real build/tools/static10 and checkmodel are used. The v11 runner runs as a subprocess with a 1.5 s
test policy (FP_RUN_TIMEOUT_POLICY), so the static analysis, three probes and the restart must share ONE limit.
Also unit tests of the shared decision rule and of the stop-time feature parser.
"""
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "broad_scope_v11"))
import common  # noqa: E402

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
STOPPED_OUT = """c --- [ solving ] ---
c  0.00  3  0 0   0  0    0    0 0.0 0 0 2 6  0% 4360 1200 100%
c -  0.04  4 17 3   0  1 1411  509 1.9 19 10 2 6 36% 4360 1200 100%
c -  0.09  4 12 5  20  1 3564 1119 2.3 19 8 2 6 38% 4360 1200 100%
c }  0.11  4 12 5  40  1 4406  670 2.4 19 9 2 6 48% 2566 549 46%
c --- [ statistics ] ---
c chronological:               662        15.02 %  of conflicts
c conflicts:                  4406     40393.85    per second
c decisions:                  5363     49167.55    per second
c learned:                    4320        98.05 %  per conflict
c learned_lits:             112198       100.00 %  learned literals
c propagations:             854553         7.83 M  per second
c restarts:                     40       110.15    interval
c raising signal 15 (SIGTERM)
"""


class V11Tests(unittest.TestCase):
    def test_decide_out_of_range(self):
        feats = list(common.STATIC)
        strat = {"base": "Fm", "missing_action": "Fm", "needs_arms": [], "features": feats,
                 "impute": {f: 0.0 for f in feats},
                 "ood": {"lo": {"st_log_vars": 1.0}, "hi": {"st_log_vars": 3.0}, "action": "D"},
                 "reader": {"method": "tree", "tree": {"feature": "st_log_vars", "threshold": 2.0,
                                                       "left": {"leaf": "Fp"}, "right": {"leaf": "Fm"}}}}
        self.assertEqual(common.decide(strat, {"st_log_vars": 1.5}, {}), ("Fp", "reader"))
        self.assertEqual(common.decide(strat, {"st_log_vars": 2.5}, {}), ("Fm", "reader"))
        self.assertEqual(common.decide(strat, {"st_log_vars": 3.5}, {}), ("D", "ood"))
        self.assertEqual(common.decide(strat, {"st_log_vars": None}, {}), ("D", "ood"))
        no = dict(strat)
        del no["ood"]
        self.assertEqual(common.decide(no, {"st_log_vars": 3.5}, {}), common.v10.decide(no, {"st_log_vars": 3.5}, {}))

    def test_runner_wrappers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            fake = tmp / "cadical"
            fake.write_text(FAKE)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            pol = tmp / "policy.json"
            pol.write_text(json.dumps({"policy_id": "test-1.5s", "per_instance_method_cpu_seconds": LIMIT,
                                       "project_cpu_hours_cap": None, "stage_cpu_hours_cap": None}))
            cnfdir = tmp / "data" / "broad_scope_v11" / "cnf"
            cnfdir.mkdir(parents=True)
            cnfs = {"burn": "c FAKE burn\np cnf 2 2\n1 2 0\n-1 2 0\n", "quick": "c FAKE answer 0.1\np cnf 1 1\n1 0\n"}
            sha = {}
            for name, text in cnfs.items():
                (cnfdir / f"t-{name}.cnf").write_text(text)
                sha[name] = hashlib.sha256(text.encode()).hexdigest()
            feats = list(common.STATIC)
            st = tmp / "st.json"  # static tree with an out-of-range check that every input fails
            st.write_text(json.dumps({"name": "st", "kind": "observe", "static": True, "probes": [],
                                      "reader": {"method": "tree", "tree": {"leaf": "Fp"}}, "features": feats,
                                      "impute": {f: 0.0 for f in feats}, "base": "Fm", "missing_action": "Fm",
                                      "needs_arms": [], "ood": {"lo": {"st_log_vars": 1e9}, "hi": {"st_log_vars": 2e9},
                                                                "action": "D"}}))
            pr = tmp / "pr.json"  # v10-format prefix reader run by the original v10 wrapper
            pr.write_text(json.dumps({"name": "pr", "kind": "observe", "static": True, "probes": [{"arm": "D", "tau": 0.3}],
                                      "reader": {"method": "tree", "tree": {"leaf": "Fm"}}, "features": feats,
                                      "impute": {f: 0.0 for f in feats}, "base": "Fp", "missing_action": "Fp",
                                      "needs_arms": []}))
            jobs = []
            for name in cnfs:
                b = {"instance": f"t-{name}", "sha256": sha[name], "rep": 0, "keep_model": name == "quick"}
                jobs += [dict(b, method="D"), dict(b, method="W", strategy=str(st)),
                         dict(b, method="W", strategy=str(pr), wrapper="scripts/cross_scale_v10/wrapper.py"),
                         dict(b, method="MEASURE", measure={"static": True, "probes": [{"arm": "D", "tau": 0.2}]})]
            plan = tmp / "plan.json"
            plan.write_text(json.dumps({"stage": "t", "jobs": jobs}))
            env = dict(os.environ, FP_DATA=str(tmp / "data"), V11_WORK=str(tmp / "work"),
                       FP_RUN_TIMEOUT_POLICY=str(pol), FP_FORMAL_OVERRIDE=str(fake))
            r = subprocess.run([sys.executable, str(ROOT / "scripts/broad_scope_v11/runner.py"), "--plan", str(plan),
                                "--stage", "t"], env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            recs = {}
            stage = tmp / "data/runs/broad_scope_v11/t"
            for p in stage.glob("*.json"):
                if p.name not in ("progress.json", "effective_plan.json"):
                    x = json.loads(p.read_text())
                    recs[(x["instance"], x["method"], x.get("strategy"))] = x
            self.assertEqual(recs[("t-burn", "D", None)]["status"], "policy_timeout")
            w = recs[("t-burn", "W", str(st))]
            self.assertEqual((w["decision"]["path"], w["decision"]["action"]), ("ood", "D"))
            self.assertEqual(w["status"], "policy_timeout")
            self.assertLess(w["cpu"], LIMIT + 1.5)
            v = recs[("t-burn", "W", str(pr))]
            self.assertEqual((v["decision"]["path"], v["decision"]["action"]), ("reader", "Fm"))
            self.assertTrue(v["key"]["wrapper_sha256"] != w["key"]["wrapper_sha256"])
            q = recs[("t-quick", "D", None)]
            self.assertEqual(q["status"], "solved")
            import gzip
            raw = gzip.open(stage / "raw" / q["id"] / "final.out.gz", "rt").read()
            self.assertIn("v 1 0", raw)  # kept model (keep_model)
            self.assertEqual(recs[("t-burn", "MEASURE", None)]["status"], "measured")
            self.assertTrue(all(x["key"]["phase"] == "broad_scope_v11" for x in recs.values()))


if __name__ == "__main__":
    unittest.main()
