#!/usr/bin/env python3
"""Goal v11 S3 baselines (docs/BROAD_SCOPE_PROTOCOL_V11.md section 7.1) on the training pool and the encoding /
sign / seed diagnostics (section 6). Training data only.

  $FP_PY scripts/broad_scope_v11/baselines.py   -> results/broad_scope_v11/baselines.json

Per family x level (and per panel, per answer, per encoding variant): completion and complete-mean status of
D / F+ / F-, clear advantages (>= 20 % and >= 1 s, or solved vs timeout), largest losses, oracle (exact where
every instance has a verified answer; otherwise lower bound), concentration of the SBS -> oracle space, and the
within-type vs between-type decomposition (family-best fixed action vs SBS vs oracle). SAT / UNSAT only posthoc.
"""
import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devlib as L  # noqa: E402

ACTS = L.ACTS
CA = L.P["clear_advantage"]
CAP = L.CAP


def clear(row, a, b):
    """True if a is clearly better than b on this instance (provable from verified answers / timeouts)."""
    oa, ob = row["ok"].get(a), row["ok"].get(b)
    if oa and not ob:
        return True
    if oa and ob:
        ta, tb = row["t"][a], row["t"][b]
        return tb >= CA["ratio"] * ta and tb - ta >= CA["min_seconds"]
    return False


def oracle_row(row):
    sol = [row["t"][a] for a in ACTS if row["ok"].get(a)]
    return (True, min(sol)) if sol else (False, CAP)


def block(rows, ids):
    out = {"n": len(ids), "modes": {}, "clear": {}, "answers": dict(collections.Counter(rows[i]["answer"] for i in ids))}
    for a in ACTS:
        sol = [i for i in ids if rows[i]["ok"].get(a)]
        tot = sum(rows[i]["t"][a] for i in ids)
        out["modes"][a] = {"solved": len(sol), "total_actual_cpu": tot,
                           "complete_mean": tot / len(ids) if len(sol) == len(ids) else None,
                           "median_solved_cpu": statistics.median([rows[i]["t"][a] for i in sol]) if sol else None,
                           "statuses": dict(collections.Counter(rows[i]["status"].get(a) for i in ids))}
    for a in ACTS:
        for b in ACTS:
            if a != b:
                out["clear"][f"{a}>{b}"] = sum(1 for i in ids if clear(rows[i], a, b))
    orc = [oracle_row(rows[i]) for i in ids]
    out["oracle"] = {"solved": sum(1 for s, _ in orc if s), "total": sum(c for _, c in orc),
                     "exact": all(s for s, _ in orc),
                     "mean": sum(c for _, c in orc) / len(ids) if all(s for s, _ in orc) else None,
                     "mean_lower_bound": sum(c for _, c in orc) / len(ids)}
    sbs = L.best_fixed(rows, None, ids) if ids else None
    out["best_fixed"] = sbs
    if ids:
        losses = []
        for a in ACTS:
            for i in ids:
                o_s, o_c = oracle_row(rows[i])
                if not o_s:
                    continue
                c = rows[i]["t"][a] if rows[i]["ok"].get(a) else None
                losses.append({"id": i, "mode": a, "oracle": o_c, "cpu": c, "timeout": c is None,
                               "loss": (c - o_c) if c is not None else None})
        worst = {}
        for a in ACTS:
            la = [x for x in losses if x["mode"] == a]
            to = [x for x in la if x["timeout"]]
            fin = sorted((x for x in la if not x["timeout"]), key=lambda x: -x["loss"])
            worst[a] = {"timeouts_where_another_mode_solved": [x["id"] for x in to],
                        "largest_losses": [{k: x[k] for k in ("id", "cpu", "oracle", "loss")} for x in fin[:3]]}
        out["worst"] = worst
        gains = sorted(((rows[i]["t"][sbs] if rows[i]["ok"].get(sbs) else CAP) - oracle_row(rows[i])[1], i) for i in ids)
        gains.reverse()
        tot = sum(g for g, _ in gains)
        out["sbs_to_oracle"] = {"total_gap": tot, "top1_share": gains[0][0] / tot if tot > 0 else None,
                                "top5_share": sum(g for g, _ in gains[:5]) / tot if tot > 0 else None,
                                "top1": gains[0][1]}
    return out


