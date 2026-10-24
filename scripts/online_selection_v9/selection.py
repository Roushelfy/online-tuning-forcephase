#!/usr/bin/env python3
"""v9 S2: development data -> candidate costs, nested grouped CV, main-strategy rule and freeze
(docs/ONLINE_SELECTION_PROTOCOL_V9.md section 4). Standard library only; development data only.

  selection.py data                       -> results/online_selection_v9/dev_table.json (fixed times, probes, REF)
  selection.py cv [--freeze]              -> results/online_selection_v9/selection.json
                                             [+ configs/online_selection_v9/strategies/main.json]
Cost model: probe solved at tau -> q_i(tau) (wrapper process-tree CPU of the PROBE run); else
q_i(tau) + t_a(i) with t_a the complete fixed run of the chosen action (same command, from scratch).
"""

import argparse
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "online_selection_v9")
RES = os.path.join(ROOT, "results", "online_selection_v9")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "online_selection_v9")
P = json.load(open(os.path.join(CFG, "protocol.json")))
SEL = P["selection"]
sys.path.insert(0, HERE)
import presolve  # noqa: E402
TAUS = SEL["tau_grid"]
ACTS = ("D", "Fp", "Fm")
FULL = SEL["gate_features"]["scale"] + SEL["gate_features"]["content"]
SCALE = SEL["gate_features"]["scale"]


def records(stage):
    out = []
    for p in glob.glob(os.path.join(RUNS, stage, "*.json")):
        if not p.endswith(("progress.json", "effective_plan.json")):
            out.append(json.load(open(p)))
    return out


def ok(r):
    return r["status"] == "solved" and (r.get("verification") or {}).get("ok") is True


def data():
    split = json.load(open(os.path.join(CFG, "split.json")))
    dev = sorted(i for i, v in split.items() if v["split"] == "dev")
    tab = {i: {"type": split[i]["type"], "scale": split[i]["scale"], "role": split[i]["role"],
               "split_hash": split[i]["split_hash"], "t": {}, "t_status": {}, "probe": {}, "ref": None} for i in dev}
    for r in records("s1_dev"):
        if r["instance"] in tab:
            tab[r["instance"]]["t"][r["method"]] = r["cpu"]
            tab[r["instance"]]["t_status"][r["method"]] = r["status"] if r["status"] != "solved" or ok(r) else "unverified"
            if r["method"] == "D":
                tab[r["instance"]]["answer"] = {10: "SAT", 20: "UNSAT"}.get(r.get("exit_code"))
                tab[r["instance"]]["conflicts_D"] = (r.get("stats") or {}).get("conflicts")
    for r in records("p_dev"):
        if r["instance"] not in tab:
            continue
        d = r.get("decision") or {}
        solved = ok(r)
        tab[r["instance"]]["probe"][repr(float(r["tau"]))] = {
            "q": r["cpu"], "solved": solved, "status": r["status"], "probe_cpu": (d.get("probe") or {}).get("cpu"),
            "overshoot": (d.get("probe") or {}).get("overshoot"), "terminated_by": (d.get("probe") or {}).get("terminated_by"),
            "features": d.get("features")}
    for r in records("ref_dev"):
        if r["instance"] in tab:
            tab[r["instance"]]["ref"] = {"cpu": r["cpu"], "status": r["status"] if r["status"] != "solved" or ok(r) else "unverified",
                                         "path": r.get("path"), "action": r.get("action"), "probe_cpu": r.get("probe_cpu"),
                                         "pre_exec_cpu": r.get("pre_exec_cpu"), "formal_cpu": r.get("formal_cpu")}
    json.dump(tab, open(os.path.join(RES, "dev_table.json"), "w"), indent=1, sort_keys=True)
    import collections
    print(len(tab), collections.Counter(tuple(sorted(v["t_status"].items())) for v in tab.values()).most_common(3),
          sum(len(v["probe"]) for v in tab.values()), sum(v["ref"] is not None for v in tab.values()))


# ------------------------------------------------------------------ costs

def probe(row, tau):
    return row["probe"][repr(float(tau))]


def cost_after_probe(row, tau, action):
    p = probe(row, tau)
    return p["q"] if p["solved"] else p["q"] + row["t"][action]


def total(ids, tab, f):
    return sum(f(tab[i]) for i in ids)


# ------------------------------------------------------------------ folds

def folds(ids, tab, k):
    cells, out = {}, {}
    for i in ids:
        cells.setdefault((tab[i]["type"], tab[i]["scale"]), []).append(i)
    for c in cells.values():
        for r, i in enumerate(sorted(c, key=lambda i: tab[i]["split_hash"])):
            out[i] = r % k
    return out


# ------------------------------------------------------------------ readers

def unsolved(ids, tab, tau):
    return [i for i in ids if not probe(tab[i], tau)["solved"]]


def has_feats(row, tau, names):
    x = probe(row, tau)["features"]
    return x is not None and all(isinstance(x.get(f), (int, float)) and math.isfinite(x[f]) for f in names)


