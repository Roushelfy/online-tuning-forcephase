"""Goal v11 development library (docs/BROAD_SCOPE_PROTOCOL_V11.md section 7, configs/broad_scope_v11/protocol.json).
Training pool table from the disc_dev and measure_pool records, offline simulation (v10 code: observation cost from the
MEASURE record + the chosen action's fixed run), the v11 method families (SBS, ST static tree, TR type router, PR
prefix reader, NC matched control, V10 historical), nested grouped CV and bootstrap. numpy (analysis venv).

Decisions on held-out instances go through common.decide (scripts/broad_scope_v11/common.py) -- the code the
deployed wrapper runs.
"""
import glob
import hashlib
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import common  # noqa: E402  (v11 common: v10 definitions + out-of-range rule)
sys.path.insert(0, os.path.dirname(HERE))
import run_timeout_policy  # noqa: E402

_spec = importlib.util.spec_from_file_location("devlib_v10", os.path.join(ROOT, "scripts", "cross_scale_v10", "devlib.py"))
L10 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L10)

CFG = os.path.join(ROOT, "configs", "broad_scope_v11")
RES = os.path.join(ROOT, "results", "broad_scope_v11")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "broad_scope_v11")
P = json.load(open(os.path.join(CFG, "protocol.json")))
ACTS = common.ACTS
CAP = float(P["per_run_cpu_seconds"])
TAG = {10: "SAT", 20: "UNSAT"}
STATIC = list(common.STATIC)
FAM_P = P["families"]

pre, outcome, agg, better, crit_key = L10.pre, L10.outcome, L10.agg, L10.better, L10.crit_key
strat_boot = L10.strat_boot


# ------------------------------------------------------------------ data

def records(stage):
    out = []
    for p in glob.glob(os.path.join(RUNS, stage, "*.json")):
        if not p.endswith(("progress.json", "effective_plan.json")):
            out.append(json.load(open(p)))
    return out


def ok(r):
    return r["status"] == "solved" and (r.get("verification") or {}).get("ok") is True and r["cpu"] <= CAP


def fixed_table(ids, stages, seed=0):
    """{id: {t: {a: cpu}, ok: {a: bool}, status: {a: status}, answer}} from the fixed runs of the given stages."""
    tab = {i: {"t": {}, "ok": {}, "status": {}, "answer": None} for i in ids}
    for st in ([stages] if isinstance(stages, str) else stages):
        for r in records(st):
            if r["instance"] not in tab or r["method"] not in ACTS or r.get("seed", 0) != seed:
                continue
            row = tab[r["instance"]]
            row["t"][r["method"]] = r["cpu"]
            row["ok"][r["method"]] = ok(r)
            s = r["status"]
            if s == "error" and run_timeout_policy.is_timeout(r["cpu"], r["key"], r.get("exit_code")):
                s = "policy_timeout"
            row["status"][r["method"]] = s if s != "solved" or ok(r) else "unverified"
            if ok(r):
                row["answer"] = TAG.get(r.get("exit_code"))
    return tab


def manifest_rows(names=("formal_manifest.json",)):
    out = {}
    for n in names:
        for r in json.load(open(os.path.join(RES, n)))["instances"]:
            out[r["id"]] = r
    return out


def fold_rank(i):
    return hashlib.sha256((i + ":v11fold").encode()).hexdigest()


def assign_folds(rows):
    by = {}
    for i, r in rows.items():
        by.setdefault((r["family"], r["level"]), []).append(i)
    for c in by.values():
        for k, i in enumerate(sorted(c, key=fold_rank)):
            rows[i]["fold"] = k % P["outer_folds"]
            rows[i]["rank"] = k


def add_measure(tab, stage):
    for r in records(stage):
        if r["instance"] not in tab or r["status"] != "measured":
            continue
        d = r["decision"]
        m = {"start": d["own_cpu_at_start"], "tree_cpu": r["cpu"],
             "static": {"cpu": d["static"]["cpu"], "wc": d["static"]["wrapper_cpu"], "status": d["static"]["status"],
                        "features": d["static"]["features"]},
             "probes": {}}
        for p in d["probes"]:
            m["probes"][(p["arm"], float(p["tau"]))] = {
                "cpu": p["cpu"], "wc": p["wrapper_cpu"], "exit": p["exit_code"], "overshoot": p["overshoot"],
                "features": p.get("features"), "v9": p.get("v9_features"), "started": p.get("started", False),
                "terminated_by": p.get("terminated_by")}
        tab[r["instance"]]["m"] = m


