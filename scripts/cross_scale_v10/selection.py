#!/usr/bin/env python3
"""Goal v10 S3/S4 (docs/CROSS_SCALE_PROTOCOL_V10.md sections 6-7): offline simulation of every registered family
on the development set, nested grouped CV, family comparisons, leave-one-level-out and proxy diagnostics, the
main-strategy rule and the freeze. Development data only.

  $FP_PY scripts/cross_scale_v10/selection.py cv        -> results/cross_scale_v10/selection.json
  $FP_PY scripts/cross_scale_v10/selection.py freeze    -> configs/cross_scale_v10/frozen/{main,reference}.json, FREEZE.json
"""
import argparse
import collections
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402
import devlib as L  # noqa: E402

FAMS = ["SBS", "A", "A_s", "N_B", "B_v9", "B", "N_C", "C", "REF"]
CAND = L.P["main_candidates"]
CONTROL = L.P["matched_control"]
MARGIN = L.P["replace_margin"]


def summarize(rows, oof):
    ids = sorted(oof)
    k = L.agg([(oof[i][0], oof[i][1]) for i in ids])
    obs = [oof[i][2] for i in ids]
    paths = collections.Counter(oof[i][4] for i in ids)
    acts = collections.Counter(oof[i][3] for i in ids)
    return {"solved": k[0], "total": k[1], "n": len(ids), "mean_obs_cpu": sum(obs) / len(ids),
            "complete_mean": k[1] / len(ids) if k[0] == len(ids) else None, "paths": dict(paths), "actions": dict(acts),
            "probe_solved": paths.get("probe_solved", 0)}


def compare(rows, oof_a, oof_b):
    ids = sorted(oof_a)
    cells = [L.cell(rows[i]) for i in ids]
    x = [oof_a[i][1] for i in ids]
    y = [oof_b[i][1] for i in ids]
    pt, lo, hi = L.strat_boot(cells, x, y)
    sa = sum(1 for i in ids if oof_a[i][0])
    sb = sum(1 for i in ids if oof_b[i][0])
    return {"gain": pt, "ci": [lo, hi], "solved": [sa, sb],
            "gained": [i for i in ids if oof_a[i][0] and not oof_b[i][0]],
            "lost": [i for i in ids if oof_b[i][0] and not oof_a[i][0]]}


def main_rule(summ):
    trace = []
    inc = "SBS"
    for f in L.P["complexity_order"][1:]:
        kf = (summ[f]["solved"], summ[f]["total"])
        ki = (summ[inc]["solved"], summ[inc]["total"])
        beats = L.better(kf, ki, MARGIN)
        note = {"family": f, "vs": inc, "beats_incumbent": beats}
        if f in CONTROL:
            c = CONTROL[f]
            kc = (summ[c]["solved"], summ[c]["total"])
            note["beats_matched_control"] = L.better(kf, kc, MARGIN)
            beats = beats and note["beats_matched_control"]
        if beats:
            inc = f
        note["incumbent_after"] = inc
        trace.append(note)
    return inc, trace


def decomposition(rows, oof, sbs_oof):
    """Gain vs SBS split into instances answered by a probe and instances decided after the probes."""
    out = {"probe_solved": 0.0, "selected": 0.0}
    for i in oof:
        d = sbs_oof[i][1] - oof[i][1]
        out["probe_solved" if oof[i][4] == "probe_solved" else "selected"] += d
    return out


def proxy_audit(rows, oof):
    """Share of reader decisions equal to the majority decision of their type x level cell."""
    by = collections.defaultdict(list)
    for i, v in oof.items():
        if v[4] == "reader":
            by[L.cell(rows[i])].append(v[3])
    agree = sum(collections.Counter(v).most_common(1)[0][1] for v in by.values())
    n = sum(len(v) for v in by.values())
    return {"reader_decisions": n, "cell_majority_share": agree / n if n else None,
            "cells": {f"{c[0]}-{c[1]}": dict(collections.Counter(v)) for c, v in sorted(by.items())}}


