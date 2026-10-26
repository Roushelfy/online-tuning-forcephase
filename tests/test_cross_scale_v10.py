"""Goal v10 wrapper and runner with controlled subprocesses (no SAT solver): a fake 'cadical' burns CPU or prints
a model; the real build/tools/static10 and checkmodel are used. The v10 runner runs as a subprocess with a 1.5 s
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
sys.path.insert(0, str(ROOT / "scripts" / "cross_scale_v10"))
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


class V10Tests(unittest.TestCase):
    def test_arm_features_from_a_stopped_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "p.out"
            out.write_text(STOPPED_OUT)
            tel = pathlib.Path(tmp) / "p.tel.jsonl"
            tel.write_text(json.dumps({"type": "final", "conflicts": 4406, "decisions": 5363, "dec_neg": 2818,
                                       "dec_free": 5363}) + "\n")
            f, info = common.arm_features("D", str(out), str(tel), 0.11)
        self.assertEqual(info["conflicts"], 4406)
        self.assertAlmostEqual(f["dec_per_conf"], 5363 / 4406)
        self.assertAlmostEqual(f["learned_len"], 112198 / 4320)
        self.assertEqual((f["glue"], f["trail"], f["remaining"]), (9.0, 0.48, 0.46))
        # growth: conflicts at the stop vs the last progress line at or before half the last progress time (0.04)
        self.assertAlmostEqual(f["growth"], __import__("math").log10(4407 / 1412))
        self.assertAlmostEqual(f["restart_rate"], 1000 * 40 / 4406)
        self.assertAlmostEqual(f["neg_dec"], 2818 / 5363)
        none, _ = common.arm_features("Fp", str(out) + ".missing", str(tel) + ".missing", 0.1)
        self.assertTrue(all(v is None for v in none.values()))

    def test_decide_ridge_margin_missing_and_impute(self):
        feats = ["st_log_vars", "pD_conf_rate"]
        strat = {"base": "Fp", "missing_action": "Fp", "needs_arms": ["D"], "features": feats,
                 "impute": {"st_log_vars": 3.0, "pD_conf_rate": 4.0},
                 "reader": {"method": "ridge", "margin": 1.0, "mean": {f: 0.0 for f in feats},
                            "std": {f: 1.0 for f in feats},
                            "models": {"D": {"intercept": -0.5, "coef": {"st_log_vars": 0.0}},
                                       "Fm": {"intercept": 0.0, "coef": {"pD_conf_rate": -1.0}}}}}
        self.assertEqual(common.decide(strat, {"st_log_vars": 1, "pD_conf_rate": 0.5}, {"D": True}), ("Fp", "reader"))
        self.assertEqual(common.decide(strat, {"st_log_vars": 1, "pD_conf_rate": 2.0}, {"D": True}), ("Fm", "reader"))
        self.assertEqual(common.decide(strat, {"st_log_vars": 1, "pD_conf_rate": None}, {"D": True}), ("Fm", "reader"))
        self.assertEqual(common.decide(strat, {"st_log_vars": 1, "pD_conf_rate": 9.0}, {"D": False}), ("Fp", "missing"))
        self.assertEqual(common.decide(dict(strat, reader=None), {}, {}), ("Fp", "fallback"))

    def test_runner_wrapper_share_one_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            fake = tmp / "cadical"
            fake.write_text(FAKE)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            pol = tmp / "policy.json"
            pol.write_text(json.dumps({"policy_id": "test-1.5s", "per_instance_method_cpu_seconds": LIMIT,
                                       "project_cpu_hours_cap": None, "stage_cpu_hours_cap": None}))
            cnfdir = tmp / "data" / "cross_scale_v10" / "cnf"
            cnfdir.mkdir(parents=True)
            cnfs = {"burn": "c FAKE burn\np cnf 2 2\n1 2 0\n-1 2 0\n", "quick": "c FAKE answer 0.1\np cnf 1 1\n1 0\n"}
            sha = {}
            for name, text in cnfs.items():
                (cnfdir / f"t-{name}.cnf").write_text(text)
                sha[name] = hashlib.sha256(text.encode()).hexdigest()
            feats = common.feature_set("C")
            strat = tmp / "c.json"
            strat.write_text(json.dumps({
                "name": "t", "kind": "observe", "static": True,
                "probes": [{"arm": "D", "tau": 0.3}, {"arm": "Fp", "tau": 0.3}, {"arm": "Fm", "tau": 0.3}],
                "reader": {"method": "tree", "tree": {"leaf": "Fm"}}, "features": feats,
                "impute": {f: 0.0 for f in feats}, "base": "Fp", "missing_action": "Fp", "needs_arms": []}))
            measure = {"static": True, "probes": [{"arm": "D", "tau": 0.2}, {"arm": "Fp", "tau": 0.2}]}
            jobs = []
            for name in cnfs:
                b = {"instance": f"t-{name}", "sha256": sha[name], "rep": 0}
                jobs += [dict(b, method="D"), dict(b, method="W", strategy=str(strat)),
                         dict(b, method="MEASURE", measure=measure)]
            plan = tmp / "plan.json"
            plan.write_text(json.dumps({"stage": "t", "jobs": jobs}))
            env = dict(os.environ, FP_DATA=str(tmp / "data"), V10_WORK=str(tmp / "work"),
                       FP_RUN_TIMEOUT_POLICY=str(pol), FP_FORMAL_OVERRIDE=str(fake))
            r = subprocess.run([sys.executable, str(ROOT / "scripts/cross_scale_v10/runner.py"), "--plan", str(plan),
                                "--stage", "t"], env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            recs = {}
            for p in (tmp / "data/runs/cross_scale_v10/t").glob("*.json"):
                if p.name not in ("progress.json", "effective_plan.json"):
                    x = json.loads(p.read_text())
                    recs[(x["instance"], x["method"])] = x
            self.assertEqual(recs[("t-burn", "D")]["status"], "policy_timeout")
            # static analysis + three 0.3 s probes + restart of the chosen action: one 1.5 s limit for the tree
            w = recs[("t-burn", "W")]
            self.assertEqual(w["status"], "policy_timeout")
            self.assertEqual((w["decision"]["path"], w["decision"]["action"]), ("reader", "Fm"))
            self.assertEqual([p["arm"] for p in w["decision"]["probes"]], ["D", "Fp", "Fm"])
            self.assertTrue(all(p["cpu"] >= 0.3 for p in w["decision"]["probes"]))
            self.assertEqual(w["decision"]["static"]["status"], "ok")
            self.assertGreaterEqual(w["cpu"], LIMIT)
            self.assertLess(w["cpu"], LIMIT + 1.5)
            self.assertGreaterEqual(w["pre_exec_cpu"], 0.9)
            # the first probe's answer is the run's answer (verified), later probes are not run
            q = recs[("t-quick", "W")]
            self.assertEqual(q["status"], "solved", q.get("verification"))
            self.assertEqual(q["decision"]["path"], "probe_solved")
            self.assertEqual(len(q["decision"]["probes"]), 1)
            self.assertEqual(recs[("t-quick", "D")]["status"], "solved")
            # measurement: every probe runs independently, no final solve
            m = recs[("t-burn", "MEASURE")]
            self.assertEqual(m["status"], "measured")
            self.assertEqual([p["exit_code"] for p in m["decision"]["probes"]], [-15, -15])
            self.assertEqual([p["exit_code"] for p in recs[("t-quick", "MEASURE")]["decision"]["probes"]], [10, 10])
            eff = json.loads((tmp / "data/runs/cross_scale_v10/t/effective_plan.json").read_text())
            self.assertTrue(all(j["cap_cpu"] == LIMIT and j["cap_kind"] == "policy_timeout" for j in eff["jobs"]))
            ids = {x["id"] for x in recs.values()}
            self.assertEqual(len(ids), len(recs))
            self.assertTrue(all(x["key"]["phase"] == "cross_scale_v10" and x["key"]["run_policy_id"] == "test-1.5s"
                                for x in recs.values()))


if __name__ == "__main__":
    unittest.main()
