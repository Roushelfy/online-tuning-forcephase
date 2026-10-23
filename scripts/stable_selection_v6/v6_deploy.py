"""Real wrapper run for v6run.py (kind 'wrap'): runs v6_wrapper.py under a
guard limit, verifies the answer like the formal runs (fprun.verify) and
keeps the raw logs (stdout without witness lines, telemetry) gzipped."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fprun  # noqa: E402


def do_wrap(key, rid, work, cnf, out_root):
    wd = os.path.join(work, "w")
    strategy = os.path.join(fprun.ROOT, key["strategy"])
    cmd = [sys.executable, os.path.join(HERE, "v6_wrapper.py"), "--strategy", strategy, "--cnf", cnf,
           "--timeout", str(key["timeout"]), "--workdir", wd, "--mem-mb", str(key["mem_mb"])]
    so, se = os.path.join(work, "wrapper.out"), os.path.join(work, "wrapper.err")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
           "FP_DATA": os.environ.get("FP_DATA", fprun.DATA)}
    r = fprun.run_limited(cmd, env, key["timeout"] + 30, key["mem_mb"] + 4000, None, so, se,
                          wall_limit=2 * key["timeout"] + 120)
    res_path = os.path.join(wd, "result.json")
    res = json.load(open(res_path)) if os.path.exists(res_path) else None
    rec = {"wrapper_exit": r["exit_code"], "wrapper_terminated_by": r["terminated_by"], "total_cpu": r["cpu"],
           "wall": r["wall"], "maxrss_kb": r["maxrss_kb"], "result": res,
           "wrapper_stderr_tail": open(se, "rb").read()[-1500:].decode("utf-8", "replace")}
    ver = None
    if res and res.get("answer_exit") in (10, 20):
        ver = fprun.verify(res["answer_exit"], cnf, res["answer_stdout"], res["answer_proof"], key["timeout"],
                           key["mem_mb"], work)
    rec["verification"] = ver
    answered = bool(res and res.get("answer_exit") in (10, 20))
    within = r["cpu"] <= key["timeout"] and r["terminated_by"] is None
    if answered and within:
        rec["status"] = {True: "solved", False: "wrong"}.get(ver["ok"] if ver else None, "unverified")
    elif res is None:
        rec["status"] = "error"
    else:
        rec["status"] = "timeout"
    rec["result_label"] = {10: "SAT", 20: "UNSAT"}.get((res or {}).get("answer_exit")) if rec["status"] == "solved" else None
    rd = os.path.join(out_root, "wrap_raw", rid[:2], rid)
    os.makedirs(rd, exist_ok=True)
    for sub in ("", "o6", "sz"):
        d = os.path.join(wd, sub)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if not os.path.isfile(p):
                continue
            tag = (sub + "_" if sub else "") + f
            if f.endswith((".err", ".jsonl", ".json", ".csv")):
                fprun.compress_into(p, os.path.join(rd, tag + ".gz"))
            elif f.endswith(".out"):
                with open(p, "rb") as fi, open(p + ".nov", "wb") as fo:
                    for line in fi:
                        if not line.startswith(b"v "):
                            fo.write(line)
                fprun.compress_into(p + ".nov", os.path.join(rd, tag + ".gz"))
    fprun.compress_into(se, os.path.join(rd, "wrapper.err.gz"))
    return rec
