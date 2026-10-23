#!/usr/bin/env python3
"""Runner for the goal-v6 observations (docs/STABLE_SELECTION_PROTOCOL_V6.md).

  v6run.py obs6  --hashes FILE --flips 10000[,50000] [--sections s28,resid,ls] [--reps 1]
  v6run.py obs5ls --hashes FILE [--reps 3]          (v5 tool, local search, control)
  v6run.py sz    --hashes FILE --groups base[,unit...] [--per-group] [--cap 3]
  v6run.py wrap  --hashes FILE --strategy S.json[,...] | --strategy-map MAP.json
  ... [--jobs 48] [--shard i/n] [--status]

Records: $FP_DATA/runs/stable_selection_v6/<kind>/<id[:2]>/<id>.json, content
addressed (inputs, parameters, repetition index, tool hashes); existing
records are skipped. Each job is pinned to one physical core.
"""

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import random
import shutil
import socket
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "observations_v5"))
import fprun  # noqa: E402
import szlib  # noqa: E402
import v5lib  # noqa: E402

OUT = os.environ.get("V6_OUT", os.path.join(fprun.DATA, "runs", "stable_selection_v6"))
MEM_MB = 16000
TIMEOUT = 300
OBS6 = os.path.join(fprun.ROOT, "build", "tools", "obsprofile6")
SECTION_CAPS6 = {"polar": 0.5, "resid": 0.5, "bilat": 0.5, "graph": 0.5, "comm": 1.0, "ls": 1.0}
SEED = 20261023


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
    base = {"schema": 1}
    jobs = []
    for h in hashes(a.hashes):
        for rep in range(a.reps):
            if a.cmd == "obs6":
                for w in map(int, a.flips.split(",")):
                    jobs.append(("obs6", dict(base, kind="obs6", instance=h, rep=rep, flips=w, sections=a.sections,
                                              cap=a.cap, section_caps=SECTION_CAPS6, seed=SEED,
                                              tool_sha256=fprun.sha256_file(OBS6))))
            elif a.cmd == "obs5ls":
                jobs.append(("obs5ls", dict(base, kind="obs5ls", instance=h, rep=rep, sections="resid,ls", cap=30.0,
                                            section_caps=v5lib.SECTION_CAPS, seed=v5lib.OBS_SEED,
                                            tool_sha256=fprun.sha256_file(v5lib.OBSPROFILE))))
            elif a.cmd == "sz":
                groups = a.groups.split(",")
                sets = [[g] for g in groups] if a.per_group else [groups]
                for gs in sets:
                    jobs.append(("sz", dict(base, kind="sz", instance=h, rep=rep, groups=gs, cap=a.cap,
                                            tool_sha256=fprun.sha256_file(szlib.SZ_BIN))))
            elif a.cmd == "wrap":
                strats = (json.load(open(a.strategy_map))[h] if a.strategy_map else a.strategy.split(","))
                for s in strats:
                    s = os.path.join(fprun.ROOT, s) if not os.path.isabs(s) else s
                    jobs.append(("wrap", dict(base, kind="wrap", instance=h, rep=rep,
                                              strategy=os.path.relpath(s, fprun.ROOT), strategy_sha256=fprun.sha256_file(s),
                                              wrapper_sha256=fprun.sha256_file(os.path.join(HERE, "v6_wrapper.py")),
                                              lib_sha256=fprun.sha256_file(os.path.join(HERE, "v6lib.py")),
                                              tools=[fprun.sha256_file(OBS6), fprun.sha256_file(szlib.SZ_BIN),
                                                     fprun.sha256_file(v5lib.FORMAL)],
                                              timeout=TIMEOUT, mem_mb=MEM_MB)))
    return [(k, key, key_id(key)) for k, key in jobs]


def run_obs(binary, key, cnf, work, extra):
    caps = ",".join(f"{k}:{v}" for k, v in key["section_caps"].items())
    cmd = [binary, f"--sections={key['sections']}", f"--cap={key['cap']}", f"--seccap={caps}",
           f"--seed={key['seed']}"] + extra + [cnf]
    so, se = os.path.join(work, "o.json"), os.path.join(work, "o.err")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    r = v5lib.twlib.run_budget(cmd, env, key["cap"] + 5.0, MEM_MB, so, se)
    out = {"cpu": r["cpu"], "exit_code": r["exit_code"], "terminated_by": r["terminated_by"], "maxrss_kb": r["maxrss_kb"]}
    try:
        d = json.load(open(so))
        out.update(sections=d["sections"], features=d["features"], meta=d.get("meta"))
    except (OSError, ValueError, KeyError):
        out.update(sections={}, features={}, error=open(se, "rb").read()[-400:].decode("utf-8", "replace"))
    return out


def do(key, rid, work):
    cnf = fprun.stage_cnf(key["instance"], "orig", 0)
    if key["kind"] == "obs6":
        return run_obs(OBS6, key, cnf, work, [f"--ls-flips={key['flips']}"])
    if key["kind"] == "obs5ls":
        return run_obs(v5lib.OBSPROFILE, key, cnf, work, [])
    if key["kind"] == "sz":
        return szlib.run_satzilla(cnf, key["groups"], key["cap"], work, MEM_MB)
    if key["kind"] == "wrap":
        import v6_deploy  # noqa: E402  (real wrapper runner, written for R3/R4)
        return v6_deploy.do_wrap(key, rid, work, cnf, OUT)
    raise ValueError(key["kind"])


def execute(job, core, log):
    kind, key, rid = job
    path = rec_path(kind, rid)
    if os.path.exists(path):
        return "exists"
    os.makedirs(os.path.join(fprun.LOCAL, "work"), exist_ok=True)
    work = tempfile.mkdtemp(prefix=f"v6_{kind}_{rid[:10]}_", dir=os.path.join(fprun.LOCAL, "work"))
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        body = do(key, rid, work)
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
    jobs, core, log = args
    if core is not None:
        os.sched_setaffinity(0, {core})
    out = {}
    for j in jobs:
        try:
            st = execute(j, core, log)
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
    print(f"[v6run] {a.cmd}: {len(jobs)} jobs, {len(mine)} to run on {nj} cores", flush=True)
    for h in sorted({j[1]["instance"] for j in mine}):
        fprun.stage_cnf(h, "orig", 0)
    chunks = [mine[k::nj] for k in range(nj)]
    totals = {}
    with mp.Pool(nj) as pool:
        for out in pool.imap_unordered(worker, [(chunks[k], cores[k], log) for k in range(nj)]):
            for s, c in out.items():
                totals[s] = totals.get(s, 0) + c
    print(f"[v6run] done {totals}", flush=True)


def cmd_status(a):
    jobs = plan(a)
    done = sum(os.path.exists(rec_path(k, rid)) for k, _, rid in jobs)
    print(json.dumps({"cmd": a.cmd, "jobs": len(jobs), "done": done}))


def parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["obs6", "obs5ls", "sz", "wrap"])
    ap.add_argument("--hashes", required=True)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--flips", default="10000")
    ap.add_argument("--sections", default="s28,resid,ls")
    ap.add_argument("--cap", type=float, default=30.0)
    ap.add_argument("--groups", default=",".join(szlib.CANDIDATE_GROUPS))
    ap.add_argument("--per-group", action="store_true")
    ap.add_argument("--strategy")
    ap.add_argument("--strategy-map")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--order-seed", type=int, default=1)
    ap.add_argument("--status", action="store_true")
    return ap


def main():
    a = parser().parse_args()
    (cmd_status if a.status else cmd_run)(a)


if __name__ == "__main__":
    main()
