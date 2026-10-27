#!/usr/bin/env python3
"""Goal v11 S5 analysis (docs/BROAD_SCOPE_PROTOCOL_V11.md section 8): one frozen panel at a time.

  $FP_PY scripts/broad_scope_v11/validation.py --panel confirm|public|dev_deploy

Methods: D, Fp, Fm (fixed), SBS (the development SBS action's fixed record), W_main / W_struct / W_nc (frozen v11
wrappers that exist in FREEZE.json; a fixed main strategy uses the fixed record), W_v10 (original v10 wrapper and
frozen file). Complete means only when every instance of the panel is solved and verified within 3600 s; otherwise
null, with solved counts, a stratified bootstrap of the solved-count difference, paired gained / lost instances,
solves by time point and per-instance status. 3600 is never used as a completion time.
"""
import argparse
import collections
import glob
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devlib as L  # noqa: E402

CAP = L.CAP
TP = L.P["time_points"]
SEV = L.P["severe_misselection"]
V10_STRAT = "configs/cross_scale_v10/frozen/main.json"


def load(stages, ids, wrappers):
    recs = {}
    for stage in stages:
        for p in glob.glob(os.path.join(L.RUNS, stage, "*.json")):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            r = json.load(open(p))
            if r["instance"] not in ids or r.get("seed", 0):
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
        s = "policy_timeout"
    solved = s == "solved" and r["cpu"] <= CAP
    return {"status": s if solved or s != "solved" else "policy_timeout", "solved": solved, "cpu": r["cpu"],
            "answer": L.TAG.get(r.get("exit_code")) if solved else None, "path": r.get("path"),
            "action": r.get("action"), "pre_exec_cpu": r.get("pre_exec_cpu"), "probe_cpu": r.get("probe_cpu")}


def boot_solved(cells, xs, ys, n=10000, seed=0):
    """Stratified bootstrap of sum(x) - sum(y) for 0/1 solved indicators."""
    rng = random.Random(seed)
    by = collections.defaultdict(list)
    for k, c in enumerate(cells):
        by[c].append(k)
    vals = []
    for _ in range(n):
        d = 0
        for g in by.values():
            for _ in range(len(g)):
                k = g[rng.randrange(len(g))]
                d += xs[k] - ys[k]
        vals.append(d)
    vals.sort()
    return sum(xs) - sum(ys), vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def panel_stats(ids, cells, tab, methods, pairs):
    out = {"n": len(ids), "methods": {}}
    for m in methods:
        st = [tab[i][m] for i in ids]
        solved = sum(s["solved"] for s in st)
        complete = solved == len(ids)
        res_cost = [min(s["cpu"], CAP) if s["cpu"] is not None else CAP for s in st]
        out["methods"][m] = {
            "solved": solved, "complete": complete,
            "mean": sum(res_cost) / len(ids) if complete and ids else None,
            "total": sum(res_cost) if complete else None,
            "resource_total_capped": sum(res_cost),
            "statuses": dict(collections.Counter(s["status"] for s in st)),
            "solved_by_answer": dict(collections.Counter(s["answer"] for s in st if s["solved"])),
            "time_points": {str(t): sum(1 for s in st if s["solved"] and s["cpu"] <= t) for t in TP},
            "unsolved": [i for i in ids if not tab[i][m]["solved"]]}
    comps = {}
    for x, y in pairs:
        if x not in methods or y not in methods or not ids:
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
            worst = min(range(len(ids)), key=lambda k: ys[k] - xs[k])
            c.update(gain=pt, ci=[lo, hi], max_loss_s=-min(d), max_loss_instance=ids[worst],
                     share_top={k: (sum(pos[:k]) / sum(pos) if pos else None) for k in (1, 3, 10)},
                     net_gain_s=sum(ys) - sum(xs))
            if pos:
                top = max(range(len(ids)), key=lambda k: ys[k] - xs[k])
                rest = [k for k in range(len(ids)) if k != top]
                c["without_top_instance"] = {"instance": ids[top],
                                             "gain": 1 - sum(xs[k] for k in rest) / sum(ys[k] for k in rest)}
        else:
            sx = [1 if tab[i][x]["solved"] else 0 for i in ids]
            sy = [1 if tab[i][y]["solved"] else 0 for i in ids]
            d, lo, hi = boot_solved([cells[i] for i in ids], sx, sy)
            c["solved_difference"] = {"diff": d, "ci": [lo, hi]}
            both = [i for i in ids if tab[i][x]["solved"] and tab[i][y]["solved"]]
            if both:
                c["common_subset"] = {"n": len(both), "mean_x": sum(tab[i][x]["cpu"] for i in both) / len(both),
                                      "mean_y": sum(tab[i][y]["cpu"] for i in both) / len(both),
                                      "note": "selection-biased secondary description"}
        comps[f"{x}_vs_{y}"] = c
    out["comparisons"] = comps
    for w in methods:
        if not w.startswith("W_"):
            continue
        st = [tab[i][w] for i in ids]
        obs = sorted((s.get("pre_exec_cpu") if s.get("pre_exec_cpu") is not None else (s["cpu"] or 0.0)) for s in st)
        out.setdefault("wrappers", {})[w] = {
            "paths": dict(collections.Counter(s.get("path") for s in st)),
            "actions": dict(collections.Counter(s.get("action") for s in st)),
            "observation_cpu_mean": sum(obs) / len(obs) if obs else None,
            "observation_cpu_q": {q: obs[int(q * (len(obs) - 1))] for q in (0.5, 0.9, 0.99)} if obs else None}
    severe = {}
    for m in methods:
        n = 0
        for i in ids:
            best = [tab[i][a]["cpu"] for a in ("D", "Fp", "Fm") if tab[i][a]["solved"]]
            if not best:
                continue
            b = min(best)
            s = tab[i][m]
            if not s["solved"] or (s["cpu"] >= SEV["ratio"] * b and s["cpu"] - b >= SEV["min_seconds"]):
                n += 1
        severe[m] = n
    out["severe_misselection"] = severe
    return out