def pool_table():
    man = manifest_rows()
    ids = sorted(i for i, r in man.items() if r["role"] in ("discovery", "development"))
    tab = fixed_table(ids, ["disc_dev"])
    for i in ids:
        tab[i].update(family=man[i]["family"], level=man[i]["level"], role=man[i]["role"], size=man[i]["size"])
    assign_folds(tab)
    add_measure(tab, "measure_pool")
    return tab


def cell(row):
    return (row["family"], row["level"])


# ------------------------------------------------------------------ fixed-action helpers

def best_fixed(rows, prs, ids):
    keys = {a: agg([outcome(rows[i], prs[i] if prs else None, a) for i in ids]) for a in ACTS}
    return min(ACTS, key=lambda a: (crit_key(keys[a]), ACTS.index(a)))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def static_matrix(prs, ids, impute):
    return np.array([[prs[i].x[f] if _num(prs[i].x.get(f)) else impute[f] for f in STATIC] for i in ids], float)


def medians(prs, ids, feats):
    out = {}
    for f in feats:
        v = [prs[i].x.get(f) for i in ids if _num(prs[i].x.get(f))]
        out[f] = float(np.median(v)) if v else 0.0
    return out


def thresholds(X, qs):
    return [sorted({float(np.quantile(X[:, j], q, method="nearest")) for q in qs}) for j in range(X.shape[1])]


# ------------------------------------------------------------------ ST: cost-sensitive static tree

def fit_static_tree(rows, prs, train, depth, theta):
    cfg = FAM_P["ST"]
    base = best_fixed(rows, prs, train)
    impute = medians(prs, train, STATIC)
    X = static_matrix(prs, train, impute)
    outs = {a: [outcome(rows[i], prs[i], a) for i in train] for a in ACTS}
    solved = np.array([[1.0 if outs[a][k][0] else 0.0 for a in ACTS] for k in range(len(train))])
    cost = np.array([[outs[a][k][1] for a in ACTS] for k in range(len(train))])
    bi = ACTS.index(base)
    thr = thresholds(X, cfg["threshold_quantiles"])
    ml = cfg["min_leaf"]

    def leaf(mask):
        s, c = solved[mask].sum(0), cost[mask].sum(0)
        a = bi
        for k in range(len(ACTS)):
            if k == bi or s[k] < s[bi]:
                continue
            if c[k] <= (1.0 - theta) * c[bi] and (s[k], -c[k]) > (s[a], -c[a]):
                a = k
        return (s[a], c[a]), {"leaf": ACTS[a], "n": int(mask.sum())}

    def grow(mask, d):
        key, node = leaf(mask)
        if d == 0 or mask.sum() < 2 * ml:
            return key, node
        best = None
        for j, f in enumerate(STATIC):
            for t in thr[j]:
                lm, rm = mask & (X[:, j] <= t), mask & ~(X[:, j] <= t)
                if lm.sum() < ml or rm.sum() < ml:
                    continue
                kl, _ = leaf(lm)
                kr, _ = leaf(rm)
                k2 = (kl[0] + kr[0], kl[1] + kr[1])
                if best is None or (-k2[0], k2[1]) < (-best[0][0], best[0][1]):
                    best = (k2, j, f, t, lm, rm)
        if best is None or not ((-best[0][0], best[0][1]) < (-key[0], key[1] - 1e-9)):
            return key, node
        _, j, f, t, lm, rm = best
        kl, nl = grow(lm, d - 1)
        kr, nr = grow(rm, d - 1)
        return (kl[0] + kr[0], kl[1] + kr[1]), {"feature": f, "threshold": t, "left": nl, "right": nr}

    _, tree = grow(np.ones(len(train), bool), depth)
    return {"kind": "observe", "static": True, "probes": [], "features": STATIC, "impute": impute, "base": base,
            "missing_action": base, "needs_arms": [],
            "reader": {"method": "tree", "depth": depth, "theta_fraction": theta, "tree": tree}}


# ------------------------------------------------------------------ TR: type router

def gini(counts):
    n = sum(counts.values())
    return 0.0 if n == 0 else 1.0 - sum((c / n) ** 2 for c in counts.values())


