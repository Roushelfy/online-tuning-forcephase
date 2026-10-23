#!/usr/bin/env python3
"""Deployable goal-v6 wrapper: observation (obsprofile6, optionally SATzilla),
one choice of D / F+ / F- by a frozen reader, formal solve from scratch.

  v6_wrapper.py --strategy configs/stable_selection_v6/frozen/<name>.json --cnf X.cnf \
      --timeout 300 --workdir DIR [--mem-mb 16000]

Any tool part not completed, or the static cap exceeded -> D. The reader sees
h = all CPU used so far by this process tree (charged by the caller via wait4).
Writes DIR/result.json; the answering run's stdout/proof stay in DIR.
Standard library only.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import szlib  # noqa: E402
import v6lib  # noqa: E402

twlib = v6lib.twlib
v5lib = v6lib.v5lib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--cnf", required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mem-mb", type=int, default=16000)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    strat = json.load(open(a.strategy))
    pkg = strat["package"]
    spec = v6lib.PACKAGES[pkg]
    out = {"strategy": strat["name"], "package": pkg, "timeout": a.timeout, "cpu_at_start": twlib.self_cpu()}
    obs6 = v6lib.run_obs6(a.cnf, spec["sections"], v6lib.SCAP, os.path.join(a.workdir, "o6"), a.mem_mb)
    out["obs6"] = {"cpu": obs6["cpu"], "sections": obs6.get("sections")}
    sz = None
    if spec["sz"]:
        left = v6lib.SCAP - obs6["cpu"]
        if left > 0.05:
            sz = szlib.run_satzilla(a.cnf, v6lib.SZ_GROUPS, left, os.path.join(a.workdir, "sz"), a.mem_mb)
            out["sz"] = {k: sz[k] for k in ("status", "cpu", "exit_code", "terminated_by")}
        else:
            sz = {"status": "skipped", "cpu": 0.0}
            out["sz"] = sz
    static = obs6["cpu"] + ((sz or {}).get("cpu") or 0.0)
    action, gains = "D", None
    if not v6lib.observation_ok(pkg, obs6, sz) or static > v6lib.SCAP:
        path = "observation_incomplete"
    else:
        feats = v6lib.features(pkg, obs6, sz)
        h = twlib.self_cpu()
        action, gains = v6lib.decide(strat["reader"], feats, h)
        path = "reader"
        out["h_at_decision"] = h
    overhead = twlib.self_cpu()
    out.update(path=path, action=action, gains=gains, overhead_cpu=overhead, static_cpu=static)
    remaining = a.timeout - overhead - v6lib.RESERVE
    out["remaining"] = remaining
    if remaining <= 0:
        out.update(decision="no_budget", answer_exit=None, cpu_at_end=twlib.self_cpu())
        json.dump(out, open(os.path.join(a.workdir, "result.json"), "w"))
        return
    so, se = os.path.join(a.workdir, "final.out"), os.path.join(a.workdir, "final.err")
    tel, proof = os.path.join(a.workdir, "final.tel.jsonl"), os.path.join(a.workdir, "final.lrat")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
    cmd = [v5lib.FORMAL] + v5lib.RUN_POLICY + v5lib.ACTIONS[action][1] + ["--fpc=1", a.cnf, proof]
    r = twlib.run_budget(cmd, env, remaining, a.mem_mb, so, se, grace=10)
    out["formal"] = r
    out.update(decision="formal", answer_exit=r["exit_code"], answer_stdout=so, answer_proof=proof,
               cpu_at_end=twlib.self_cpu())
    json.dump(out, open(os.path.join(a.workdir, "result.json"), "w"))


if __name__ == "__main__":
    main()
