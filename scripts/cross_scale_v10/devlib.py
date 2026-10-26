"""Goal v10 development library (docs/CROSS_SCALE_PROTOCOL_V10.md sections 5-7): dev table from the s1_dev and
measure_dev records, the offline cost simulation (section 6.4), the two readers (7.1), nested grouped CV (7.2),
the selection criterion (7.3) and paired cell-stratified bootstrap. numpy (analysis venv).

Decisions on held-out instances go through common.decide -- the code the deployed wrapper runs.
"""
import glob
import itertools
import json
import math
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import common  # noqa: E402

CFG = os.path.join(ROOT, "configs", "cross_scale_v10")
RES = os.path.join(ROOT, "results", "cross_scale_v10")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "cross_scale_v10")
P = json.load(open(os.path.join(CFG, "protocol.json")))
ACTS = common.ACTS
CAP = float(P["per_run_cpu_seconds"])
RD = P["readers"]
TAG = {10: "SAT", 20: "UNSAT"}


# ------------------------------------------------------------------ data

def records(stage):
    out = []
    for p in glob.glob(os.path.join(RUNS, stage, "*.json")):
        if not p.endswith(("progress.json", "effective_plan.json")):
            out.append(json.load(open(p)))
    return out


def ok(r):
    return r["status"] == "solved" and (r.get("verification") or {}).get("ok") is True


def fixed_table(ids, stage, split=None, seed=0, variant=None):
    """{id: {t: {a: cpu}, ok: {a: bool}, status: {a: status}, answer}} from fixed runs of one stage."""
    tab = {i: {"t": {}, "ok": {}, "status": {}, "answer": None} for i in ids}
    for r in records(stage):
        if r["instance"] not in tab or r["method"] not in ACTS or r.get("seed", 0) != seed or r.get("variant") != variant:
            continue
        row = tab[r["instance"]]
        row["t"][r["method"]] = r["cpu"]
        row["ok"][r["method"]] = ok(r)
        row["status"][r["method"]] = r["status"] if r["status"] != "solved" or ok(r) else "unverified"
        if ok(r):
            row["answer"] = TAG.get(r.get("exit_code"))
    if split:
        for i in ids:
            tab[i].update({k: split[i][k] for k in ("type", "level", "rank", "fold") if k in split[i]})
    return tab


def dev_table():
    split = json.load(open(os.path.join(CFG, "split.json")))
    ids = sorted(i for i, v in split.items() if v["split"] == "dev")
    tab = fixed_table(ids, "s1_dev", split)
    for r in records("measure_dev"):
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
    return tab


def cell(row):
    return (row["type"], row["level"])


# ------------------------------------------------------------------ simulation (protocol 6.4)

class Pre:
    __slots__ = ("answered", "cost", "obs", "x", "started", "answer_arm", "consistent")

    def __init__(self, answered, cost, obs, x, started, answer_arm=None, consistent=True):
        self.answered, self.cost, self.obs, self.x, self.started = answered, cost, obs, x, started
        self.answer_arm, self.consistent = answer_arm, consistent


def pre(row, static, probes, v9=False):
    """Observation part of a schedule on one dev instance: cost so far, answer or features."""
    m = row["m"]
    cost = m["start"]
    st = {}
    if static:
        cost += m["static"]["cpu"] + m["static"]["wc"]
        st = m["static"]["features"] or {}
    arms, started, v9f = {}, {}, {}
    for arm, tau in probes:
        p = m["probes"][(arm, float(tau))]
        cost += p["cpu"] + p["wc"]
        if p["exit"] in (10, 20):
            cons = row["answer"] is None or TAG[p["exit"]] == row["answer"]
            return Pre(True, cost, cost, None, None, arm, cons)
        arms[arm] = p["features"] or {}
        started[arm] = bool(p["started"])
        if arm == "D" and p.get("v9"):
            v9f = p["v9"]
    x = common.combine(st, arms)
    if v9:
        x.update(v9f)
        started["v9cp"] = any(v is not None for v in v9f.values())
    return Pre(False, cost, cost, x, started)


