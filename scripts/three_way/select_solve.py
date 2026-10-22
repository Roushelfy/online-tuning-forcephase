#!/usr/bin/env python3
"""Deployable one-shot selector: observe cheaply, pick D / F+ / F- once, solve.

  select_solve.py --model configs/three_way/frozen/<name>.json --cnf X.cnf \
      --timeout 300 --workdir DIR [--mem-mb 16000]

1. static profile of the CNF (build/tools/cnfprofile);
2. probe models only: native D for the model's CPU budget (same command as
   the D baseline, LRAT proof); if the probe answers, that answer is final;
3. predict the action from features available before the decision;
4. start the chosen configuration from scratch with the remaining budget
   T - (all CPU used so far by this process and its children).
Writes DIR/result.json; the answering run's stdout/proof stay in DIR for
the caller to verify. The caller measures the total CPU of this process
tree (wait4) and charges all of it. Standard library only.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import twlib  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--cnf", required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mem-mb", type=int, default=16000)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    model = json.load(open(a.model))
    out = {"model": model["name"], "kind": model["kind"], "timeout": a.timeout,
           "cpu_at_start": twlib.self_cpu()}

    prof = twlib.run_profile(a.cnf)
    out["profile_cpu"] = prof.get("cpu")
    out["profile_error"] = prof.get("error")
    feats = twlib.static_features(prof)
    if model["kind"] == "probe":
        pr = twlib.run_probe(a.cnf, model["budget"], a.workdir, a.mem_mb)
        out["probe"] = {k: pr[k] for k in ("exit_code", "cpu", "wall", "terminated_by", "answered", "status_line")}
        if pr["answered"]:
            out.update(decision="probe", action="D", answer_exit=pr["exit_code"],
                       answer_stdout=pr["stdout"], answer_proof=pr["proof"],
                       overhead_cpu=twlib.self_cpu(), cpu_at_end=twlib.self_cpu())
            json.dump(out, open(os.path.join(a.workdir, "result.json"), "w"))
            return
        for p in (pr["proof"],):
            if os.path.exists(p):
                os.unlink(p)
        feats.update(twlib.probe_features(pr, prof))
    action = twlib.predict(model["model"], feats)
    out["features"] = feats
    out["action"] = action
    overhead = twlib.self_cpu()
    out["overhead_cpu"] = overhead
    remaining = a.timeout - overhead - twlib.RESERVE  # leave room for this process after the solve
    out["remaining"] = remaining
    if remaining <= 0:
        out.update(decision="no_budget", answer_exit=None)
        out["cpu_at_end"] = twlib.self_cpu()
        json.dump(out, open(os.path.join(a.workdir, "result.json"), "w"))
        return
    so, se = os.path.join(a.workdir, "final.out"), os.path.join(a.workdir, "final.err")
    tel, proof = os.path.join(a.workdir, "final.tel.jsonl"), os.path.join(a.workdir, "final.lrat")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
    cmd = [twlib.BINARY] + twlib.RUN_POLICY + twlib.ACTIONS[action][1] + ["--fpc=1", a.cnf, proof]
    r = twlib.run_budget(cmd, env, remaining, a.mem_mb, so, se, grace=10)
    out["formal"] = r
    out.update(decision="formal", answer_exit=r["exit_code"], answer_stdout=so, answer_proof=proof,
               cmd=[os.path.relpath(c, twlib.ROOT) if c.startswith(twlib.ROOT) else c for c in cmd])
    out["cpu_at_end"] = twlib.self_cpu()
    json.dump(out, open(os.path.join(a.workdir, "result.json"), "w"))


if __name__ == "__main__":
    main()
