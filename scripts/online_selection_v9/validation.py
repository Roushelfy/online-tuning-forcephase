#!/usr/bin/env python3
"""v9 R3 analysis: complete means, paired cell-stratified bootstrap, blocks and per-instance table for one
frozen panel (docs/ONLINE_SELECTION_PROTOCOL_V9.md sections 5-7). Standard library only.

  validation.py --stage holdout --panel holdout [--panel H1 ...] --sbs Fm --main configs/.../main.json
               [--ref configs/.../ref_D2_Fp.json] --out results/online_selection_v9/validation_holdout.json

Methods: D, Fp, Fm (fixed), SBS (= the development SBS action's fixed record), W_main, W_ref (wrappers).
A missing/unfinished/unverified record leaves that method's mean null (evaluate.py semantics).
"""
import argparse
import collections
import glob
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "online_selection_v9")
RES = os.path.join(ROOT, "results", "online_selection_v9")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
sys.path.insert(0, os.path.join(ROOT, "scripts", "completion_v7"))
import evaluate  # noqa: E402

ACTS = ("D", "Fp", "Fm")


def panel(name):
    return [l.split()[0] for l in open(os.path.join(CFG, f"panel_{name}.txt")) if l.strip() and not l.startswith("#")]


_STOPS = {x["id"] for x in json.load(open(os.path.join(ROOT, "results", "policy_stops.json")))["stops"]} \
    if os.path.exists(os.path.join(ROOT, "results", "policy_stops.json")) else set()
_CORR = {x["id"]: x["status"] for x in json.load(open(os.path.join(ROOT, "results", "verification_corrections.json")))["corrections"]} \
    if os.path.exists(os.path.join(ROOT, "results", "verification_corrections.json")) else {}


def norm(r, method):
    if r is not None and r["id"] in _STOPS:  # stopped under the 3600 s policy: actual-CPU lower bound
        r = dict(r, status="censored", stop_reason="policy_timeout")
    elif r is not None and r["id"] in _CORR:
        r = dict(r, status=_CORR[r["id"]])
    if r is None:
        return {"method": method, "status": "missing", "cpu_seconds": None, "verified": False, "measurement_valid": False}
    st = r["status"]
    if st == "solved" and (r.get("verification") or {}).get("ok") is True:
        out = {"status": "solved", "verified": True, "measurement_valid": True, "cpu_seconds": r["cpu"]}
    elif st in ("censored", "noncompetitive_bound"):
        out = {"status": st, "verified": False, "measurement_valid": True, "cpu_seconds": r["cpu"]}
    else:
        out = {"status": "error", "verified": False, "measurement_valid": False, "cpu_seconds": r.get("cpu")}
    out.update(instance=r["instance"], method=method, time_kind="measured_process_tree_cpu",
               source_run_id=f"v9:{r['id']}", answer={10: "SAT", 20: "UNSAT"}.get(r.get("exit_code")),
               path=r.get("path"), action=r.get("action"), pre_exec_cpu=r.get("pre_exec_cpu"))
    return out


def load(stages, ids, sbs, wrappers):
    recs = {}
    for st in stages:
        for p in glob.glob(os.path.join(DATA, "runs", "online_selection_v9", st, "*.json")):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            r = json.load(open(p))
            if r["instance"] not in ids or r.get("seed", 0) or r.get("rep", 0):
                continue
            m = r["method"] if r["method"] != "W" else wrappers.get(r.get("strategy"))
            if m is None:
                continue
            recs[(r["instance"], m)] = r
    out = []
    for i in ids:
        for m in list(ACTS) + sorted(set(wrappers.values())):
            x = norm(recs.get((i, m)), m)
            x["instance"] = i
            out.append(x)
        x = norm(recs.get((i, sbs)), "SBS")
        x["instance"] = i
        out.append(x)
    return out


def summarize(ids, rows, methods):
    cfg = {"panel_size": len(ids), "methods": methods, "baseline": "D", "required_methods": methods,
           "oracle_actions": list(ACTS), "require_oracle_complete": True, "metric": "mean_completed_cpu_seconds"}
    return evaluate.summarize(ids, [r for r in rows if r["method"] in methods], cfg)


