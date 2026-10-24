#!/usr/bin/env python3
"""v9 R3 robustness (protocol section 6): 54 development instances (the 6 smallest split-hash ranks in each main
cell); solver seed 1 x {D, Fp, Fm} on the original CNF, and the renamed variant (cnfscramble perm 1) x
{D, Fp, Fm, W_ref}. Variants stay grouped with their base instance (never new samples).

  robust.py make       -> variant CNFs, results/online_selection_v9/robust_manifest.json, configs/online_selection_v9/robust.json
  robust.py analyze    -> results/online_selection_v9/robust.json
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
CFG = os.path.join(ROOT, "configs", "online_selection_v9")
RES = os.path.join(ROOT, "results", "online_selection_v9")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
CNF = os.path.join(DATA, "online_selection_v9", "cnf")
REF = "configs/online_selection_v9/strategies/ref_D2_Fp.json"
ACTS = ("D", "Fp", "Fm")


def chosen():
    split = json.load(open(os.path.join(CFG, "split.json")))
    out = []
    for s in ("L", "M", "S"):
        for t in ("rand3", "col3", "assign2"):
            cell = sorted([i for i, v in split.items() if v["split"] == "dev" and v["role"] == "main" and v["type"] == t
                           and v["scale"] == s], key=lambda i: split[i]["split_hash"])
            out += cell[:6]
    return out, split


def make():
    ids, split = chosen()
    rows, jobs = [], []
    for i in ids:
        v = f"{i}~perm1"
        out = os.path.join(CNF, v + ".cnf")
        if not os.path.exists(out):
            subprocess.run([os.path.join(ROOT, "build", "tools", "cnfscramble"), os.path.join(CNF, i + ".cnf"), out, "perm", "1"],
                           check=True)
        sha = hashlib.sha256(open(out, "rb").read()).hexdigest()
        rows.append({"id": v, "base": i, "variant": "perm1", "sha256": sha})
        b = {"instance": i, "sha256": split[i]["sha256"], "rep": 0, "seed": 1}
        jobs += [dict(b, method=m) for m in ACTS]
        bv = {"instance": v, "sha256": sha, "rep": 0}
        jobs += [dict(bv, method=m) for m in ACTS] + [dict(bv, method="W", strategy=REF)]
    json.dump({"instances": rows}, open(os.path.join(RES, "robust_manifest.json"), "w"), indent=1)
    json.dump({"stage": "robust", "jobs": jobs}, open(os.path.join(CFG, "robust.json"), "w"), indent=1)
    print(len(ids), len(jobs))


def analyze():
    ids, split = chosen()
    tab = json.load(open(os.path.join(RES, "dev_table.json")))
    rec = {}
    for p in glob.glob(os.path.join(DATA, "runs", "online_selection_v9", "robust", "*.json")):
        if p.endswith(("progress.json", "effective_plan.json")):
            continue
        r = json.load(open(p))
        ok = r["status"] == "solved" and (r.get("verification") or {}).get("ok") is True
        variant = "perm1" if r["instance"].endswith("~perm1") else f"seed{r.get('seed', 0)}"
        m = "W_ref" if r["method"] == "W" else r["method"]
        rec[(r["instance"].split("~")[0], variant, m)] = r["cpu"] if ok else None
    out = {"n": len(ids), "variants": {}}
    for var, methods in (("seed1", ACTS), ("perm1", ACTS + ("W_ref",))):
        rows = []
        for i in ids:
            base = {**tab[i]["t"], "W_ref": (tab[i]["ref"] or {}).get("cpu")}
            new = {m: rec.get((i, var, m)) for m in methods}
            if any(new[m] is None for m in methods):
                continue
            rows.append({"instance": i, "base": base, "new": new})
        res = {"complete": len(rows)}
        if rows:
            win = lambda d: min(ACTS, key=lambda m: (d[m], ACTS.index(m)))  # noqa: E731
            res["winner_same"] = sum(1 for r in rows if win(r["base"]) == win(r["new"]))
            res["totals_base"] = {m: sum(r["base"][m] for r in rows) for m in methods}
            res["totals_new"] = {m: sum(r["new"][m] for r in rows) for m in methods}
            res["median_abs_log2"] = {m: sorted(abs(math.log2(r["new"][m] / r["base"][m])) for r in rows)[len(rows) // 2]
                                      for m in methods}
            res["Fp_vs_D_sign_same"] = sum(1 for r in rows if (r["base"]["Fp"] < r["base"]["D"]) == (r["new"]["Fp"] < r["new"]["D"]))
            res["gain_Fp_vs_D_pct"] = {k: 100 * (1 - res[k]["Fp"] / res[k]["D"]) for k in ("totals_base", "totals_new")}
            if "W_ref" in methods:
                res["gain_Wref_vs_D_pct"] = {k: 100 * (1 - res[k]["W_ref"] / res[k]["D"]) for k in ("totals_base", "totals_new")}
        out["variants"][var] = res
    json.dump(out, open(os.path.join(RES, "robust.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    {"make": make, "analyze": analyze}[sys.argv[1]]()
