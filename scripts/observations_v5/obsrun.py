#!/usr/bin/env python3
"""Runner for the goal-v5 observations (offline collection) and wrappers.

  obsrun.py obs  --hashes FILE [--variants orig,flipall,perm1]
  obsrun.py arm  --hashes FILE --tags e02,e05,ec,fD [--actions D,Fp,Fm] [--variants orig]
  obsrun.py eqv  --hashes FILE                 (equivalence gate, protocol section 3)
  obsrun.py wrap --hashes FILE --strategy S1.json[,S2.json...] [--observe-only]
  obsrun.py wrap --hashes FILE --strategy-map MAP.json     (per-instance strategies)
  ... [--jobs 48] [--shard i/n] [--status]

obs: obsprofile with all sections (protocol section caps, total cap 30 s,
so every section's own status/CPU is recorded); arm: one probe arm
(v5lib.run_arm), answers verified like the formal runs (fprun.verify);
eqv: build/obs vs build/fpc at a conflict limit of 20,000 for D/F+/F-;
wrap: the deployable wrapper v5_wrapper.py.

Records: $FP_DATA/runs/observations_v5/<kind>/<id[:2]>/<id>.json, content
addressed (inputs, code and binary hashes); existing records are skipped.
Raw arm output (stdout without witness lines, telemetry) is kept gzipped
under .../arm_raw/. Each job is pinned to one physical core.
"""

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import fprun  # noqa: E402
import v5lib  # noqa: E402

OUT = os.environ.get("V5_OUT", os.path.join(fprun.DATA, "runs", "observations_v5"))
MEM_MB = 16000
TIMEOUT = 300
SCHEMA = 1
VARIANTS = {"orig": ("orig", 0), "flipall": ("flipall", 0), "perm1": ("orig", 1)}


def sha_files(*paths):
    h = hashlib.sha256()
    for p in paths:
        h.update(open(p, "rb").read())
    return h.hexdigest()


def hashes(path):
    hs = []
    for p in path.split(","):
        hs += [l.split()[0] for l in open(p) if l.strip() and not l.startswith("#")]
    return sorted(set(hs))


def rec_path(kind, rid):
    return os.path.join(OUT, kind, rid[:2], rid + ".json")


def key_id(key):
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()


def plan(a):
    base = {"schema": SCHEMA, "code_sha256": sha_files(os.path.join(HERE, "v5lib.py"), os.path.join(HERE, "obsrun.py"))}
    jobs = []
    for h in hashes(a.hashes):
        for var in a.variants.split(","):
            if a.cmd == "obs":
                jobs.append(("obs", dict(base, kind="obs", instance=h, variant=var, cap=30.0,
                                         tool_sha256=fprun.sha256_file(v5lib.OBSPROFILE),
                                         section_caps=v5lib.SECTION_CAPS, seed=v5lib.OBS_SEED)))
            elif a.cmd == "arm":
                for tag in a.tags.split(","):
                    for act in a.actions.split(","):
                        jobs.append(("arm", dict(base, kind="arm", instance=h, variant=var, tag=tag, action=act,
                                                 arm=list(v5lib.ARMS[tag]), probe_sha256=fprun.sha256_file(v5lib.PROBE),
                                                 win=v5lib.PROBE_WIN, mem_mb=MEM_MB)))
            elif a.cmd == "eqv":
                for act in v5lib.ACT_ORDER:
                    jobs.append(("eqv", dict(base, kind="eqv", instance=h, variant=var, action=act, conflicts=a.conflicts,
                                             probe_sha256=fprun.sha256_file(v5lib.PROBE),
                                             formal_sha256=fprun.sha256_file(v5lib.FORMAL))))
            elif a.cmd == "wrap":
              strats = (json.load(open(a.strategy_map))[h] if getattr(a, "strategy_map", None)
                        else a.strategy.split(","))
              for strat in strats:
                strat = os.path.join(fprun.ROOT, strat) if not os.path.isabs(strat) else strat
                jobs.append(("wrap", dict(base, kind="wrap", instance=h, variant=var,
                                          strategy=os.path.relpath(os.path.abspath(strat), fprun.ROOT),
                                          strategy_sha256=fprun.sha256_file(strat),
                                          wrapper_sha256=fprun.sha256_file(os.path.join(HERE, "v5_wrapper.py")),
                                          feat_sha256=fprun.sha256_file(os.path.join(HERE, "obsfeat.py")),
                                          probe_sha256=fprun.sha256_file(v5lib.PROBE),
                                          formal_sha256=fprun.sha256_file(v5lib.FORMAL),
                                          tool_sha256=fprun.sha256_file(v5lib.OBSPROFILE),
                                          observe_only=bool(a.observe_only), timeout=TIMEOUT, mem_mb=MEM_MB)))
    return [(k, key, key_id(key)) for k, key in jobs]


