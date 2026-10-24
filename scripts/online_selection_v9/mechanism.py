#!/usr/bin/env python3
"""v9 R4 analysis (protocol section 8): paired contrasts of D / D_R0 / D_P0 / D_R0_P0 / Fp / Fm on the 54
diagnostic development instances, by type x answer. Writes results/online_selection_v9/mechanism.json.
"""
import collections
import glob
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "online_selection_v9")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
CONFIGS = ("D", "D_R0", "D_P0", "D_R0_P0", "Fp", "Fm")
CONTRASTS = {
    "rephase_off (D_R0 vs D)": ("D_R0", "D"),
    "rephase_off at phase 0 (D_R0_P0 vs D_P0)": ("D_R0_P0", "D_P0"),
    "force over saved/target, phase 1 (Fp vs D_R0)": ("Fp", "D_R0"),
    "force over saved/target, phase 0 (Fm vs D_R0_P0)": ("Fm", "D_R0_P0"),
    "initial phase 0 vs 1, default (D_P0 vs D)": ("D_P0", "D"),
    "initial phase 0 vs 1, no rephase (D_R0_P0 vs D_R0)": ("D_R0_P0", "D_R0"),
    "initial phase 0 vs 1, forced (Fm vs Fp)": ("Fm", "Fp"),
    "forcephase total (Fp vs D)": ("Fp", "D"),
    "forcephase total (Fm vs D)": ("Fm", "D"),
}


def med(v):
    v = sorted(v)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def main():
    sel = json.load(open(os.path.join(RES, "mechanism_instances.json")))
    ans = {i: a for c in sel["cells"].values() for i, a in c["picked"].items()}
    t = collections.defaultdict(dict)
    status = collections.Counter()
    for p in glob.glob(os.path.join(DATA, "runs", "online_selection_v9", "mech_dev", "*.json")):
        if p.endswith(("progress.json", "effective_plan.json")):
            continue
        r = json.load(open(p))
        ok = r["status"] == "solved" and (r.get("verification") or {}).get("ok") is True
        status[r["status"] if ok or r["status"] != "solved" else "unverified"] += 1
        if ok:
            t[r["instance"]][r["method"]] = r["cpu"]
    full = [i for i in sel["instances"] if all(c in t[i] for c in CONFIGS)]
    out = {"n_selected": len(sel["instances"]), "n_complete": len(full), "statuses": dict(status), "groups": {}}
    groups = collections.defaultdict(list)
    for i in full:
        typ = i.split("-")[1]
        groups[f"{typ}-{ans[i]}"].append(i)
        groups[f"all-{ans[i]}"].append(i)
        groups["all"].append(i)
    for g, ids in sorted(groups.items()):
        d = {"n": len(ids), "totals": {c: sum(t[i][c] for i in ids) for c in CONFIGS}, "contrasts": {}}
        for name, (a, b) in CONTRASTS.items():
            lr = [math.log2(t[i][a] / t[i][b]) for i in ids]
            d["contrasts"][name] = {"median_log2": med(lr), "faster": sum(1 for x in lr if x < -0.0704),
                                    "slower": sum(1 for x in lr if x > 0.0704), "n": len(lr),
                                    "total_ratio": sum(t[i][a] for i in ids) / sum(t[i][b] for i in ids)}
        out["groups"][g] = d
    out["per_instance"] = {i: {"answer": ans[i], **t[i]} for i in full}
    json.dump(out, open(os.path.join(RES, "mechanism.json"), "w"), indent=1)
    for g, d in out["groups"].items():
        print(g, d["n"], {k.split(" (")[1][:-1]: (round(v["median_log2"], 2), v["faster"], v["slower"])
                          for k, v in d["contrasts"].items()})


if __name__ == "__main__":
    main()
