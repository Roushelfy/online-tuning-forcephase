#!/usr/bin/env python3
"""P1_M05_long: the frozen v6 selector (configs/stable_selection_v6/frozen/
P1_M05_final.json, unchanged) with the 300-second formal-solve stop removed
(docs/COMPLETION_RUN_PLAN_V7.md section 2).

  wrapper_long.py --strategy STRAT.json --cnf X.cnf --workdir DIR [--mem-mb 16000]

Observation exactly as the v6 wrapper (obsprofile6 S28 under the 3 s static
cap; incomplete -> D), decision by the frozen reader, then this process is
REPLACED (exec) by the formal solver with the action's flags -- the same
command as the fixed runs -- with no scoring cutoff. The caller times the
whole process (wait4: Python, the observation children it waited for, and
the solver). DIR/decision.json records the decision and cpu_at_exec, so the
formal solver CPU is total - cpu_at_exec. Standard library only.
"""

import argparse
import json
import os
import resource
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_timeout_policy  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "stable_selection_v6"))
import szlib  # noqa: E402
import v6lib  # noqa: E402

twlib, v5lib = v6lib.twlib, v6lib.v5lib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--cnf", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mem-mb", type=int, default=16000)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    strat = json.load(open(a.strategy))
    pkg = strat["package"]
    spec = v6lib.PACKAGES[pkg]
    out = {"strategy": strat["name"], "method": "P1_M05_long", "package": pkg, "cpu_at_start": twlib.self_cpu()}
    obs6 = v6lib.run_obs6(a.cnf, spec["sections"], v6lib.SCAP, os.path.join(a.workdir, "o6"), a.mem_mb)
    out["obs6"] = {"cpu": obs6["cpu"], "sections": obs6.get("sections")}
    sz = None
    if spec["sz"]:
        left = v6lib.SCAP - obs6["cpu"]
        sz = szlib.run_satzilla(a.cnf, v6lib.SZ_GROUPS, left, os.path.join(a.workdir, "sz"), a.mem_mb) if left > 0.05 \
            else {"status": "skipped", "cpu": 0.0}
        out["sz"] = {k: sz.get(k) for k in ("status", "cpu")}
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
    so, se = os.path.join(a.workdir, "final.out"), os.path.join(a.workdir, "final.err")
    tel, proof = os.path.join(a.workdir, "final.tel.jsonl"), os.path.join(a.workdir, "final.lrat")
    cmd = [v5lib.FORMAL] + v5lib.RUN_POLICY + v5lib.ACTIONS[action][1] + ["--fpc=1", a.cnf, proof]
    out.update(path=path, action=action, gains=gains, static_cpu=static, cmd=cmd, answer_stdout=so, answer_proof=proof,
               cpu_at_exec=twlib.self_cpu())
    json.dump(out, open(os.path.join(a.workdir, "decision.json"), "w"))
    # formal solve: replace this process; no scoring cutoff
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
    resource.setrlimit(resource.RLIMIT_AS, (a.mem_mb << 20, a.mem_mb << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if run_timeout_policy.wrapper_limit():  # per-run cap for the whole tree (probe/observation already waited for)
        run_timeout_policy.set_cpu_rlimit(run_timeout_policy.wrapper_limit())
    fo = os.open(so, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    fe = os.open(se, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(fo, 1)
    os.dup2(fe, 2)
    os.execve(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