def stage(key):
    v, s = VARIANTS[key["variant"]]
    return fprun.stage_cnf(key["instance"], v, s)


def verify(code, cnf, so, proof, work):
    if code not in (10, 20):
        return None
    return fprun.verify(code, cnf, so, proof, TIMEOUT, MEM_MB, work)


def do_obs(key, rid, work):
    cnf = stage(key)
    r = v5lib.run_obsprofile(cnf, v5lib.ALL_SECTIONS, key["cap"], work, MEM_MB)
    return r


def do_arm(key, rid, work):
    cnf = stage(key)
    raw = os.path.join(OUT, "arm_raw", rid[:2], rid)
    r = v5lib.run_arm(cnf, key["action"], key["tag"], work, key["mem_mb"], keep_raw=raw)
    ver = verify(r["exit_code"], cnf, r["stdout"], r["proof"], work)
    r["verification"] = ver
    r["solved"] = bool(r["answered"] and ver and ver["ok"] is True)
    r["result_label"] = {10: "SAT", 20: "UNSAT"}.get(r["exit_code"]) if r["solved"] else None
    for k in ("stdout", "proof"):
        r.pop(k, None)
    return r


def do_eqv(key, rid, work):
    cnf = stage(key)
    out = {}
    for name, binary, extra in (("formal", v5lib.FORMAL, []), ("probe", v5lib.PROBE, [f"--fpcwin={v5lib.PROBE_WIN}"])):
        tel, so, se = (os.path.join(work, f"{name}.{x}") for x in ("tel", "out", "err"))
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "FPC_LOG": tel}
        cmd = [binary] + v5lib.RUN_POLICY + v5lib.ACTIONS[key["action"]][1] + ["--fpc=1"] + extra + \
            ["-c", str(key["conflicts"]), cnf, os.path.join(work, f"{name}.lrat")]
        r = v5lib.twlib.run_budget(cmd, env, 120.0, MEM_MB, so, se)
        _, stats, _ = v5lib.twlib.parse_stats(so)
        fin, _ = v5lib.parse_obs_telemetry(tel)
        out[name] = {"exit_code": r["exit_code"], "cpu": r["cpu"], "terminated_by": r["terminated_by"],
                     "stats": stats, "digest": (fin or {}).get("digest")}
    keys = ("conflicts", "decisions", "propagations", "fixed", "learned_lits", "restarts", "rephased", "reduced")
    out["same"] = (out["formal"]["exit_code"] == out["probe"]["exit_code"] and
                   out["formal"]["digest"] == out["probe"]["digest"] and out["formal"]["digest"] is not None and
                   all(out["formal"]["stats"].get(k) == out["probe"]["stats"].get(k) for k in keys))
    return out


def do_wrap(key, rid, work):
    cnf = stage(key)
    strategy = os.path.join(fprun.ROOT, key["strategy"])
    wd = os.path.join(work, "w")
    cmd = [sys.executable, os.path.join(HERE, "v5_wrapper.py"), "--strategy", strategy, "--cnf", cnf,
           "--timeout", str(key["timeout"]), "--workdir", wd, "--mem-mb", str(key["mem_mb"])]
    if key["observe_only"]:
        cmd.append("--observe-only")
    so, se = os.path.join(work, "wrapper.out"), os.path.join(work, "wrapper.err")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    r = fprun.run_limited(cmd, env, key["timeout"] + 30, key["mem_mb"] + 4000, None, so, se,
                          wall_limit=2 * key["timeout"] + 120)
    res_path = os.path.join(wd, "result.json")
    res = json.load(open(res_path)) if os.path.exists(res_path) else None
    rec = {"wrapper_exit": r["exit_code"], "wrapper_terminated_by": r["terminated_by"], "total_cpu": r["cpu"],
           "wall": r["wall"], "maxrss_kb": r["maxrss_kb"], "result": res,
           "wrapper_stderr_tail": open(se, "rb").read()[-1500:].decode("utf-8", "replace")}
    ver = None
    if res and res.get("answer_exit") in (10, 20):
        ver = verify(res["answer_exit"], cnf, res["answer_stdout"], res["answer_proof"], work)
    rec["verification"] = ver
    answered = bool(res and res.get("answer_exit") in (10, 20))
    within = r["cpu"] <= key["timeout"] and r["terminated_by"] is None
    if key["observe_only"]:
        rec["status"] = "observed" if res else "error"
    elif answered and within:
        rec["status"] = {True: "solved", False: "wrong"}.get(ver["ok"] if ver else None, "unverified")
    elif res is None:
        rec["status"] = "error"
    else:
        rec["status"] = "timeout"
    rec["result_label"] = {10: "SAT", 20: "UNSAT"}.get((res or {}).get("answer_exit")) if rec["status"] == "solved" else None
    rd = os.path.join(OUT, "wrap_raw", rid[:2], rid)
    os.makedirs(rd, exist_ok=True)
    if os.path.isdir(wd):
        for f in os.listdir(wd):
            p = os.path.join(wd, f)
            if f.endswith((".err", ".jsonl", ".json")):
                fprun.compress_into(p, os.path.join(rd, f + ".gz"))
            elif f.endswith(".out"):
                with open(p, "rb") as fi, open(p + ".nov", "wb") as fo:
                    for line in fi:
                        if not line.startswith(b"v "):
                            fo.write(line)
                fprun.compress_into(p + ".nov", os.path.join(rd, f + ".gz"))
    fprun.compress_into(se, os.path.join(rd, "wrapper.err.gz"))
    return rec


