#!/usr/bin/env python3
"""v9 deployment wrapper: default pre-solve, then one configuration choice
(docs/ONLINE_SELECTION_PROTOCOL_V9.md section 4). Standard library only.

  presolve.py --strategy S.json --cnf X.cnf --workdir DIR [--mem-mb 16000] [--probe-only --tau T]

Strategy kinds:
  {"kind": "presolve", "tau": T, "fallback": "Fp"|"Fm"|"D"}
  {"kind": "gate", "tau": T, "reader": {...}, "missing_action": a}   (content gate after the probe)
  {"kind": "fixed", "action": a}                                      (no probe)
Semantics (fixed in advance):
  1. Probe = the formal D command (build/fpc, --lrat=1 --phase=1 --forcephase=0 --fpc=1, seed 0) on the
     original input. Its window tau is the probe process's own CPU from its start (parsing and
     preprocessing included); at tau it gets SIGTERM (SIGKILL after 1 s more).
  2. If the probe answered (exit 10/20), its stdout / proof / telemetry become the answer files and the
     wrapper exits with the same code -- the answer is verified by the caller and never re-solved.
  3. Otherwise the probe's proof is deleted, the action is chosen (fallback, or the gate on the last
     telemetry checkpoint written before the stop; no checkpoint -> missing_action), and this process
     is REPLACED (exec) by the formal command of that action from scratch (D too: repeated work is
     charged). The caller times the whole process tree (wait4): Python, probe, and final solver.
DIR/decision.json records probe CPU, exit, stop overshoot, features, path and action.
--probe-only (development measurements): run the probe with --tau, record everything and exit 0 if the
probe did not answer (no final solve); a probe answer is handled as in 2.
"""

import argparse
import json
import math
import os
import resource
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
import twlib  # noqa: E402

FORMAL = os.path.join(ROOT, "build", "fpc", "cadical")
ARGS = {"D": ["--phase=1", "--forcephase=0"], "Fp": ["--phase=1", "--forcephase=1"], "Fm": ["--phase=0", "--forcephase=1"]}


def self_cpu():
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def last_checkpoint(tel_path):
    """Feature dict of the last 'checkpoint' record (names from the header); None if there is none."""
    names, last = None, None
    try:
        with open(tel_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue  # a line cut by the stop
                if d.get("type") == "header":
                    names = d.get("features")
                elif d.get("type") == "checkpoint" and isinstance(d.get("f"), (dict, list)):
                    last = d
    except OSError:
        return None
    if last is None:
        return None
    f = last["f"]
    feats = dict(f) if isinstance(f, dict) else dict(zip(names or [], f))
    feats["_conflicts"] = last.get("conflicts")
    feats["_time"] = last.get("time")
    return feats


def decide_gate(reader, x):
    """reader: tree {"tree": node} or ridge {"mean","std","models","margin"}; x: feature dict."""
    if reader["method"] == "tree":
        node = reader["tree"]
        while "leaf" not in node:
            node = node["left"] if x[node["feature"]] <= node["threshold"] else node["right"]
        return node["leaf"]
    pred = {a: m["intercept"] + sum(w * (x[f] - reader["mean"][f]) / reader["std"][f] for f, w in m["coef"].items())
            for a, m in reader["models"].items()}
    best = min(sorted(pred), key=lambda a: pred[a])
    return best if pred[best] < -reader["margin"] else "D"


def usable(x, names):
    return x is not None and all(isinstance(x.get(f), (int, float)) and math.isfinite(x[f]) for f in names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy")
    ap.add_argument("--cnf", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mem-mb", type=int, default=16000)
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--tau", type=float)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    strat = json.load(open(a.strategy)) if a.strategy else {"kind": "presolve", "tau": a.tau, "fallback": None}
    tau = a.tau if a.probe_only else strat.get("tau")
    out = {"strategy": strat.get("name"), "kind": strat["kind"], "tau": tau, "probe_only": a.probe_only,
           "cpu_at_start": self_cpu()}
    final = {k: os.path.join(a.workdir, "final" + e) for k, e in (("out", ".out"), ("err", ".err"), ("tel", ".tel.jsonl"),
                                                                  ("proof", ".lrat"))}
    env_base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    action, path = None, None
    if strat["kind"] == "fixed":
        action, path = strat["action"], "fixed"
    else:
        pr = {k: os.path.join(a.workdir, "probe" + e) for k, e in (("out", ".out"), ("err", ".err"),
                                                                   ("tel", ".tel.jsonl"), ("proof", ".lrat"))}
        cmd = [FORMAL, "--lrat=1"] + ARGS["D"] + ["--fpc=1", a.cnf, pr["proof"]]
        r = twlib.run_budget(cmd, dict(env_base, FPC_LOG=pr["tel"]), tau, a.mem_mb, pr["out"], pr["err"], grace=1.0)
        out["probe"] = {"cmd": cmd, "exit_code": r["exit_code"], "cpu": r["cpu"], "wall": r["wall"],
                        "terminated_by": r.get("terminated_by"), "overshoot": r["cpu"] - tau}
        if r["exit_code"] in (10, 20):
            for k in ("out", "err", "tel", "proof"):
                if os.path.exists(pr[k]):
                    os.replace(pr[k], final[k])
            out.update(path="probe_solved", action="D_probe", cpu_at_end=self_cpu())
            json.dump(out, open(os.path.join(a.workdir, "decision.json"), "w"))
            sys.exit(r["exit_code"])
        try:
            os.unlink(pr["proof"])
        except OSError:
            pass
        x = last_checkpoint(pr["tel"])
        out["features"] = x
        if strat["kind"] == "presolve":
            action, path = strat.get("fallback"), "fallback"
        else:
            names = strat["features"]
            if usable(x, names):
                action, path = decide_gate(strat["reader"], x), "gate"
            else:
                action, path = strat["missing_action"], "gate_missing_features"
        if a.probe_only:
            out.update(path="probe_unsolved", action=action, cpu_at_end=self_cpu())
            json.dump(out, open(os.path.join(a.workdir, "decision.json"), "w"))
            sys.exit(0)
    cmd = [FORMAL, "--lrat=1"] + ARGS[action] + ["--fpc=1", a.cnf, final["proof"]]
    out.update(path=path, action=action, cmd=cmd, cpu_at_exec=self_cpu())
    json.dump(out, open(os.path.join(a.workdir, "decision.json"), "w"))
    resource.setrlimit(resource.RLIMIT_AS, (a.mem_mb << 20, a.mem_mb << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    fo = os.open(final["out"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    fe = os.open(final["err"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(fo, 1)
    os.dup2(fe, 2)
    os.execve(cmd[0], cmd, dict(env_base, FPC_LOG=final["tel"]))


if __name__ == "__main__":
    main()