def outcome(row, pr, a):
    """(solved, resource cost) of choosing action a after the observation pr."""
    if pr is not None and pr.answered:
        return (pr.consistent, pr.cost if pr.consistent else CAP)
    c = (pr.cost if pr is not None else 0.0) + row["t"][a]
    if row["ok"].get(a) and c <= CAP:
        return True, c
    return False, min(c, CAP)


def agg(outs):
    """outs: list of (solved, cost) -> (solved count, total cost)."""
    return sum(1 for s, _ in outs if s), sum(c for _, c in outs)


def better(k1, k2, margin=0.0):
    """Criterion 7.3: k = (solved, total). True if k1 strictly better than k2 by more than the margin."""
    if k1[0] != k2[0]:
        return k1[0] > k2[0]
    return k1[1] < (1.0 - margin) * k2[1]


def crit_key(k):
    return (-k[0], k[1])


# ------------------------------------------------------------------ readers (protocol 7.1)

def best_fixed(rows, prs, ids):
    keys = {a: agg([outcome(rows[i], prs[i], a) for i in ids]) for a in ACTS}
    return min(ACTS, key=lambda a: (crit_key(keys[a]), ACTS.index(a)))


def censored_delta(row, a, b):
    ta, tb, oa, ob = row["t"][a], row["t"][b], row["ok"].get(a), row["ok"].get(b)
    if oa and ob:
        return ta - tb
    if not oa and ob:
        return CAP - tb
    if oa and not ob:
        return ta - CAP
    return 0.0


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fit_reader(rows, prs, ids, features, needs, method, param, theta):
    """Strategy dict (common.decide format) fitted on the training ids."""
    U = [i for i in ids if not prs[i].answered]
    base = best_fixed(rows, prs, U) if U else "Fp"
    S = [i for i in U if all(prs[i].started.get(a) for a in needs)]
    impute = {}
    for f in features:
        vals = [prs[i].x.get(f) for i in S if _num(prs[i].x.get(f))]
        impute[f] = float(np.median(vals)) if vals else 0.0
    strat = {"features": list(features), "impute": impute, "base": base, "missing_action": base,
             "needs_arms": list(needs), "reader": None}
    if len(S) < 2 * RD["tree_min_leaf"]:
        strat["reader"] = {"method": "none", "reason": f"only {len(S)} training instances reach the reader"}
        return strat
    X = np.array([[prs[i].x[f] if _num(prs[i].x.get(f)) else impute[f] for f in features] for i in S], float)
    if method == "ridge":
        mu, sd = X.mean(0), X.std(0)
        sd[sd < 1e-12] = 1.0
        Z = (X - mu) / sd
        models = {}
        for a in ACTS:
            if a == base:
                continue
            y = np.array([censored_delta(rows[i], a, base) for i in S], float)
            yb = y.mean()
            w = np.linalg.solve(Z.T @ Z + param * np.eye(Z.shape[1]), Z.T @ (y - yb))
            models[a] = {"intercept": float(yb), "coef": {f: float(v) for f, v in zip(features, w)}}
        strat["reader"] = {"method": "ridge", "alpha": param, "margin": theta,
                           "mean": {f: float(v) for f, v in zip(features, mu)},
                           "std": {f: float(v) for f, v in zip(features, sd)}, "models": models}
        return strat
    # tree
    outs = {a: [outcome(rows[i], prs[i], a) for i in S] for a in ACTS}
    solved = np.array([[1.0 if outs[a][k][0] else 0.0 for a in ACTS] for k in range(len(S))])
    cost = np.array([[outs[a][k][1] for a in ACTS] for k in range(len(S))])
    bi = ACTS.index(base)
    thr = {}
    for j, f in enumerate(features):
        thr[f] = sorted({float(np.quantile(X[:, j], q, method="nearest")) for q in RD["tree_threshold_quantiles"]})

    def leaf(mask):
        n = int(mask.sum())
        s, c = solved[mask].sum(0), cost[mask].sum(0)
        a = bi
        if n >= RD["tree_min_leaf"]:
            for k in range(len(ACTS)):
                if k == bi or s[k] < s[bi]:
                    continue
                if c[bi] - c[k] > theta * n and (s[k], -c[k]) > (s[a], -c[a]):
                    a = k
        return (s[a], c[a]), {"leaf": ACTS[a]}

    def grow(mask, depth):
        key, node = leaf(mask)
        if depth == 0 or mask.sum() < 2 * RD["tree_min_leaf"]:
            return key, node
        best = None
        for j, f in enumerate(features):
            for t in thr[f]:
                lm = mask & (X[:, j] <= t)
                rm = mask & ~(X[:, j] <= t)
                if lm.sum() < RD["tree_min_leaf"] or rm.sum() < RD["tree_min_leaf"]:
                    continue
                kl, _ = leaf(lm)
                kr, _ = leaf(rm)
                k2 = (kl[0] + kr[0], kl[1] + kr[1])
                if best is None or (-k2[0], k2[1]) < (-best[0][0], best[0][1]):
                    best = (k2, j, f, t, lm, rm)
        if best is None or not ((-best[0][0], best[0][1]) < (-key[0], key[1] - 1e-9)):
            return key, node
        _, j, f, t, lm, rm = best
        kl, nl = grow(lm, depth - 1)
        kr, nr = grow(rm, depth - 1)
        return (kl[0] + kr[0], kl[1] + kr[1]), {"feature": f, "threshold": t, "left": nl, "right": nr}

    _, tree = grow(np.ones(len(S), bool), param)
    strat["reader"] = {"method": "tree", "depth": param, "margin": theta, "tree": tree}
    return strat


