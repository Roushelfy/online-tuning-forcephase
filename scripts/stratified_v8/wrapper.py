#!/usr/bin/env python3
"""v8 deployment wrapper W (docs/STRATIFIED_PROTOCOL_V8.md section 8).

  wrapper.py --strategy configs/stratified_v8/frozen/strategy.json --cnf X.cnf --workdir DIR [--mem-mb 16000]

Observe (features.extract: obsprofile6, 2 s cap) -> the frozen strategy picks
one action (missing / incomplete observation -> D) -> this process is
REPLACED (exec) by the formal solver with that action's flags, the same
command as the fixed runs, no scoring cutoff. The caller times the whole
process tree (wait4). DIR/decision.json records the decision and
cpu_at_exec. Standard library only (no numpy import cost).
"""

import argparse
import json
import os
import resource
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import features  # noqa: E402

FORMAL = os.path.join(ROOT, "build", "fpc", "cadical")
ARGS = {"D": ["--phase=1", "--forcephase=0"], "Fp": ["--phase=1", "--forcephase=1"], "Fm": ["--phase=0", "--forcephase=1"]}


def self_cpu():
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def decide(strategy, x):
    """Frozen decision; x: feature dict (all present). Returns (action, detail)."""
    if strategy["method"] == "tree":
        node = strategy["tree"]
        path = []
        while "leaf" not in node:
            go = "left" if x[node["feature"]] <= node["threshold"] else "right"
            path.append([node["feature"], node["threshold"], go])
            node = node[go]
        return node["leaf"], {"path": path}
    if strategy["method"] == "ridge":
        pred = {}
        for a, m in strategy["models"].items():
            pred[a] = m["intercept"] + sum(w * (x[f] - strategy["mean"][f]) / strategy["std"][f]
                                           for f, w in m["coef"].items())
        best = min(sorted(pred), key=lambda a: pred[a])
        return (best if pred[best] < -strategy["margin"] else "D"), {"pred_delta": pred}
    if strategy["method"] == "fixed":
        return strategy["action"], {}
    raise ValueError(strategy["method"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--cnf", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mem-mb", type=int, default=16000)
    ap.add_argument("--decide-only", action="store_true", help="consistency check: write decision.json, no solve")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    strat = json.load(open(a.strategy))
    out = {"strategy": strat.get("name"), "cpu_at_start": self_cpu()}
    obs = features.extract(a.cnf, os.path.join(a.workdir, "o6"), a.mem_mb)
    out["observation"] = {k: obs[k] for k in ("ok", "cpu", "exit_code", "terminated_by", "sections")}
    if obs["ok"]:
        action, detail = decide(strat, obs["features"])
        path = "strategy"
    else:
        action, detail, path = "D", {}, "observation_incomplete"
    so, se = os.path.join(a.workdir, "final.out"), os.path.join(a.workdir, "final.err")
    tel, proof = os.path.join(a.workdir, "final.tel.jsonl"), os.path.join(a.workdir, "final.lrat")
    cmd = [FORMAL, "--lrat=1"] + ARGS[action] + ["--fpc=1", a.cnf, proof]
    out.update(path=path, action=action, detail=detail, features=obs["features"], cmd=cmd, cpu_at_exec=self_cpu())
    json.dump(out, open(os.path.join(a.workdir, "decision.json"), "w"))
    if a.decide_only:
        print(json.dumps({"action": action, "path": path, "cpu_at_exec": out["cpu_at_exec"]}))
        return
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
    resource.setrlimit(resource.RLIMIT_AS, (a.mem_mb << 20, a.mem_mb << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    fo = os.open(so, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    fe = os.open(se, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(fo, 1)
    os.dup2(fe, 2)
    os.execve(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
