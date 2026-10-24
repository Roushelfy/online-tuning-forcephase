#!/usr/bin/env python3
"""v8 registered mechanism check (docs/STRATIFIED_PROTOCOL_V8.md section 10): paired variants of the
development instances -- V1 `flipall` (every literal negated) and V2 `perm 1` (variables renamed) via
build/tools/cnfscramble -- each run with D / Fp / Fm. Variants are never independent samples and never
feed the frozen rule.

  mechanism.py make      (inside the container)  -> variant CNFs + results/stratified_v8/mechanism_manifest.json
                                                    + configs/stratified_v8/mech_dev.json (run plan)
  mechanism.py analyze                            -> results/stratified_v8/mechanism.json
"""

import glob
import hashlib
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
CNF = os.path.join(DATA, "stratified_v8", "cnf")
CFG = os.path.join(ROOT, "configs", "stratified_v8")
RES = os.path.join(ROOT, "results", "stratified_v8")
VARIANTS = {"flipall": ("flipall", "0"), "perm1": ("perm", "1")}
ACTS = ("D", "Fp", "Fm")


def make():
    split = json.load(open(os.path.join(CFG, "split.json")))
    dev = sorted(i for i, v in split.items() if v["split"] == "dev")
    rows, jobs = [], []
    for i in dev:
        for tag, (mode, seed) in VARIANTS.items():
            vid = f"{i}~{tag}"
            out = os.path.join(CNF, vid + ".cnf")
            subprocess.run([os.path.join(ROOT, "build", "tools", "cnfscramble"), os.path.join(CNF, i + ".cnf"), out, mode,
                            seed], check=True)
            sha = hashlib.sha256(open(out, "rb").read()).hexdigest()
            rows.append({"id": vid, "base": i, "variant": tag, "cmd": ["cnfscramble", i + ".cnf", vid + ".cnf", mode, seed],
                         "sha256": sha})
    # pre-registered order: as S1 (L, M, S; types; split hash), variants adjacent, actions adjacent
    order = []
    for s in ("L", "M", "S"):
        for t in ("rand3", "col3", "assign"):
            order += sorted([i for i in dev if split[i]["type"] == t and split[i]["scale"] == s],
                            key=lambda i: split[i]["split_hash"])
    by = {(r["base"], r["variant"]): r for r in rows}
    for i in order:
        for tag in VARIANTS:
            for m in ACTS:
                jobs.append({"instance": by[(i, tag)]["id"], "sha256": by[(i, tag)]["sha256"], "method": m, "rep": 0,
                             "cap_cpu": 900})
    json.dump({"variants": VARIANTS, "instances": rows}, open(os.path.join(RES, "mechanism_manifest.json"), "w"), indent=1)
    json.dump({"stage": "mech_dev", "jobs": jobs}, open(os.path.join(CFG, "mech_dev.json"), "w"), indent=1)
    print(len(rows), len(jobs))


def analyze():
    split = json.load(open(os.path.join(CFG, "split.json")))
    base = json.load(open(os.path.join(RES, "dev_times.json")))
    recs = {}
    for p in glob.glob(os.path.join(DATA, "runs", "stratified_v8", "mech_dev", "*.json")):
        if p.endswith("progress.json"):
            continue
        r = json.load(open(p))
        recs[(r["instance"], r["method"])] = r
    out = {"pairs": [], "summary": {}}
    for i in sorted(base):
        for tag in VARIANTS:
            row = {"base": i, "variant": tag, "type": split[i]["type"], "scale": split[i]["scale"]}
            for m in ACTS:
                r = recs.get((f"{i}~{tag}", m))
                row[m] = r["cpu"] if r and r["status"] == "solved" else None
                row[m + "_status"] = r["status"] if r else "missing"
                row[m + "_orig"] = base[i][m]
            out["pairs"].append(row)
    for tag in VARIANTS:
        rows = [r for r in out["pairs"] if r["variant"] == tag and all(r[m] is not None for m in ACTS)]
        s = {"complete_pairs": len(rows), "of": sum(1 for r in out["pairs"] if r["variant"] == tag)}
        win = lambda r, suf: min(ACTS, key=lambda m: (r[m + suf], ACTS.index(m)))  # noqa: E731
        s["winner_same"] = sum(1 for r in rows if win(r, "") == win(r, "_orig"))
        if tag == "flipall":
            swap = {"D": "D", "Fp": "Fm", "Fm": "Fp"}
            s["winner_same_after_swap"] = sum(1 for r in rows if win(r, "") == swap[win(r, "_orig")])
            s["median_abs_log_Fp_vs_origFm"] = med([abs(math.log(r["Fp"] / r["Fm_orig"])) for r in rows])
            s["median_abs_log_Fm_vs_origFp"] = med([abs(math.log(r["Fm"] / r["Fp_orig"])) for r in rows])
        for m in ACTS:
            s[f"median_abs_log_{m}_vs_orig_{m}"] = med([abs(math.log(r[m] / r[m + "_orig"])) for r in rows])
            s[f"total_{m}"] = sum(r[m] for r in rows)
            s[f"total_{m}_orig"] = sum(r[m + "_orig"] for r in rows)
        by_type = {}
        for t in ("rand3", "col3", "assign"):
            rt = [r for r in rows if r["type"] == t]
            by_type[t] = {"pairs": len(rt), "winner_same": sum(1 for r in rt if win(r, "") == win(r, "_orig")),
                          **{f"total_{m}": sum(r[m] for r in rt) for m in ACTS},
                          **{f"total_{m}_orig": sum(r[m + "_orig"] for r in rt) for m in ACTS}}
            if tag == "flipall":
                by_type[t]["winner_same_after_swap"] = sum(1 for r in rt if win(r, "") == {"D": "D", "Fp": "Fm", "Fm": "Fp"}[win(r, "_orig")])
        s["by_type"] = by_type
        out["summary"][tag] = s
    json.dump(out, open(os.path.join(RES, "mechanism.json"), "w"), indent=1)
    print(json.dumps(out["summary"], indent=1))


def med(v):
    v = sorted(v)
    return None if not v else (v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2)


if __name__ == "__main__":
    {"make": make, "analyze": analyze}[sys.argv[1]]()
