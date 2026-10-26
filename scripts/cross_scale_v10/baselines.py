#!/usr/bin/env python3
"""Goal v10 S2 (docs/CROSS_SCALE_PROTOCOL_V10.md section 5): selection space and misselection cost on the new
development set (s1_dev), the robustness diagnostic (robust_dev) and -- labelled historical re-evaluation under the
3600 s view -- the exposed v9 dev / holdout / extrapolation panels.

  $FP_PY scripts/cross_scale_v10/baselines.py      -> results/cross_scale_v10/baselines.json, reports/cross_scale_v10/BASELINES.md
"""
import collections
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devlib as L  # noqa: E402

ROOT, CFG, RES = L.ROOT, L.CFG, L.RES
ACTS, CAP = L.ACTS, L.CAP
NAME = {"D": "D", "Fp": "F+", "Fm": "F−"}
CA = L.P["clear_advantage"]


def solved(row, a):
    return bool(row["ok"].get(a)) and row["t"][a] <= CAP


def cost(row, a):
    return row["t"][a] if solved(row, a) else min(row["t"].get(a, CAP), CAP)


def clear(row, a, b):
    """'a' / 'b' if one is clearly faster (>= 20% and >= 1 s, a proven bound when the slower one timed out), else
    'close' or 'unknown'."""
    sa, sb = solved(row, a), solved(row, b)
    if not sa and not sb:
        return "unknown"
    ta = row["t"][a] if sa else max(row["t"].get(a, CAP), CAP)
    tb = row["t"][b] if sb else max(row["t"].get(b, CAP), CAP)
    for x, tx, y, ty, sx in ((a, ta, b, tb, sa), (b, tb, a, ta, sb)):
        if sx and ty - tx >= CA["absolute_seconds"] and tx <= (1 - CA["relative"]) * ty:
            return x
    if sa and sb:
        return "close"
    return "unknown"  # the unfinished side's bound is not large enough to prove a clear advantage


def oracle(row):
    done = [cost(row, a) for a in ACTS if solved(row, a)]
    if len(done) == len(ACTS) or (done and min(done) <= min(cost(row, a) for a in ACTS if not solved(row, a))):
        return min(done) if done else None
    return None


def summarize(rows, ids, sbs=None):
    out = {"n": len(ids)}
    keys = {a: L.agg([(solved(rows[i], a), cost(rows[i], a)) for i in ids]) for a in ACTS}
    out["solved"] = {a: keys[a][0] for a in ACTS}
    out["resource_total"] = {a: keys[a][1] for a in ACTS}
    out["complete_mean"] = {a: (keys[a][1] / len(ids) if keys[a][0] == len(ids) else None) for a in ACTS}
    sbs = sbs or min(ACTS, key=lambda a: (L.crit_key(keys[a]), ACTS.index(a)))
    out["sbs"] = sbs
    orc = [oracle(rows[i]) for i in ids]
    out["oracle_mean"] = sum(orc) / len(ids) if all(o is not None for o in orc) else None
    out["oracle_known"] = sum(o is not None for o in orc)
    out["answers"] = dict(collections.Counter(rows[i]["answer"] or "unknown" for i in ids))
    fastest = collections.Counter()
    for i in ids:
        r = rows[i]
        if all(solved(r, a) for a in ACTS):
            fastest[min(ACTS, key=lambda a: r["t"][a])] += 1
        else:
            fastest["not all solved"] += 1
    out["fastest"] = dict(fastest)
    cls = {f"{a}_vs_{b}": dict(collections.Counter(clear(rows[i], a, b) for i in ids))
           for a, b in (("Fp", "D"), ("Fm", "D"), ("Fp", "Fm"))}
    out["clear_advantage"] = cls
    # per-instance loss of SBS vs D and of each forced mode vs D (only where both solved; unknown otherwise)
    loss = {}
    for a in ("Fp", "Fm"):
        d = [(cost(rows[i], a) - cost(rows[i], "D"), i) for i in ids if solved(rows[i], a) and solved(rows[i], "D")]
        lost = [i for i in ids if solved(rows[i], "D") and not solved(rows[i], a)]
        gained = [i for i in ids if solved(rows[i], a) and not solved(rows[i], "D")]
        pos = sorted((-x for x, _ in d if x < 0), reverse=True)
        tot = sum(pos)
        loss[a] = {"max_loss_s": max((x for x, _ in d), default=None),
                   "max_loss_instance": max(d)[1] if d else None,
                   "slower_count": sum(1 for x, _ in d if x > 0), "faster_count": sum(1 for x, _ in d if x < 0),
                   "lost_to_timeout": lost, "gained_from_timeout": gained,
                   "gain_share_top": {k: (sum(pos[:k]) / tot if tot else None) for k in (1, 3, 10)}}
    out["vs_D"] = loss
    if out["oracle_mean"] is not None and keys[sbs][0] == len(ids):
        g = sorted((cost(rows[i], sbs) - oracle(rows[i]) for i in ids), reverse=True)
        tot = sum(g)
        out["oracle_vs_sbs"] = {"saving_s": tot, "share_top": {k: (sum(g[:k]) / tot if tot else None) for k in (1, 3, 10)}}
    return out


def by_cell(rows, ids):
    cells = collections.defaultdict(list)
    for i in ids:
        cells[(rows[i]["type"], rows[i]["level"])].append(i)
    return cells