def execute(job, core, strategy, log):
    kind, key, rid = job
    path = rec_path(kind, rid)
    if os.path.exists(path):
        return "exists"
    os.makedirs(os.path.join(fprun.LOCAL, "work"), exist_ok=True)
    work = tempfile.mkdtemp(prefix=f"v5_{kind}_{rid[:10]}_", dir=os.path.join(fprun.LOCAL, "work"))
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        body = {"obs": do_obs, "arm": do_arm, "eqv": do_eqv, "wrap": do_wrap}[kind](key, rid, work)
        rec = {"id": rid, "key": key, "host": socket.gethostname(), "core": core, "cpu_model": fprun.cpu_model(),
               "slurm_job": os.environ.get("SLURM_JOB_ID"), "start_utc": start,
               "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **body}
        fprun.atomic_write_json(path, rec)
        with open(log, "a") as f:
            f.write(json.dumps({"id": rid, "kind": kind, "event": "done", "start": start}) + "\n")
        return "done"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def worker(args):
    jobs, core, strategy, log = args
    if core is not None:
        os.sched_setaffinity(0, {core})
    out = {}
    for j in jobs:
        try:
            st = execute(j, core, strategy, log)
        except Exception as e:
            st = "runner-error"
            with open(log, "a") as f:
                f.write(json.dumps({"id": j[2], "event": "runner-error", "error": repr(e),
                                    "traceback": traceback.format_exc()[-2000:]}) + "\n")
        out[st] = out.get(st, 0) + 1
    return out


def cmd_run(a):
    jobs = plan(a)
    i, n = map(int, a.shard.split("/"))
    mine = [j for j in jobs if int(j[2][:8], 16) % n == i and not os.path.exists(rec_path(j[0], j[2]))]
    random.Random(a.order_seed).shuffle(mine)
    cores = fprun.physical_cores()
    if a.jobs and a.jobs < len(cores):
        step = len(cores) / a.jobs
        cores = [cores[int(k * step)] for k in range(a.jobs)]
    nj = min(a.jobs or len(cores), len(cores), max(1, len(mine)))
    os.makedirs(os.path.join(OUT, "attempts"), exist_ok=True)
    log = os.path.join(OUT, "attempts", f"{a.cmd}-{socket.gethostname()}-{os.getpid()}.jsonl")
    print(f"[obsrun] {a.cmd}: {len(jobs)} jobs, {len(mine)} to run on {nj} cores", flush=True)
    # stage CNFs once (decompression is not part of any measured observation)
    for h in sorted({j[1]["instance"] for j in mine}):
        for var in sorted({j[1]["variant"] for j in mine if j[1]["instance"] == h}):
            stage({"instance": h, "variant": var})
    chunks = [mine[k::nj] for k in range(nj)]
    strategy = None
    totals = {}
    with mp.Pool(nj) as pool:
        for out in pool.imap_unordered(worker, [(chunks[k], cores[k], strategy, log) for k in range(nj)]):
            for s, c in out.items():
                totals[s] = totals.get(s, 0) + c
    print(f"[obsrun] done {totals}", flush=True)


def cmd_status(a):
    jobs = plan(a)
    done = sum(os.path.exists(rec_path(k, rid)) for k, _, rid in jobs)
    print(json.dumps({"cmd": a.cmd, "jobs": len(jobs), "done": done}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["obs", "arm", "eqv", "wrap"])
    ap.add_argument("--hashes", required=True)
    ap.add_argument("--variants", default="orig")
    ap.add_argument("--tags", default="e02,e05,ec,fD")
    ap.add_argument("--actions", default="D,Fp,Fm")
    ap.add_argument("--conflicts", type=int, default=20000, help="eqv: conflict limit")
    ap.add_argument("--strategy")
    ap.add_argument("--strategy-map", help="wrap: JSON {hash: [strategy paths]} (per-instance fold models)")
    ap.add_argument("--observe-only", action="store_true")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--order-seed", type=int, default=1)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.cmd == "wrap" and not (a.strategy or a.strategy_map):
        raise SystemExit("--strategy or --strategy-map required")
    (cmd_status if a.status else cmd_run)(a)


if __name__ == "__main__":
    main()