def decomposition(rows, ids, key):
    """SBS vs best fixed action per group (posthoc, in-sample) vs oracle -- how much of the oracle space a fixed
    per-group flag captures."""
    sbs = L.best_fixed(rows, None, ids)
    groups = collections.defaultdict(list)
    for i in ids:
        groups[key(rows[i])].append(i)
    gact = {g: L.best_fixed(rows, None, v) for g, v in groups.items()}

    def tot(choose):
        o = [L.outcome(rows[i], None, choose(i)) for i in ids]
        return sum(1 for s, _ in o if s), sum(c for _, c in o)
    s_sbs = tot(lambda i: sbs)
    s_grp = tot(lambda i: gact[key(rows[i])])
    orc = [oracle_row(rows[i]) for i in ids]
    s_orc = (sum(1 for s, _ in orc if s), sum(c for _, c in orc))
    space = s_sbs[1] - s_orc[1]
    return {"sbs": sbs, "group_actions": {"|".join(g) if isinstance(g, tuple) else g: a for g, a in gact.items()},
            "sbs_key": s_sbs, "group_key": s_grp, "oracle_key": s_orc,
            "captured_fraction_of_cpu_space": (s_sbs[1] - s_grp[1]) / space if space > 0 else None}


def family_equal_weight(rows, ids, a, b):
    """Mean over families of the per-family relative CPU reduction of a vs b (instance totals, actual CPU)."""
    fams = sorted({rows[i]["family"] for i in ids})
    vals = {}
    for f in fams:
        fi = [i for i in ids if rows[i]["family"] == f]
        ta, tb = sum(rows[i]["t"][a] for i in fi), sum(rows[i]["t"][b] for i in fi)
        vals[f] = 1 - ta / tb if tb > 0 else None
    v = [x for x in vals.values() if x is not None]
    return {"per_family": vals, "mean": sum(v) / len(v) if v else None}


def variant_table(stage, ids, seed=0):
    return L.fixed_table(ids, [stage], seed=seed)


def fastest(row):
    sol = [(row["t"][a], a) for a in ACTS if row["ok"].get(a)]
    return min(sol)[1] if sol else None


def clear_class(row):
    """'D' / 'Fp' / 'Fm' if that mode is clearly better than both others, 'Fpm' if both forced modes are clearly
    better than D, 'D>F' if D clearly beats both forced modes, else 'none'."""
    for a in ACTS:
        if all(clear(row, a, b) for b in ACTS if b != a):
            return a
    if clear(row, "Fp", "D") and clear(row, "Fm", "D"):
        return "Fpm"
    if clear(row, "D", "Fp") and clear(row, "D", "Fm"):
        return "D>F"
    return "none"


SWAP = {"D": "D", "Fp": "Fm", "Fm": "Fp", "Fpm": "Fpm", "D>F": "D>F", "none": "none", None: None}