def d_bin(tab, i):
    s = tab[i]["D"]
    if not s["solved"]:
        return "timeout"
    return "<1s" if s["cpu"] < 1 else ("1-300s" if s["cpu"] <= 300 else ">300s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True, choices=["confirm", "public", "dev_deploy"])
    a = ap.parse_args()
    fr = json.load(open(os.path.join(L.CFG, "frozen", "FREEZE.json")))
    sbs = fr["dev_sbs"]
    names = {"main": "W_main", "structural": "W_struct", "nc": "W_nc"}
    wrappers = {f["path"]: names[n] for n, f in fr["files"].items() if n in names}
    wrappers[V10_STRAT] = "W_v10"
    fixed_main = None
    mainf = json.load(open(os.path.join(L.ROOT, fr["files"]["main"]["path"])))
    if mainf["kind"] == "fixed":
        fixed_main = mainf["action"]
        wrappers = {k: v for k, v in wrappers.items() if v != "W_main"}
    if a.panel == "public":
        man = json.load(open(os.path.join(L.RES, "public_formal_manifest.json")))["instances"]
        ids = [r["id"] for r in man]
        meta = {r["id"]: r for r in man}
        cells = {r["id"]: r["source"] for r in man}
        stages = ["public"]
    else:
        man = L.manifest_rows()
        role = "confirmation" if a.panel == "confirm" else "development"
        ids = sorted(i for i, r in man.items() if r["role"] == role)
        meta = man
        cells = {i: (man[i].get("block", "-"), man[i]["family"], man[i]["level"]) for i in ids}
        stages = ["confirm"] if a.panel == "confirm" else ["disc_dev", "deploy_dev"]
    recs = load(stages, set(ids), wrappers)
    wl = sorted({m for (_, m) in recs if m.startswith("W_")})  # wrappers deployed on this panel
    methods = ["D", "Fp", "Fm", "SBS"] + (["W_main"] if fixed_main else []) + wl
    tab = {}
    for i in ids:
        tab[i] = {m: status(recs.get((i, m))) for m in ("D", "Fp", "Fm")}
        tab[i]["SBS"] = tab[i][sbs]
        if fixed_main:
            tab[i]["W_main"] = tab[i][fixed_main]
        for w in wl:
            tab[i][w] = status(recs.get((i, w)))
    pairs = [("W_main", "SBS"), ("W_main", "W_struct"), ("W_main", "W_nc"), ("W_main", "W_v10"), ("W_struct", "SBS"),
             ("W_nc", "SBS"), ("W_v10", "SBS"), ("W_main", "D"), ("W_main", "Fp"), ("W_main", "Fm"),
             ("Fp", "D"), ("Fm", "D"), ("SBS", "D")]
    res = {"panel": a.panel, "stages": stages, "dev_sbs": sbs, "freeze": fr,
           "all": panel_stats(ids, cells, tab, methods, pairs)}
    allm = res["all"]["methods"]
    fixed_keys = {f: (allm[f]["solved"], allm[f]["resource_total_capped"]) for f in ("D", "Fp", "Fm")}
    res["posthoc_best_fixed"] = min(fixed_keys, key=lambda f: L.crit_key(fixed_keys[f]))
    pb = res["posthoc_best_fixed"]
    res["all"]["comparisons"].update(panel_stats(ids, cells, tab, methods, [("W_main", pb)])["comparisons"])
    groups = collections.defaultdict(list)
    for i in ids:
        if a.panel == "public":
            r = meta[i]
            groups["source:" + r["source"]].append(i)
            groups["kind:" + ("competition" if r["source"].startswith("comp") else "other")].append(i)
            groups["family_relation:" + ("unseen" if r["unseen_in_v11_training"] else "related:" + r["related_v11_family"])].append(i)
            groups["family_relation:" + ("unseen" if r["unseen_in_v11_training"] else "related")].append(i)
            groups["D_bin:" + d_bin(tab, i)].append(i)
        else:
            r = meta[i]
            if r.get("block"):
                groups["block:" + r["block"]].append(i)
            groups["family:" + r["family"]].append(i)
            groups["level:" + r["level"]].append(i)
            groups["cell:" + r["family"] + "|" + r["level"]].append(i)
    for g, gi in sorted(groups.items()):
        res.setdefault("groups", {})[g] = panel_stats(gi, cells, tab, methods, pairs + [("W_main", pb)])
    ans = collections.defaultdict(list)
    for i in ids:
        an = next((tab[i][m]["answer"] for m in methods if tab[i][m]["answer"]), "unknown")
        ans[an].append(i)
    res["by_answer_posthoc"] = {k: panel_stats(v, cells, tab, methods, pairs) for k, v in sorted(ans.items())}
    res["per_instance"] = tab
    out = os.path.join(L.RES, f"validation_{a.panel}.json")
    json.dump(res, open(out, "w"), indent=1, sort_keys=True, default=str)
    print(a.panel, {k: (v["solved"], round(v["mean"], 2) if v["mean"] is not None else None) for k, v in allm.items()},
          "posthoc best fixed", pb)
    for k, v in res["all"]["comparisons"].items():
        if "gain" in v:
            print(f"  {k}: {100 * v['gain']:+.1f}% [{100 * v['ci'][0]:+.1f}, {100 * v['ci'][1]:+.1f}] "
                  f"gained {len(v['gained'])} lost {len(v['lost'])}")
        else:
            sd = v["solved_difference"]
            print(f"  {k}: incomplete; solved diff {sd['diff']} [{sd['ci'][0]}, {sd['ci'][1]}]; "
                  f"gained {len(v['gained'])} lost {len(v['lost'])}")


if __name__ == "__main__":
    main()