def leave_one_level(sim):
    rows = sim.rows
    out = {}
    for lv in ("S", "M", "L"):
        train = [i for i in rows if rows[i]["level"] != lv]
        test = [i for i in rows if rows[i]["level"] == lv]
        res = {}
        for fam in ("SBS", "A", "N_B", "B", "N_C", "C"):
            cfg, strat, got = L.run_family(sim, fam, train, test)
            k = L.agg([(v[0], v[1]) for v in got.values()])
            res[fam] = {"solved": k[0], "total": k[1], "config": L.describe(cfg, strat)}
        out[lv] = res
    return out


def coverage(rows):
    """Probe answer / search-start rates and static analyser status on the development set."""
    out = {"static": dict(collections.Counter(r["m"]["static"]["status"] for r in rows.values())),
           "static_cpu_max": max(r["m"]["static"]["cpu"] for r in rows.values()), "probes": {}}
    keys = sorted({k for r in rows.values() for k in r["m"]["probes"]})
    for arm, tau in keys:
        ps = [r["m"]["probes"][(arm, tau)] for r in rows.values()]
        out["probes"][f"{arm}@{tau}"] = {
            "answered": sum(p["exit"] in (10, 20) for p in ps),
            "started_unanswered": sum(p["exit"] not in (10, 20) and p["started"] for p in ps),
            "not_started": sum(p["exit"] not in (10, 20) and not p["started"] for p in ps),
            "cpu_mean": sum(p["cpu"] for p in ps) / len(ps), "overshoot_max": max(p["overshoot"] for p in ps),
            "wrapper_cpu_mean": sum(p["wc"] for p in ps) / len(ps)}
    out["wrapper_start_cpu_mean"] = sum(r["m"]["start"] for r in rows.values()) / len(rows)
    return out


def cv():
    t0 = time.time()
    rows = L.dev_table()
    missing = [i for i, r in rows.items() if "m" not in r or any(a not in r["t"] for a in L.ACTS)]
    if missing:
        raise SystemExit(f"{len(missing)} dev instances without complete s1_dev / measure_dev records: {missing[:5]}")
    sim = L.Sim(rows)
    res = {"n": len(rows), "families": {}, "oof": {}, "chosen": {}}
    oofs = {}
    for fam in FAMS:
        oof, chosen = L.outer_cv(sim, fam)
        oofs[fam] = oof
        res["families"][fam] = summarize(rows, oof)
        res["chosen"][fam] = chosen
        res["oof"][fam] = {i: list(v) for i, v in sorted(oof.items())}
        print(f"[cv] {fam}: solved {res['families'][fam]['solved']} total {res['families'][fam]['total']:.1f} "
              f"({time.time() - t0:.0f} s)", flush=True)
    for a in L.ACTS:
        got = {i: (*L.outcome(rows[i], None, a), 0.0, a, "fixed") for i in rows}
        oofs["fixed_" + a] = got
        res["families"]["fixed_" + a] = summarize(rows, got)
    orc = {}
    for i, r in rows.items():
        best = min(L.ACTS, key=lambda a: (not L.outcome(r, None, a)[0], L.outcome(r, None, a)[1]))
        orc[i] = (*L.outcome(r, None, best), 0.0, best, "oracle")
    res["families"]["oracle"] = summarize(rows, orc)
    pairs = [("A", "SBS"), ("N_B", "SBS"), ("B", "A"), ("B", "N_B"), ("B", "B_v9"), ("N_C", "N_B"), ("C", "B"),
             ("C", "N_C"), ("C", "SBS"), ("REF", "SBS"), ("A_s", "A")]
    pairs += [(f, "fixed_D") for f in ("SBS", "A", "N_B", "B", "N_C", "C", "REF")]
    res["comparisons"] = {f"{a}_vs_{b}": compare(rows, oofs[a], oofs[b]) for a, b in pairs}
    res["decomposition_vs_SBS"] = {f: decomposition(rows, oofs[f], oofs["SBS"]) for f in ("N_B", "B", "N_C", "C", "REF")}
    res["proxy_audit"] = {f: proxy_audit(rows, oofs[f]) for f in ("A", "A_s", "B", "B_v9", "C")}
    main, trace = main_rule(res["families"])
    res["main_rule"] = {"main": main, "trace": trace, "margin": MARGIN}
    res["leave_one_level"] = leave_one_level(sim)
    res["coverage"] = coverage(rows)
    res["elapsed_s"] = time.time() - t0
    json.dump(res, open(os.path.join(L.RES, "selection.json"), "w"), indent=1, sort_keys=True)
    print("[cv] main =", main, json.dumps(trace))


