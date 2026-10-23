#!/usr/bin/env python3
"""Deployable goal-v5 wrapper: bounded observation, one choice of D / F+ / F-,
formal solve from scratch (docs/OBSERVATION_PROTOCOL_V5.md sections 4-5).

  v5_wrapper.py --strategy configs/observations_v5/frozen/<name>.json --cnf X.cnf \
      --timeout 300 --workdir DIR [--mem-mb 16000] [--observe-only]

1. obsprofile with the package's sections (always s28) under the package's
   static cap; any required section not 'ok' -> D;
2. probe arms of the package in the fixed order D, F+, F- (build/obs, LRAT);
   an arm that answers ends the run with that answer (R11: arms only when
   the first stage is uncertain, see 'decide');
3. reader + default gate -> action;
4. formal solve (build/fpc) of that action with T - all CPU used so far - RESERVE.
Writes DIR/result.json; the answering run's stdout/proof stay in DIR for the
caller to verify. The caller charges the whole process tree (wait4).
--observe-only stops after step 3 (used to measure the wrapper overhead).
Standard library only.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import obsfeat  # noqa: E402
import v5lib  # noqa: E402

twlib = v5lib.twlib


def finish(out, workdir):
    out["cpu_at_end"] = twlib.self_cpu()
    json.dump(out, open(os.path.join(workdir, "result.json"), "w"))


def run_arms(spec_arms, cnf, workdir, mem_mb, out, tcap):
    """Run arms in order; returns (arms dict, answering arm or None, capped).
    An arm starts only if the CPU used so far plus its budget fits in tcap."""
    arms = {}
    for tag, acts in spec_arms:
        for act in acts:
            if twlib.self_cpu() + v5lib.ARMS[tag][0] > tcap:
                return arms, None, True
            r = v5lib.run_arm(cnf, act, tag, workdir, mem_mb)
            arms[(tag, act)] = r
            out.setdefault("arms", []).append({k: r[k] for k in ("tag", "action", "cpu", "exit_code", "terminated_by",
                                                                   "answered")})
            if r["answered"]:
                return arms, r, False
            if os.path.exists(r["proof"]):
                os.unlink(r["proof"])
    return arms, None, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--cnf", required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mem-mb", type=int, default=16000)
    ap.add_argument("--observe-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    strat = json.load(open(a.strategy))
    pkg = strat["package"]
    spec = v5lib.PACKAGES[pkg]
    out = {"strategy": strat["name"], "package": pkg, "timeout": a.timeout, "cpu_at_start": twlib.self_cpu()}

    # 1. static part
    obs = v5lib.run_obsprofile(a.cnf, spec["static"], spec["scap"], a.workdir, a.mem_mb)
    out["obsprofile"] = {"cpu": obs["cpu"], "sections": obs.get("sections")}
    action, path, gains = "D", None, None
    arms = {}
    if not v5lib.static_ok(obs, spec["static"]):
        path = "static_incomplete"
    else:
        # 2./3. arms and decision
        if spec.get("conditional"):
            f1 = obsfeat.package_features(pkg, obs, {}, stage=1)
            act1, g1 = v5lib.decide(strat["stage1"], f1)
            gains = {"stage1": g1}
            best1 = max(g1.values())
            if act1 != "D" and strat["theta1"] is not None and best1 > strat["theta1"]:
                action, path = act1, "stage1_direct"
            elif strat["theta_ask"] is not None and best1 > strat["theta_ask"]:
                arms, ans, cap = run_arms(spec["arms"], a.cnf, a.workdir, a.mem_mb, out, spec["tcap"])
                if ans is not None:
                    path = "probe_answer"
                elif cap:
                    path = "obs_cap"
                else:
                    f2 = obsfeat.package_features(pkg, obs, arms, stage=2)
                    action, g2 = v5lib.decide(strat["stage2"], f2)
                    gains["stage2"] = g2
                    path = "stage2"
            else:
                path = "stage1_keep_D"
        else:
            arms, ans, cap = run_arms(spec["arms"], a.cnf, a.workdir, a.mem_mb, out, spec["tcap"])
            if ans is not None:
                path = "probe_answer"
            elif cap:
                path = "obs_cap"
            else:
                feats = obsfeat.package_features(pkg, obs, arms)
                action, gains = v5lib.decide(strat["reader"], feats)
                path = "reader"
        if path == "probe_answer":
            out.update(decision="probe", path=path, action=ans["action"], answer_exit=ans["exit_code"],
                       answer_stdout=ans["stdout"], answer_proof=ans["proof"], overhead_cpu=twlib.self_cpu())
            finish(out, a.workdir)
            return
    out.update(path=path, action=action, gains=gains)
    overhead = twlib.self_cpu()
    out["overhead_cpu"] = overhead
    out["component_cpu"] = obs["cpu"] + sum(r["cpu"] for r in arms.values())
    if a.observe_only:
        out["decision"] = "observe_only"
        finish(out, a.workdir)
        return
    remaining = a.timeout - overhead - v5lib.RESERVE
    out["remaining"] = remaining
    if remaining <= 0:
        out.update(decision="no_budget", answer_exit=None)
        finish(out, a.workdir)
        return
    so, se = os.path.join(a.workdir, "final.out"), os.path.join(a.workdir, "final.err")
    tel, proof = os.path.join(a.workdir, "final.tel.jsonl"), os.path.join(a.workdir, "final.lrat")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
    cmd = [v5lib.FORMAL] + v5lib.RUN_POLICY + v5lib.ACTIONS[action][1] + ["--fpc=1", a.cnf, proof]
    r = twlib.run_budget(cmd, env, remaining, a.mem_mb, so, se, grace=10)
    out["formal"] = r
    out.update(decision="formal", answer_exit=r["exit_code"], answer_stdout=so, answer_proof=proof,
               cmd=[os.path.relpath(c, v5lib.ROOT) if c.startswith(v5lib.ROOT) else c for c in cmd])
    finish(out, a.workdir)


if __name__ == "__main__":
    main()