def const_action(ids, tab):
    return min(ACTS, key=lambda a: (sum(tab[i]["t"][a] for i in ids), ACTS.index(a))) if ids else "D"


def quantile(v, q):
    v = sorted(v)
    return v[int(round(q * (len(v) - 1)))]


def fit_tree(ids, tab, tau, names, margin, default):
    X = {i: probe(tab[i], tau)["features"] for i in ids}
    T = {i: tab[i]["t"] for i in ids}
    cands = sorted({(f, quantile([X[i][f] for i in ids], q)) for f in names for q in SEL["tree"]["threshold_quantiles"]},
                   key=lambda c: (names.index(c[0]), c[1]))

    def leaf(S):
        if not S:
            return 0.0, {"leaf": default}
        sums = {a: sum(T[i][a] for i in S) for a in ACTS}
        best = min(ACTS, key=lambda a: (sums[a], ACTS.index(a)))
        a = best if (best == default or (len(S) >= SEL["tree"]["min_leaf"] and sums[default] - sums[best] > margin)) else default
        return sums[a], {"leaf": a}

    def best(S, depth):
        c, node = leaf(S)
        out = (c, 0, node)
        if depth == 0:
            return out
        for f, thr in cands:
            L = [i for i in S if X[i][f] <= thr]
            R = [i for i in S if X[i][f] > thr]
            if len(L) < SEL["tree"]["min_leaf"] or len(R) < SEL["tree"]["min_leaf"]:
                continue
            cl, nl, tl = best(L, depth - 1)
            cr, nr, tr = best(R, depth - 1)
            if (cl + cr, 1 + nl + nr) < out[:2]:
                out = (cl + cr, 1 + nl + nr, {"feature": f, "threshold": thr, "left": tl, "right": tr})
        return out
    return {"method": "tree", "tree": best(ids, SEL["tree"]["max_depth"])[2], "margin": margin}


def solve(A, b):
    n = len(A)
    M = [row[:] + [b[k]] for k, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[k][n] / M[k][k] if abs(M[k][k]) > 1e-12 else 0.0 for k in range(n)]


def fit_ridge(ids, tab, tau, names, alpha, margin):
    X = {i: probe(tab[i], tau)["features"] for i in ids}
    mean = {f: sum(X[i][f] for i in ids) / len(ids) for f in names}
    std = {}
    for f in names:
        v = sum((X[i][f] - mean[f]) ** 2 for i in ids) / len(ids)
        std[f] = v ** 0.5 if v > 1e-18 else 1.0
    Z = [[1.0] + [(X[i][f] - mean[f]) / std[f] for f in names] for i in ids]
    k = len(names) + 1
    A = [[sum(z[r] * z[c] for z in Z) + (alpha if r == c and r > 0 else 0.0) for c in range(k)] for r in range(k)]
    models = {}
    for a in ("Fp", "Fm"):
        y = [tab[i]["t"][a] - tab[i]["t"]["D"] for i in ids]
        w = solve(A, [sum(z[r] * yy for z, yy in zip(Z, y)) for r in range(k)])
        models[a] = {"intercept": w[0], "coef": dict(zip(names, w[1:]))}
    return {"method": "ridge", "mean": mean, "std": std, "models": models, "margin": margin}


def read(reader, x):
    return presolve.decide_gate(reader, x)  # the deployment decision code


def gate_strategy(train, tab, tau, names, hp):
    un = unsolved(train, tab, tau)
    default = const_action(un, tab)
    fit_ids = [i for i in un if has_feats(tab[i], tau, names)]
    if len(fit_ids) < 2 * SEL["tree"]["min_leaf"]:
        reader = {"method": "tree", "tree": {"leaf": default}, "margin": hp["margin"]}
    elif hp["reader"] == "tree":
        reader = fit_tree(fit_ids, tab, tau, names, hp["margin"], default)
    else:
        reader = fit_ridge(fit_ids, tab, tau, names, hp["alpha"], hp["margin"])
    return {"kind": "gate", "tau": tau, "features": names, "missing_action": default, "reader": reader}


def apply(strat, row):
    """CPU of a strategy on one development row (cost model)."""
    if strat["kind"] == "fixed":
        return row["t"][strat["action"]]
    tau = strat["tau"]
    p = probe(row, tau)
    if p["solved"]:
        return p["q"]
    if strat["kind"] == "presolve":
        a = strat["fallback"]
    else:
        a = read(strat["reader"], p["features"]) if has_feats(row, tau, strat["features"]) else strat["missing_action"]
    return p["q"] + row["t"][a]


def action_of(strat, row):
    if strat["kind"] == "fixed":
        return strat["action"]
    p = probe(row, strat["tau"])
    if p["solved"]:
        return "probe"
    if strat["kind"] == "presolve":
        return strat["fallback"]
    return read(strat["reader"], p["features"]) if has_feats(row, strat["tau"], strat["features"]) else strat["missing_action"]


# ------------------------------------------------------------------ families