def robust(dev):
    split = json.load(open(os.path.join(CFG, "split.json")))
    ids = [l.strip() for l in open(os.path.join(CFG, "panel_robust.txt")) if l.strip() and not l.startswith("#")]
    cond = {"seed0": {i: dev[i] for i in ids},
            "seed1": L.fixed_table(ids, "robust_dev", split, seed=1),
            "perm1": L.fixed_table(ids, "robust_dev", split, seed=0, variant="perm1")}
    out = {"n": len(ids), "conditions": {}}
    for c, rows in cond.items():
        complete = [i for i in ids if all(a in rows[i]["t"] for a in ACTS)]
        out["conditions"][c] = {"records_complete": len(complete),
                                "solved": {a: sum(solved(rows[i], a) for i in complete) for a in ACTS},
                                "total": {a: sum(cost(rows[i], a) for i in complete) for a in ACTS}}
    base = cond["seed0"]
    for c in ("seed1", "perm1"):
        rows = cond[c]
        same, n, cls_same, cls_n, sev_same, sev_n = 0, 0, 0, 0, 0, 0
        for i in ids:
            if not all(a in rows[i]["t"] for a in ACTS):
                continue
            if all(solved(base[i], a) and solved(rows[i], a) for a in ACTS):
                n += 1
                same += min(ACTS, key=lambda a: base[i]["t"][a]) == min(ACTS, key=lambda a: rows[i]["t"][a])
            for a, b in (("Fp", "D"), ("Fm", "D")):
                k0, k1 = clear(base[i], a, b), clear(rows[i], a, b)
                if k0 in (a, b):
                    cls_n += 1
                    cls_same += k1 == k0
            k0, k1 = clear(base[i], "Fp", "D"), clear(rows[i], "Fp", "D")
            if k0 == "D":  # severe F+ loss (the v9 SBS) in seed 0
                sev_n += 1
                sev_same += k1 == "D"
        out[c] = {"fastest_same": same, "fastest_n": n, "clear_same": cls_same, "clear_n": cls_n,
                  "severe_Fp_loss_kept": sev_same, "severe_Fp_loss_n": sev_n}
    return out


def v9_historical():
    """Exposed v9 panels in the 3600 s view (historical re-evaluation, protocol section 5)."""
    V9 = os.path.join(L.DATA, "runs", "online_selection_v9")
    split = json.load(open(os.path.join(ROOT, "configs", "online_selection_v9", "split.json")))
    stops = {x["id"] for x in json.load(open(os.path.join(ROOT, "results", "policy_stops.json")))["stops"]}
    panels = {"v9_dev": ("s1_dev", [i for i, v in split.items() if v["split"] == "dev" and v.get("role") == "main"]),
              "v9_holdout": ("holdout", [i for i, v in split.items() if v["split"] == "holdout" and v.get("role") == "main"])}
    ext = [l.split()[0] for l in open(os.path.join(ROOT, "configs", "online_selection_v9", "panel_extrapolation.txt"))
           if l.strip() and not l.startswith("#")]
    panels["v9_extrapolation"] = ("extrap", ext)
    out = {}
    for name, (stage, ids) in panels.items():
        rows = {i: {"t": {}, "ok": {}, "answer": None} for i in ids}
        for p in glob.glob(os.path.join(V9, stage, "*.json")):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            r = json.load(open(p))
            if r["instance"] not in rows or r["method"] not in ACTS or r.get("seed", 0) or r.get("rep", 0):
                continue
            rows[r["instance"]]["t"][r["method"]] = r["cpu"]
            rows[r["instance"]]["ok"][r["method"]] = L.ok(r) and r["id"] not in stops
            if L.ok(r):
                rows[r["instance"]]["answer"] = L.TAG.get(r.get("exit_code"))
        for i in ids:
            v = split.get(i) or {}
            rows[i]["type"] = v.get("type") or i.split("-")[1]
            rows[i]["level"] = v.get("scale") or i.split("-")[2]
        out[name] = {"all": summarize(rows, ids, sbs="Fp"),
                     "cells": {f"{t}-{l}": summarize(rows, c, sbs="Fp") for (t, l), c in sorted(by_cell(rows, ids).items())}}
    return out


def fmt(x, nd=2):
    return "—" if x is None else (f"{x:,.{nd}f}" if isinstance(x, float) else str(x))


def main():
    dev = L.fixed_table(sorted(i for i, v in json.load(open(os.path.join(CFG, "split.json"))).items()
                               if v["split"] == "dev"), "s1_dev", json.load(open(os.path.join(CFG, "split.json"))))
    ids = sorted(dev)
    res = {"dev": {"all": summarize(dev, ids)}}
    sbs = res["dev"]["all"]["sbs"]
    res["dev"]["cells"] = {f"{t}-{l}": summarize(dev, c, sbs=sbs) for (t, l), c in sorted(by_cell(dev, ids).items())}
    res["dev"]["sbs_cell_losses"] = {}
    res["robust"] = robust(dev)
    res["v9_historical"] = v9_historical()
    os.makedirs(RES, exist_ok=True)
    json.dump(res, open(os.path.join(RES, "baselines.json"), "w"), indent=1, sort_keys=True)
    print(json.dumps({k: res["dev"]["all"][k] for k in ("solved", "complete_mean", "sbs", "oracle_mean")}, indent=1))


if __name__ == "__main__":
    main()