def fit_type_router(rows, prs, train, depth):
    cfg = FAM_P["TR"]
    sbs = best_fixed(rows, prs, train)
    fams = sorted({rows[i]["family"] for i in train})
    fam_act = {f: best_fixed(rows, prs, [i for i in train if rows[i]["family"] == f]) for f in fams}
    impute = medians(prs, train, STATIC)
    X = static_matrix(prs, train, impute)
    y = [rows[i]["family"] for i in train]
    thr = thresholds(X, cfg["threshold_quantiles"])
    ml = cfg["min_leaf"]

    def counts(mask):
        c = {}
        for k in np.flatnonzero(mask):
            c[y[k]] = c.get(y[k], 0) + 1
        return c

    def leaf(mask):
        c = counts(mask)
        maj = max(sorted(c), key=lambda f: c[f])
        pur = c[maj] / sum(c.values())
        act = fam_act[maj] if pur >= cfg["purity_min"] else sbs
        return {"leaf": act, "family": maj, "purity": pur, "n": int(mask.sum())}

    def grow(mask, d):
        c = counts(mask)
        if d == 0 or mask.sum() < 2 * ml or len(c) == 1:
            return leaf(mask)
        g0, n = gini(c), mask.sum()
        best = None
        for j, f in enumerate(STATIC):
            for t in thr[j]:
                lm, rm = mask & (X[:, j] <= t), mask & ~(X[:, j] <= t)
                if lm.sum() < ml or rm.sum() < ml:
                    continue
                g = (lm.sum() * gini(counts(lm)) + rm.sum() * gini(counts(rm))) / n
                if best is None or g < best[0] - 1e-12:
                    best = (g, f, t, lm, rm)
        if best is None or best[0] >= g0 - 1e-12:
            return leaf(mask)
        _, f, t, lm, rm = best
        return {"feature": f, "threshold": t, "left": grow(lm, d - 1), "right": grow(rm, d - 1)}

    tree = grow(np.ones(len(train), bool), depth)
    lo, hi = {}, {}
    for j, f in enumerate(STATIC):
        vals = [prs[i].x.get(f) for i in train if _num(prs[i].x.get(f))]
        a, b = (min(vals), max(vals)) if vals else (0.0, 0.0)
        w = cfg["range_expand_fraction"] * (b - a)
        lo[f], hi[f] = a - w, b + w
    return {"kind": "observe", "static": True, "probes": [], "features": STATIC, "impute": impute, "base": sbs,
            "missing_action": sbs, "needs_arms": [], "family_actions": fam_act,
            "ood": {"lo": lo, "hi": hi, "action": sbs},
            "reader": {"method": "tree", "depth": depth, "classifier": "family", "tree": tree}}


# ------------------------------------------------------------------ configurations

def family_configs(fam):
    if fam == "SBS":
        return [{"fixed": None}]
    if fam == "V10":
        return [{"static": True, "probes": [("D", 2.0)], "frozen": "configs/cross_scale_v10/frozen/main.json"}]
    if fam == "ST":
        c = FAM_P["ST"]
        return [{"static": True, "probes": [], "st": (d, th)} for th in sorted(c["theta_fraction"], reverse=True)
                for d in c["depth"]]
    if fam == "TR":
        return [{"static": True, "probes": [], "tr": d} for d in FAM_P["TR"]["depth"]]
    if fam == "PR":
        return [{"static": True, "probes": [("D", t)], "features": common.feature_set("B"), "needs": ["D"],
                 "reader": tuple(r)} for t in FAM_P["PR"]["taus"] for r in FAM_P["PR"]["readers"]]
    if fam == "NC":
        return [{"static": False, "probes": [("D", t)], "nc": True} for t in FAM_P["PR"]["taus"]]
    raise ValueError(fam)


