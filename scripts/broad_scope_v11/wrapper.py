#!/usr/bin/env python3
"""Goal v11 wrapper: the v10 wrapper (scripts/cross_scale_v10/wrapper.py) with the v11 decision
(scripts/broad_scope_v11/common.py: out-of-range check before the v10 readers; docs/BROAD_SCOPE_PROTOCOL_V11.md
section 7). Standard library only.

  wrapper.py --strategy S.json --cnf X.cnf --workdir DIR [--mem-mb 16000]      deployment
  wrapper.py --measure M.json  --cnf X.cnf --workdir DIR [--mem-mb 16000]      development measurement

Strategy kinds:
  {"kind": "fixed", "action": a}
  {"kind": "observe", "static": bool, "probes": [{"arm": a, "tau": t}, ...], "reader": {...}|null,
   "features": [...], "impute": {...}, "base": a, "missing_action": a, "needs_arms": [...]}
Semantics (fixed in advance):
  1. Static analysis (if used): build/tools/static10 under a CPU cap of 2 s (and its own work cap); over the cap
     or failed -> static features missing (imputed by the strategy's training medians).
  2. Probes in the listed order, each the formal command of its arm (build/fpc, --lrat=1 <arm> --fpc=1, seed 0)
     on the original input; window tau = the probe process's own CPU from its start (parsing and preprocessing
     included); SIGTERM at tau, SIGKILL 1 s later. A probe that answers (exit 10/20) ends the run: its stdout,
     proof and telemetry become the answer files and the wrapper exits with that code (verified by the caller,
     never re-solved, later probes not run).
  3. Otherwise each probe's proof is deleted and its features are read from what it wrote up to its stop
     (statistics block, telemetry 'final' record, progress lines); the action is decided (common.decide) and
     this process is REPLACED (exec) by the formal command of that action from scratch -- D too, all repeated
     work charged. Before exec the kernel CPU limit is set to the per-run cap minus everything already used
     (FP_RUN_CPU_LIMIT from the controller), so the whole tree stops at the cap.
--measure M.json ({"static": bool, "probes": [...]}): runs the static analysis and EVERY listed probe
independently (no early stop; answers recorded, proofs deleted, not verified here), records CPU, the wrapper's
own CPU per step, features and exit codes in DIR/decision.json, and exits 0. Used to simulate any registered
schedule offline.
"""

import argparse
import json
import os
import resource
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import common  # noqa: E402
import run_timeout_policy  # noqa: E402

twlib = common.twlib


def own_cpu():
    s = resource.getrusage(resource.RUSAGE_SELF)
    return s.ru_utime + s.ru_stime


def tree_cpu():
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def run_static(cnf, workdir):
    so, se = os.path.join(workdir, "static.out"), os.path.join(workdir, "static.err")
    cmd = [common.STATIC_TOOL, "--work-cap", repr(common.STATIC_WORK_CAP), cnf]
    r = twlib.run_budget(cmd, {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}, common.STATIC_CPU_CAP,
                         4000, so, se, grace=1.0)
    out = {"cpu": r["cpu"], "exit_code": r["exit_code"], "terminated_by": r.get("terminated_by"), "status": None,
           "features": {k: None for k in common.STATIC}}
    if r["exit_code"] == 0:
        try:
            d = json.load(open(so))
            out["status"] = d.get("status")
            out["features"] = {k: d["features"].get(k) for k in common.STATIC}
            out["work"] = d.get("work")
        except (OSError, ValueError, KeyError):
            out["status"] = "unreadable"
    else:
        out["status"] = "cap" if r.get("terminated_by") else "error"
    return out


