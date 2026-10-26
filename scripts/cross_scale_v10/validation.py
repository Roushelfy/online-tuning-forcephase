#!/usr/bin/env python3
"""Goal v10 S5 analysis (docs/CROSS_SCALE_PROTOCOL_V10.md section 8): one frozen panel at a time.

  $FP_PY scripts/cross_scale_v10/validation.py --panel confirm|extrapolation|external|dev_deploy

Methods: D, Fp, Fm (fixed), SBS (= the development SBS action's fixed record), W_main / W_ref (frozen wrappers).
Complete means only when every instance of the fixed panel is solved and verified within 3600 s; otherwise null,
with solved counts, paired gained / lost instances, solves by the preset time points and the per-instance status.
"""
import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devlib as L  # noqa: E402

CAP = L.CAP
TP = L.P["time_points"]


def load(stage, ids, wrappers):
    recs = {}
    for p in glob.glob(os.path.join(L.RUNS, stage, "*.json")):
        if p.endswith(("progress.json", "effective_plan.json")):
            continue
        r = json.load(open(p))
        if r["instance"] not in ids or r.get("seed", 0) or r.get("variant"):
            continue
        m = r["method"] if r["method"] != "W" else wrappers.get(r.get("strategy"))
        if m:
            recs[(r["instance"], m)] = r
    return recs


def status(r):
    if r is None:
        return {"status": "missing", "solved": False, "cpu": None}
    s = r["status"] if r["status"] != "solved" or L.ok(r) else "unverified"
    if s == "error" and L.run_timeout_policy.is_timeout(r["cpu"], r["key"], r.get("exit_code")):
        s = "policy_timeout"  # kernel SIGXCPU at the cap recorded as 'error' before the classifier fix (protocol 12)
    solved = s == "solved" and r["cpu"] <= CAP
    return {"status": s if solved or s != "solved" else "policy_timeout", "solved": solved, "cpu": r["cpu"],
            "answer": L.TAG.get(r.get("exit_code")) if solved else None, "path": r.get("path"),
            "action": r.get("action"), "pre_exec_cpu": r.get("pre_exec_cpu"), "probe_cpu": r.get("probe_cpu")}