def reader_grid():
    """Reader configurations in the tie-break preference order of protocol 7.3."""
    out = []
    for th in sorted(RD["margin_seconds"], reverse=True):
        for al in sorted(RD["ridge_alpha"], reverse=True):
            out.append(("ridge", al, th))
    for th in sorted(RD["margin_seconds"], reverse=True):
        for d in sorted(RD["tree_depth"]):
            out.append(("tree", d, th))
    return out


# ------------------------------------------------------------------ families (protocol 6.3)

ORDERS = [tuple(o) for o in P["families"]["C"]["orders"]]


def family_configs(fam):
    F = P["families"]
    if fam == "SBS":
        return [{"fixed": a} for a in ACTS]
    if fam == "REF":
        return [{"static": False, "probes": [("D", 2.0)], "fallback": "Fp"}]
    if fam == "N_B":
        return [{"static": False, "probes": [("D", t)], "fallback": a} for t in F["N_B"]["taus"] for a in ACTS]
    if fam == "N_C":
        return [{"static": False, "probes": [(arm, t) for arm in o], "fallback": a}
                for t in F["N_C"]["taus"] for o in ORDERS for a in ACTS]
    if fam in ("A", "A_s"):
        feats = common.feature_set("A") if fam == "A" else ["st_log_vars", "st_log_clauses", "st_cv_ratio",
                                                             "st_mean_len", "st_bin_frac"]
        return [{"static": True, "probes": [], "features": feats, "needs": [], "reader": r} for r in reader_grid()]
    if fam == "B":
        return [{"static": True, "probes": [("D", t)], "features": common.feature_set("B"), "needs": ["D"], "reader": r}
                for t in F["B"]["taus"] for r in reader_grid()]
    if fam == "B_v9":
        return [{"static": False, "probes": [("D", t)], "features": common.feature_set("B_v9"), "needs": ["v9cp"],
                 "v9": True, "reader": r} for t in F["B_v9"]["taus"] for r in reader_grid()]
    if fam == "C":
        return [{"static": True, "probes": [(arm, t) for arm in o], "features": common.feature_set("C"),
                 "needs": ["D", "Fp", "Fm"], "reader": r} for t in F["C"]["taus"] for o in ORDERS for r in reader_grid()]
    raise ValueError(fam)