def run_probe(arm, tau, cnf, workdir, tag, mem_mb, env_base):
    pr = {k: os.path.join(workdir, f"{tag}{e}") for k, e in (("out", ".out"), ("err", ".err"), ("tel", ".tel.jsonl"),
                                                               ("proof", ".lrat"))}
    cmd = [common.FORMAL, "--lrat=1"] + common.ARGS[arm] + ["--fpc=1", cnf, pr["proof"]]
    o0 = own_cpu()
    r = twlib.run_budget(cmd, dict(env_base, FPC_LOG=pr["tel"]), tau, mem_mb, pr["out"], pr["err"], grace=1.0)
    rec = {"arm": arm, "tau": tau, "cmd": cmd, "exit_code": r["exit_code"], "cpu": r["cpu"], "wall": r["wall"],
           "terminated_by": r.get("terminated_by"), "overshoot": r["cpu"] - tau, "files": pr}
    if r["exit_code"] not in (10, 20):
        feats, info = common.arm_features(arm, pr["out"], pr["tel"], r["cpu"])
        rec.update(features=feats, info=info, started=bool(info.get("conflicts")))
        if arm == "D":
            rec["v9_features"] = common.v9_checkpoint_features(pr["tel"])
    rec["wrapper_cpu"] = own_cpu() - o0
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy")
    ap.add_argument("--measure")
    ap.add_argument("--cnf", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mem-mb", type=int, default=16000)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    env_base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    dec_path = os.path.join(a.workdir, "decision.json")
    final = {k: os.path.join(a.workdir, "final" + e) for k, e in (("out", ".out"), ("err", ".err"),
                                                                  ("tel", ".tel.jsonl"), ("proof", ".lrat"))}
    if a.measure:
        spec = json.load(open(a.measure))
        out = {"mode": "measure", "spec": spec, "own_cpu_at_start": own_cpu(), "tree_cpu_at_start": tree_cpu()}
        if spec.get("static"):
            o0 = own_cpu()
            out["static"] = run_static(a.cnf, a.workdir)
            out["static"]["wrapper_cpu"] = own_cpu() - o0
        out["probes"] = []
        for k, p in enumerate(spec["probes"]):
            rec = run_probe(p["arm"], float(p["tau"]), a.cnf, a.workdir, f"m{k}", a.mem_mb, env_base)
            for f in rec.pop("files").values():
                if f.endswith((".lrat",)) and os.path.exists(f):
                    os.unlink(f)
            out["probes"].append(rec)
        out.update(own_cpu_at_end=own_cpu(), tree_cpu_at_end=tree_cpu())
        json.dump(out, open(dec_path, "w"))
        sys.exit(0)

    strat = json.load(open(a.strategy))
    out = {"mode": "deploy", "strategy": strat.get("name"), "kind": strat["kind"], "own_cpu_at_start": own_cpu(),
           "tree_cpu_at_start": tree_cpu()}
    if strat["kind"] == "fixed":
        action, path = strat["action"], "fixed"
    else:
        static = {}
        if strat.get("static"):
            st = run_static(a.cnf, a.workdir)
            out["static"] = st
            static = st["features"]
        arms, started, probes = {}, {}, []
        for k, p in enumerate(strat.get("probes", [])):
            rec = run_probe(p["arm"], float(p["tau"]), a.cnf, a.workdir, f"probe{k}", a.mem_mb, env_base)
            files = rec.pop("files")
            probes.append(rec)
            if rec["exit_code"] in (10, 20):
                for key in ("out", "err", "tel", "proof"):
                    if os.path.exists(files[key]):
                        os.replace(files[key], final[key])
                out.update(probes=probes, path="probe_solved", action=p["arm"] + "_probe", answered_by=k,
                           tree_cpu_at_end=tree_cpu())
                json.dump(out, open(dec_path, "w"))
                sys.exit(rec["exit_code"])
            if os.path.exists(files["proof"]):
                os.unlink(files["proof"])
            arms[p["arm"]] = rec["features"]
            started[p["arm"]] = rec["started"]
        x = common.combine(static, arms)
        out.update(probes=probes, features={f: x.get(f) for f in strat.get("features", [])})
        action, path = common.decide(strat, x, started)
    cmd = [common.FORMAL, "--lrat=1"] + common.ARGS[action] + ["--fpc=1", a.cnf, final["proof"]]
    out.update(path=path, action=action, cmd=cmd, cpu_at_exec=tree_cpu())
    json.dump(out, open(dec_path, "w"))
    resource.setrlimit(resource.RLIMIT_AS, (a.mem_mb << 20, a.mem_mb << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if run_timeout_policy.wrapper_limit():  # per-run cap for the whole tree (analysis and probes already waited for)
        run_timeout_policy.set_cpu_rlimit(run_timeout_policy.wrapper_limit())
    fo = os.open(final["out"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    fe = os.open(final["err"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(fo, 1)
    os.dup2(fe, 2)
    os.execve(cmd[0], cmd, dict(env_base, FPC_LOG=final["tel"]))


if __name__ == "__main__":
    main()