def panel_stats(ids, cells, tab, methods, sbs, main, control):
    out = {"n": len(ids), "methods": {}}
    for m in methods:
        st = [tab[i][m] for i in ids]
        solved = sum(s["solved"] for s in st)
        complete = solved == len(ids)
        res_cost = [min(s["cpu"], CAP) if s["cpu"] is not None else CAP for s in st]
        out["methods"][m] = {
            "solved": solved, "complete": complete,
            "mean": sum(res_cost) / len(ids) if complete else None,
            "total": sum(res_cost) if complete else None,
            "resource_total_capped": sum(res_cost),
            "statuses": dict(collections.Counter(s["status"] for s in st)),
            "solved_by_answer": dict(collections.Counter(s["answer"] for s in st if s["solved"])),
            "time_points": {str(t): sum(1 for s in st if s["solved"] and s["cpu"] <= t) for t in TP},
            "unsolved": [i for i in ids if not tab[i][m]["solved"]]}
    comps = {}
    pairs = [(x, y) for x in ("Fp", "Fm", "SBS", "W_main", "W_ref") for y in ("D",)]
    pairs += [("W_main", "SBS"), ("W_ref", "SBS"), ("W_main", "W_ref"), ("W_main", "Fp"), ("W_main", "Fm"), ("W_ref", "Fp")]
    for x, y in pairs:
        if x not in methods or y not in methods:
            continue
        a, b = out["methods"][x], out["methods"][y]
        c = {"gained": [i for i in ids if tab[i][x]["solved"] and not tab[i][y]["solved"]],
             "lost": [i for i in ids if tab[i][y]["solved"] and not tab[i][x]["solved"]]}
        if a["complete"] and b["complete"]:
            xs = [tab[i][x]["cpu"] for i in ids]
            ys = [tab[i][y]["cpu"] for i in ids]
            pt, lo, hi = L.strat_boot([cells[i] for i in ids], xs, ys)
            d = sorted((ys[k] - xs[k] for k in range(len(ids))), reverse=True)
            pos = [v for v in d if v > 0]
            c.update(gain=pt, ci=[lo, hi], max_loss_s=-min(d), max_loss_instance=ids[min(range(len(ids)), key=lambda k: ys[k] - xs[k])],
                     share_top={k: (sum(pos[:k]) / sum(pos) if pos else None) for k in (1, 3, 10)})
        else:
            common = [i for i in ids if tab[i][x]["solved"] and tab[i][y]["solved"]]
            if common:
                c["common_subset"] = {"n": len(common), "mean_x": sum(tab[i][x]["cpu"] for i in common) / len(common),
                                      "mean_y": sum(tab[i][y]["cpu"] for i in common) / len(common),
                                      "note": "selection-biased secondary description"}
        comps[f"{x}_vs_{y}"] = c
    out["comparisons"] = comps
    for w in ("W_main", "W_ref"):
        if w in methods:
            st = [tab[i][w] for i in ids]
            obs = sorted((s["pre_exec_cpu"] if s["pre_exec_cpu"] is not None else (s["cpu"] or 0.0)) for s in st)
            out.setdefault("wrappers", {})[w] = {
                "paths": dict(collections.Counter(s["path"] for s in st)),
                "actions": dict(collections.Counter(s["action"] for s in st)),
                "observation_cpu_mean": sum(obs) / len(obs),
                "observation_cpu_q": {q: obs[int(q * (len(obs) - 1))] for q in (0.5, 0.9, 0.99)}}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True, choices=["confirm", "extrapolation", "external", "dev_deploy"])
    a = ap.parse_args()
    fr = json.load(open(os.path.join(L.CFG, "frozen", "FREEZE.json")))
    sbs = fr["dev_sbs"]
    wrappers = {}
    if fr.get("main_wrapper"):
        wrappers[fr["main_wrapper"]] = "W_main"
    if fr.get("reference_wrapper"):
        wrappers[fr["reference_wrapper"]] = "W_ref"
    split = json.load(open(os.path.join(L.CFG, "split.json")))
    if a.panel == "external":
        man = json.load(open(os.path.join(L.RES, "external_manifest.json")))["instances"]
        ids = [r["id"] for r in man]
        cells = {r["id"]: r["family"] for r in man}
        stage = "external"
    else:
        part = {"confirm": "confirm", "extrapolation": "extrapolation", "dev_deploy": "dev"}[a.panel]
        ids = sorted(i for i, v in split.items() if v["split"] == part)
        cells = {i: (split[i]["type"], split[i]["level"]) for i in ids}
        stage = {"confirm": "confirm", "extrapolation": "extrap", "dev_deploy": "s1_dev"}[a.panel]
    recs = load(stage, set(ids), wrappers)
    if a.panel == "dev_deploy":
        recs.update(load("deploy_dev", set(ids), wrappers))
    methods = ["D", "Fp", "Fm", "SBS"] + sorted(set(wrappers.values()))
    if fr.get("main_action"):
        methods.append("W_main")  # fixed main strategy: its record is the fixed action's
    tab = {}
    for i in ids:
        tab[i] = {m: status(recs.get((i, m))) for m in ("D", "Fp", "Fm")}
        tab[i]["SBS"] = tab[i][sbs]
        for w in set(wrappers.values()):
            tab[i][w] = status(recs.get((i, w)))
        if fr.get("main_action"):
            tab[i]["W_main"] = tab[i][fr["main_action"]]
    res = {"panel": a.panel, "stage": stage, "dev_sbs": sbs, "freeze": fr, "all": panel_stats(ids, cells, tab, methods, sbs, None, None)}
    groups = collections.defaultdict(list)
    for i in ids:
        groups[("cell:" + "-".join(cells[i])) if isinstance(cells[i], tuple) else ("family:" + cells[i])].append(i)
        if a.panel == "confirm":
            groups["block:" + split[i]["block"]].append(i)
            groups["type:" + split[i]["type"]].append(i)
            groups["level:" + split[i]["level"]].append(i)
    for g, gi in sorted(groups.items()):
        res.setdefault("groups", {})[g] = panel_stats(gi, cells, tab, methods, sbs, None, None)
    ans = collections.defaultdict(list)
    for i in ids:
        an = next((tab[i][m]["answer"] for m in ("D", "Fp", "Fm") if tab[i][m]["answer"]), "unknown")
        ans[an].append(i)
    res["by_answer_posthoc"] = {k: panel_stats(v, cells, tab, methods, sbs, None, None) for k, v in sorted(ans.items())}
    res["per_instance"] = tab
    out = os.path.join(L.RES, f"validation_{a.panel}.json")
    json.dump(res, open(out, "w"), indent=1, sort_keys=True, default=str)
    m = res["all"]["methods"]
    print(a.panel, {k: (v["solved"], round(v["mean"], 2) if v["mean"] is not None else None) for k, v in m.items()})
    for k, v in res["all"]["comparisons"].items():
        if "gain" in v:
            print(f"  {k}: {100 * v['gain']:+.1f}% [{100 * v['ci'][0]:+.1f}, {100 * v['ci'][1]:+.1f}] "
                  f"gained {len(v['gained'])} lost {len(v['lost'])}")
        else:
            print(f"  {k}: incomplete; gained {len(v['gained'])} lost {len(v['lost'])}")


if __name__ == "__main__":
    main()