class Sim:
    """Caches the observation part of each schedule per instance."""

    def __init__(self, rows):
        self.rows = rows
        self._pre = {}

    def prs(self, cfg):
        if "fixed" in cfg:
            return {i: None for i in self.rows}
        key = (cfg["static"], tuple(cfg["probes"]), cfg.get("v9", False))
        if key not in self._pre:
            self._pre[key] = {i: pre(r, cfg["static"], cfg["probes"], cfg.get("v9", False)) for i, r in self.rows.items()}
        return self._pre[key]

    def fit(self, cfg, train):
        """Fitted strategy for a config on training ids (dict in common.decide format, or a fixed action)."""
        prs = self.prs(cfg)
        if "fixed" in cfg:
            return {"kind": "fixed", "action": cfg["fixed"]}
        if "fallback" in cfg:
            return {"kind": "observe", "static": cfg["static"], "probes": cfg["probes"], "reader": None,
                    "base": cfg["fallback"], "missing_action": cfg["fallback"], "features": [], "needs_arms": []}
        meth, par, th = cfg["reader"]
        s = fit_reader(self.rows, prs, train, cfg["features"], cfg["needs"], meth, par, th)
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


def inner_folds(rows, ids, k=3):
    by = {}
    for i in ids:
        by.setdefault(cell(rows[i]), []).append(i)
    f = {}
    for c in by.values():
        for r, i in enumerate(sorted(c, key=lambda i: rows[i]["rank"])):
            f[i] = r % k
    return f


def select_config(sim, fam, train, margin=0.01):
    """Inner 3-fold CV over the family's grid; returns (config index, inner results)."""
    cfgs = family_configs(fam)
    if len(cfgs) == 1:
        return 0, []
    f = inner_folds(sim.rows, train)
    res = []
    for ci, cfg in enumerate(cfgs):
        outs, obs = [], []
        for k in range(3):
            tr = [i for i in train if f[i] != k]
            te = [i for i in train if f[i] == k]
            got = sim.apply(cfg, sim.fit(cfg, tr), te)
            outs += [(v[0], v[1]) for v in got.values()]
            obs += [v[2] for v in got.values()]
        res.append((agg(outs), float(np.mean(obs)) if obs else 0.0, ci))
    best = min(res, key=lambda r: (crit_key(r[0]), r[2]))
    # ties (same solved, total within 1%): lower mean observation cost, then grid order
    tied = [r for r in res if r[0][0] == best[0][0] and r[0][1] <= (1 + margin) * best[0][1]]
    pick = min(tied, key=lambda r: (round(r[1], 6), r[2]))
    return pick[2], res


def run_family(sim, fam, train, test):
    ci, _ = select_config(sim, fam, train)
    cfg = family_configs(fam)[ci]
    strat = sim.fit(cfg, train)
    return cfg, strat, sim.apply(cfg, strat, test)


def outer_cv(sim, fam):
    rows = sim.rows
    oof, chosen = {}, []
    for k in range(5):
        train = [i for i in rows if rows[i]["fold"] != k]
        test = [i for i in rows if rows[i]["fold"] == k]
        cfg, strat, got = run_family(sim, fam, train, test)
        oof.update(got)
        chosen.append(describe(cfg, strat))
    return oof, chosen


def describe(cfg, strat):
    if "fixed" in cfg:
        return {"fixed": cfg["fixed"]}
    d = {"static": cfg["static"], "probes": [list(p) for p in cfg["probes"]]}
    if "fallback" in cfg:
        d["fallback"] = cfg["fallback"]
    else:
        rd = strat["reader"] or {}
        d.update(reader=list(cfg["reader"]), base=strat["base"], reader_method=rd.get("method"))
    return d


# ------------------------------------------------------------------ bootstrap

def strat_boot(cells, x, y, n=10000, seed=0):
    """Paired cell-stratified bootstrap of 1 - sum(x)/sum(y) (x = method costs, y = control costs per instance).
    cells: list of stratum labels aligned with x, y. Returns (point, lo, hi)."""
    rng = random.Random(seed)
    by = {}
    for k, c in enumerate(cells):
        by.setdefault(c, []).append(k)
    groups = list(by.values())
    point = 1 - sum(x) / sum(y)
    vals = []
    for _ in range(n):
        sx = sy = 0.0
        for g in groups:
            for _ in range(len(g)):
                k = g[rng.randrange(len(g))]
                sx += x[k]
                sy += y[k]
        vals.append(1 - sx / sy)
    vals.sort()
    return point, vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def flatten(x):
    return list(itertools.chain.from_iterable(x))