class Sim:
    """Caches the observation part of each schedule per instance."""

    def __init__(self, rows):
        self.rows = rows
        self._pre = {}

    def prs(self, cfg):
        if "fixed" in cfg:
            return {i: None for i in self.rows}
        key = (cfg["static"], tuple(cfg["probes"]))
        if key not in self._pre:
            self._pre[key] = {i: pre(r, cfg["static"], cfg["probes"]) for i, r in self.rows.items()}
        return self._pre[key]

    def fit(self, cfg, train):
        prs = self.prs(cfg)
        if "fixed" in cfg:
            return {"kind": "fixed", "action": best_fixed(self.rows, None, train)}
        if "frozen" in cfg:
            s = json.load(open(os.path.join(ROOT, cfg["frozen"])))
            return s
        if "st" in cfg:
            return fit_static_tree(self.rows, prs, train, *cfg["st"])
        if "tr" in cfg:
            return fit_type_router(self.rows, prs, train, cfg["tr"])
        if cfg.get("nc"):
            U = [i for i in train if not prs[i].answered]
            base = best_fixed(self.rows, prs, U) if U else "Fm"
            return {"kind": "observe", "static": False, "probes": cfg["probes"], "reader": None, "base": base,
                    "missing_action": base, "features": [], "needs_arms": []}
        meth, par, th = cfg["reader"]
        s = L10.fit_reader(self.rows, prs, train, cfg["features"], cfg["needs"], meth, par, th)
        s.update(kind="observe", static=cfg["static"], probes=cfg["probes"])
        return s

    def apply(self, cfg, strat, ids):
        """{id: (solved, cost, obs_cost, action, path)}."""
        prs = self.prs(cfg)
        out = {}
        for i in ids:
            row = self.rows[i]
            if strat["kind"] == "fixed":
                s, c = outcome(row, None, strat["action"])
                out[i] = (s, c, 0.0, strat["action"], "fixed")
                continue
            pr = prs[i]
            if pr.answered:
                s, c = outcome(row, pr, None)
                out[i] = (s, c, pr.cost, pr.answer_arm + "_probe", "probe_solved")
                continue
            a, path = common.decide(strat, pr.x, pr.started)
            s, c = outcome(row, pr, a)
            out[i] = (s, c, pr.cost, a, path)
        return out


def inner_folds(rows, ids, k):
    by = {}
    for i in ids:
        by.setdefault(cell(rows[i]), []).append(i)
    f = {}
    for c in by.values():
        for r, i in enumerate(sorted(c, key=fold_rank)):
            f[i] = r % k
    return f


def select_config(sim, fam, train, margin=0.01):
    cfgs = family_configs(fam)
    if len(cfgs) == 1:
        return 0, []
    k = P["inner_folds"]
    f = inner_folds(sim.rows, train, k)
    res = []
    for ci, cfg in enumerate(cfgs):
        outs, obs = [], []
        for q in range(k):
            tr = [i for i in train if f[i] != q]
            te = [i for i in train if f[i] == q]
            got = sim.apply(cfg, sim.fit(cfg, tr), te)
            outs += [(v[0], v[1]) for v in got.values()]
            obs += [v[2] for v in got.values()]
        res.append((agg(outs), float(np.mean(obs)) if obs else 0.0, ci))
    best = min(res, key=lambda r: (crit_key(r[0]), r[2]))
    tied = [r for r in res if r[0][0] == best[0][0] and r[0][1] <= (1 + margin) * best[0][1]]
    pick = min(tied, key=lambda r: (round(r[1], 6), r[2]))
    return pick[2], res


def run_family(sim, fam, train, test, pr_cfg=None):
    """Fit the family on train (inner CV for its grid) and apply to test. NC follows PR's tau (pr_cfg)."""
    if fam == "NC":
        tau = pr_cfg["probes"][0][1]
        cfg = {"static": False, "probes": [("D", tau)], "nc": True}
    else:
        ci, _ = select_config(sim, fam, train)
        cfg = family_configs(fam)[ci]
    strat = sim.fit(cfg, train)
    return cfg, strat, sim.apply(cfg, strat, test)


def cv(sim, fam, folds, pr_cfgs=None):
    """folds: {id: fold label}. Returns oof results, per-fold configs."""
    oof, chosen = {}, {}
    for k in sorted(set(folds.values())):
        train = [i for i in sim.rows if folds[i] != k]
        test = [i for i in sim.rows if folds[i] == k]
        cfg, strat, got = run_family(sim, fam, train, test, (pr_cfgs or {}).get(k))
        oof.update(got)
        chosen[k] = {"cfg": cfg, "strategy": strat}
    return oof, chosen


def summarize(oof):
    ids = sorted(oof)
    k = agg([(oof[i][0], oof[i][1]) for i in ids])
    paths, acts = {}, {}
    for i in ids:
        paths[oof[i][4]] = paths.get(oof[i][4], 0) + 1
        acts[oof[i][3]] = acts.get(oof[i][3], 0) + 1
    return {"solved": k[0], "total": k[1], "n": len(ids), "mean_obs_cpu": float(np.mean([oof[i][2] for i in ids])),
            "complete_mean": k[1] / len(ids) if k[0] == len(ids) else None, "paths": paths, "actions": acts}


def jsonable(cfg):
    return {k: (list(map(list, v)) if k == "probes" else (list(v) if isinstance(v, tuple) else v)) for k, v in cfg.items()}