def diagnostics(rows):
    var = json.load(open(os.path.join(L.RES, "variants_manifest.json")))["instances"]
    vt = variant_table("encoding", [v["id"] for v in var])
    out = {"variants": {}, "seeds": {}}
    for v in var:
        b, r = rows[v["base"]], vt[v["id"]]
        if set(r["t"]) != set(ACTS):
            continue
        fb, fv = fastest(b), fastest(r)
        cb, cv = clear_class(b), clear_class(r)
        out["variants"][v["id"]] = {
            "base": v["base"], "op": v["op"], "family": b["family"], "level": b["level"],
            "answer_base": b["answer"], "answer_variant": r["answer"],
            "answer_consistent": b["answer"] is None or r["answer"] is None or b["answer"] == r["answer"],
            "fastest_base": fb, "fastest_variant": fv, "clear_base": cb, "clear_variant": cv,
            "t_base": b["t"], "ok_base": b["ok"], "t_variant": r["t"], "ok_variant": r["ok"]}
    seed_ids = json.load(open(os.path.join(L.CFG, "variants_gen.json")))["seed_repeat_base"]
    for s in (1, 2):
        st = L.fixed_table(seed_ids, ["seeds"], seed=s)
        for i in seed_ids:
            r = st[i]
            if set(r["t"]) != set(ACTS):
                continue
            out["seeds"].setdefault(i, {"family": rows[i]["family"], "level": rows[i]["level"], "seed0": {
                "fastest": fastest(rows[i]), "clear": clear_class(rows[i]), "t": rows[i]["t"], "ok": rows[i]["ok"]}})
            out["seeds"][i][f"seed{s}"] = {"fastest": fastest(r), "clear": clear_class(r), "t": r["t"], "ok": r["ok"]}
    summ = collections.defaultdict(lambda: collections.Counter())
    for v in out["variants"].values():
        op = v["op"].split(":")[0] if v["op"].startswith("enc") else v["op"]
        k = summ[(op, v["family"])]
        k["n"] += 1
        k["fastest_same"] += v["fastest_base"] == v["fastest_variant"]
        k["clear_same"] += v["clear_base"] == v["clear_variant"]
        if op == "flipall":
            k["fastest_same_after_swap"] += SWAP[v["fastest_base"]] == v["fastest_variant"]
            k["clear_same_after_swap"] += SWAP[v["clear_base"]] == v["clear_variant"]
        k["answer_inconsistent"] += not v["answer_consistent"]
    for i, v in out["seeds"].items():
        for s in (1, 2):
            if f"seed{s}" in v:
                k = summ[(f"seed{s}", v["family"])]
                k["n"] += 1
                k["fastest_same"] += v["seed0"]["fastest"] == v[f"seed{s}"]["fastest"]
                k["clear_same"] += v["seed0"]["clear"] == v[f"seed{s}"]["clear"]
    out["summary"] = {f"{op}|{fam}": dict(c) for (op, fam), c in sorted(summ.items())}
    return out


def main():
    rows = L.pool_table()
    ids = sorted(rows)
    fams = sorted({r["family"] for r in rows.values()})
    out = {"n": len(ids), "pool": block(rows, ids), "families": {}, "cells": {}, "panels": {}, "answers": {}}
    for f in fams:
        out["families"][f] = block(rows, [i for i in ids if rows[i]["family"] == f])
        for lv in ("S", "M", "L"):
            out["cells"][f"{f}|{lv}"] = block(rows, [i for i in ids if rows[i]["family"] == f and rows[i]["level"] == lv])
    for p in ("discovery", "development"):
        out["panels"][p] = block(rows, [i for i in ids if rows[i]["role"] == p])
    for ans in ("SAT", "UNSAT", None):
        out["answers"][str(ans)] = block(rows, [i for i in ids if rows[i]["answer"] == ans])
    out["decomposition"] = {"by_family": decomposition(rows, ids, lambda r: r["family"]),
                            "by_cell": decomposition(rows, ids, L.cell),
                            "by_level": decomposition(rows, ids, lambda r: r["level"])}
    sbs = out["pool"]["best_fixed"]
    out["weighting"] = {f"{a}_vs_{sbs}": {"family_equal": family_equal_weight(rows, ids, a, sbs),
                                          "instance_total": 1 - sum(rows[i]["t"][a] for i in ids) / sum(rows[i]["t"][sbs] for i in ids)}
                        for a in ACTS if a != sbs}
    out["time_points"] = {a: {str(t): sum(1 for i in ids if rows[i]["ok"].get(a) and rows[i]["t"][a] <= t)
                              for t in L.P["time_points"]} for a in ACTS}
    if os.path.exists(os.path.join(L.RES, "variants_manifest.json")):
        out["diagnostics"] = diagnostics(rows)
    json.dump(out, open(os.path.join(L.RES, "baselines.json"), "w"), indent=1, default=str)
    print("pool", {a: (v["solved"], round(v["total_actual_cpu"], 1)) for a, v in out["pool"]["modes"].items()},
          "SBS", sbs, "oracle", out["pool"]["oracle"]["solved"], round(out["pool"]["oracle"]["total"], 1))
    for f, b in out["families"].items():
        print(f, {a: (v["solved"], round(v["total_actual_cpu"], 1)) for a, v in b["modes"].items()}, "best", b["best_fixed"],
              "answers", b["answers"])
    print("captured by family flag:", out["decomposition"]["by_family"]["captured_fraction_of_cpu_space"])


if __name__ == "__main__":
    main()