def to_deploy(cfg, strat, name, note):
    s = dict(strat)
    s["name"] = name
    s["note"] = note
    if s["kind"] == "observe":
        s["probes"] = [{"arm": a, "tau": float(t)} for a, t in cfg["probes"]]
        s["static"] = bool(cfg["static"]) and bool(s.get("reader") and s["reader"].get("method") not in (None, "none"))
        if not s.get("reader") or s["reader"].get("method") == "none":
            s["reader"] = None
            s["features"], s["needs_arms"] = [], []
    return s


def freeze():
    sel = json.load(open(os.path.join(L.RES, "selection.json")))
    main = sel["main_rule"]["main"]
    rows = L.dev_table()
    sim = L.Sim(rows)
    ids = sorted(rows)
    ci, inner = L.select_config(sim, main, ids)
    cfg = L.family_configs(main)[ci]
    strat = sim.fit(cfg, ids)
    out_dir = os.path.join(L.CFG, "frozen")
    os.makedirs(out_dir, exist_ok=True)
    m = to_deploy(cfg, strat, f"v10_main_{main}", f"family {main}, config index {ci}, fitted on all 270 dev instances")
    ref = None
    if main in ("A", "B", "C") and main in CONTROL and CONTROL[main] != "SBS":
        cfam = CONTROL[main]
        fb = L.best_fixed(rows, sim.prs(cfg), [i for i in ids if not sim.prs(cfg)[i].answered])
        ccfg = {"static": False, "probes": cfg["probes"], "fallback": fb}
        ref = to_deploy(ccfg, sim.fit(ccfg, ids), f"v10_control_{cfam}",
                        f"matched content-free control of the main strategy ({cfam}): same probes, fallback chosen on all dev")
    else:
        rcfg = L.family_configs("REF")[0]
        same = (m["kind"] == "observe" and not m.get("reader") and m["probes"] == [{"arm": "D", "tau": 2.0}]
                and m["base"] == "Fp")
        if not same:
            ref = to_deploy(rcfg, sim.fit(rcfg, ids), "v10_ref_D2_Fp", "fixed reference D 2 s -> F+ (protocol 6.3)")
    paths = {}
    if m["kind"] == "fixed":
        paths["main_action"] = m["action"]
    for name, s in (("main", m), ("reference", ref)):
        if s is None or s["kind"] == "fixed":
            continue
        p = os.path.join(out_dir, f"{name}.json")
        json.dump(s, open(p, "w"), indent=1, sort_keys=True)
        paths[f"{name}_wrapper"] = os.path.relpath(p, L.ROOT)
    sbs = sel["families"]["SBS"]
    dev_sbs = min(L.ACTS, key=lambda a: (L.crit_key(L.agg([L.outcome(rows[i], None, a) for i in ids])), L.ACTS.index(a)))
    fr = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "main_family": main, "main_config_index": ci,
          "dev_sbs": dev_sbs, "oof_sbs": {"solved": sbs["solved"], "total": sbs["total"]},
          "main_rule_trace": sel["main_rule"]["trace"], **paths,
          "sha256": {k: hashlib.sha256(open(os.path.join(L.ROOT, v), "rb").read()).hexdigest()
                     for k, v in paths.items() if k.endswith("_wrapper")},
          "code_sha256": {f: hashlib.sha256(open(os.path.join(HERE, f), "rb").read()).hexdigest()
                          for f in ("common.py", "wrapper.py", "runner.py", "devlib.py", "selection.py")}}
    json.dump(fr, open(os.path.join(out_dir, "FREEZE.json"), "w"), indent=1, sort_keys=True)
    print(json.dumps(fr, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cv", "freeze"])
    a = ap.parse_args()
    cv() if a.cmd == "cv" else freeze()


if __name__ == "__main__":
    main()