def boot(ids, val, cell, num, den, B=10000, seed=0):
    rng = random.Random(seed)
    cells = collections.defaultdict(list)
    for i in ids:
        cells[cell[i]].append(i)
    out = []
    for _ in range(B):
        sn = sd = 0.0
        for c in cells.values():
            for _ in range(len(c)):
                i = c[rng.randrange(len(c))]
                sn += val[(i, num)]
                sd += val[(i, den)]
        out.append(100 * (1 - sn / sd))
    out.sort()
    return [out[int(0.025 * B)], out[int(0.975 * B) - 1]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", action="append", required=True)
    ap.add_argument("--panel", action="append", required=True)
    ap.add_argument("--sbs", required=True)
    ap.add_argument("--main")
    ap.add_argument("--ref")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    split = json.load(open(os.path.join(CFG, "split.json")))
    if os.path.exists(os.path.join(CFG, "split_external.json")):  # external SATLIB panel: one 'cell' per archive
        split.update(json.load(open(os.path.join(CFG, "split_external.json"))))
    wrappers = {}
    if a.main:
        wrappers[a.main] = "W_main"
    if a.ref and a.ref != a.main:
        wrappers[a.ref] = "W_ref"
    methods = list(ACTS) + ["SBS"] + sorted(set(wrappers.values()))
    result = {"sbs": a.sbs, "wrappers": wrappers, "panels": {}}
    for pn in a.panel:
        ids = panel(pn)
        rows = load(a.stage, set(ids), a.sbs, wrappers)
        s = summarize(ids, rows, methods)
        val = {(r["instance"], r["method"]): r["cpu_seconds"] for r in rows if r["status"] == "solved"}
        res = {"n": len(ids), "summary": s}
        complete = s["primary_comparison_complete"]
        cell = {i: (split[i]["type"], split[i]["scale"]) for i in ids}
        if complete:
            for i in ids:
                val[(i, "oracle")] = min(val[(i, x)] for x in ACTS)
            res["ci"] = {}
            for w in sorted(set(wrappers.values())) + ["SBS", "oracle", "Fp", "Fm"]:
                for base in ("D", "SBS"):
                    if w != base:
                        res["ci"][f"{w}_vs_{base}"] = boot(ids, val, cell, w, base)
            per = []
            for i in ids:
                row = {"instance": i, "cell": "-".join(cell[i]), "split": split[i]["split"],
                       **{m: val.get((i, m)) for m in methods}, "oracle": val[(i, "oracle")]}
                for r in rows:
                    if r["instance"] == i and r["method"] == "D":
                        row["answer"] = r.get("answer")
                    if r["instance"] == i and r["method"] in ("W_main", "W_ref"):
                        row[r["method"] + "_path"] = r.get("path")
                        row[r["method"] + "_action"] = r.get("action")
                        row[r["method"] + "_pre_exec"] = r.get("pre_exec_cpu")
                per.append(row)
            res["per_instance"] = per
            for w in sorted(set(wrappers.values())):
                gains = sorted(((row["D"] - row[w]), row["instance"]) for row in per)
                tot = sum(g for g, _ in gains)
                pos = sorted((g for g, _ in gains if g > 0), reverse=True)
                res[f"{w}_vs_D_detail"] = {
                    "total_saving": tot, "worst_loss": gains[0], "best_gain": gains[-1],
                    "top1_share_of_positive": (pos[0] / sum(pos)) if pos else None,
                    "top3_share_of_positive": (sum(pos[:3]) / sum(pos)) if pos else None,
                    "wins": sum(1 for g, _ in gains if g > 0), "losses": sum(1 for g, _ in gains if g < 0)}
            by_cell = {}
            for c in sorted(set(cell.values())):
                cid = [i for i in ids if cell[i] == c]
                by_cell["-".join(c)] = {m: sum(val[(i, m)] for i in cid) / len(cid) for m in methods + ["oracle"]}
            res["by_cell"] = by_cell
            by_ans = {}
            for row in per:
                k = f"{row['cell'].split('-')[0]}-{row.get('answer')}"
                d = by_ans.setdefault(k, {"n": 0, **{m: 0.0 for m in methods}})
                d["n"] += 1
                for m in methods:
                    d[m] += row[m]
            res["by_type_answer"] = by_ans
        result["panels"][pn] = res
        g = s["gain_percent_vs_baseline"]
        print(pn, len(ids), "complete" if complete else "INCOMPLETE",
              {m: (s["methods"][m]["completed"], None if s["methods"][m]["mean_cpu_seconds"] is None else round(s["methods"][m]["mean_cpu_seconds"], 3)) for m in methods},
              {m: (None if g.get(m) is None else round(g[m], 1)) for m in methods}, res.get("ci", {}).get("W_main_vs_D"))
    json.dump(result, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