def family_candidates(fam, train, tab):
    if fam == "SBS":
        return [{"kind": "fixed", "action": const_action(train, tab)}]
    if fam == "A":
        return [{"kind": "presolve", "tau": t, "fallback": a} for t in TAUS for a in SEL["fallbacks"]]
    names = FULL if fam == "B" else SCALE
    hps = [{"reader": "tree", "margin": m} for m in SEL["tree"]["margin_seconds"]] + \
          [{"reader": "ridge", "alpha": al, "margin": m} for al in SEL["ridge"]["alpha"] for m in SEL["ridge"]["margin_seconds"]]
    return [("gate", t, names, hp) for t in TAUS for hp in hps]


def realize(cand, train, tab):
    if isinstance(cand, dict):
        return cand
    _, tau, names, hp = cand
    s = gate_strategy(train, tab, tau, names, hp)
    s["hyper"] = hp
    return s


def select(fam, ids, tab, k):
    """Inner CV over the family's candidates on ids; returns (best realized-on-ids strategy, its CV total)."""
    if fam == "SBS":
        return realize(family_candidates(fam, ids, tab)[0], ids, tab), None
    fo = folds(ids, tab, k)
    best = None
    for cand in family_candidates(fam, ids, tab):
        tot = 0.0
        if isinstance(cand, dict):  # A: nothing to fit
            tot = total(ids, tab, lambda r: apply(cand, r))
        else:
            for f in sorted(set(fo.values())):
                tr = [i for i in ids if fo[i] != f]
                te = [i for i in ids if fo[i] == f]
                s = realize(cand, tr, tab)
                tot += total(te, tab, lambda r: apply(s, r))
        if best is None or tot < best[0] - 1e-9:
            best = (tot, cand)
    return realize(best[1], ids, tab), best[0]


def nested(fam, ids, tab):
    fo = folds(ids, tab, SEL["outer_folds"])
    per, chosen = {}, {}
    for f in sorted(set(fo.values())):
        tr = [i for i in ids if fo[i] != f]
        te = [i for i in ids if fo[i] == f]
        s, _ = select(fam, tr, tab, SEL["inner_folds"])
        chosen[f] = {k: v for k, v in s.items() if k != "reader"} | ({"reader_method": s["reader"]["method"]} if "reader" in s else {})
        for i in te:
            per[i] = {"cost": apply(s, tab[i]), "action": action_of(s, tab[i])}
    return {"cv_total": sum(v["cost"] for v in per.values()), "per_instance": per, "chosen_by_fold": chosen}


def cv(freeze):
    tab = json.load(open(os.path.join(RES, "dev_table.json")))
    ids = sorted(i for i, v in tab.items() if v["role"] == "main")
    ctl = sorted(i for i, v in tab.items() if v["role"] == "control")
    bad = [i for i in ids + ctl if any(tab[i]["t_status"].get(a) != "solved" for a in ACTS)
           or len(tab[i]["probe"]) != len(TAUS)]
    if bad:
        raise SystemExit(f"incomplete development data: {bad[:10]} ({len(bad)})")
    out = {"n_dev": len(ids), "n_controls": len(ctl)}
    out["fixed_totals"] = {a: sum(tab[i]["t"][a] for i in ids) for a in ACTS}
    out["oracle_total"] = sum(min(tab[i]["t"][a] for a in ACTS) for i in ids)
    out["SBS_in_sample"] = const_action(ids, tab)
    out["A_in_sample"] = {f"P({t},{a})": total(ids, tab, lambda r: apply({"kind": "presolve", "tau": t, "fallback": a}, r))
                          for t in TAUS for a in SEL["fallbacks"]}
    res = {}
    for fam in ("SBS", "A", "B", "B_s"):
        res[fam] = nested(fam, ids, tab)
        print(fam, round(res[fam]["cv_total"], 1), flush=True)
    out["cv"] = res
    a, b, sbs = res["A"]["cv_total"], res["B"]["cv_total"], res["SBS"]["cv_total"]
    main = "B" if b < a * 0.99 else ("A" if a < sbs * 0.99 else "SBS")
    out["main_family"] = main
    strat, inner = select(main, ids, tab, SEL["inner_folds"])
    strat["name"] = f"v9_main_{main}"
    strat["family"] = main
    strat["inner_cv_total_all_dev"] = inner
    strat["in_sample_total"] = total(ids, tab, lambda r: apply(strat, r))
    out["main_strategy"] = strat
    out["controls_in_sample"] = {"D": sum(tab[i]["t"]["D"] for i in ctl), "main": total(ctl, tab, lambda r: apply(strat, r))}
    json.dump(out, open(os.path.join(RES, "selection.json"), "w"), indent=1)
    if freeze:
        json.dump(strat, open(os.path.join(CFG, "strategies", "main.json"), "w"), indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in out.items() if k not in ("cv", "main_strategy")}, indent=1))
    print("main", main, {k: v for k, v in strat.items() if k != "reader"})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data")
    c = sub.add_parser("cv")
    c.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    data() if a.cmd == "data" else cv(a.freeze)


if __name__ == "__main__":
    main()
