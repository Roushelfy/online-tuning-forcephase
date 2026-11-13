"""Exploration analyses (2026-11-13), same cohort, budget and scoring as tools/anni2022_week_analysis.py.

  fourmode : cost-weighted selector over {D, F+, F-, F-largest}; inputs 42 statistics (+ per-variable majority-sign
             shares); same-distribution (iso) folds and whole-family folds
  safe     : the 3-mode static selector gated by novelty - if an instance's nearest training neighbour (standardised
             42-input space) is farther than tau, run D; tau chosen on inner-validation parents per fold
  robust   : seed-1 and permuted-copy reruns of 462 instances vs the baseline (preference reproducibility)

  PY tools/anni2022_explore_analysis.py {fourmode,safe,robust} --data DATA --gbd-base BASE --gbd-meta META --inputs inputs_mu --out OUT
"""
import argparse
import glob
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anni2022_selector as S  # noqa: E402
import anni2022_week_analysis as WA  # noqa: E402

BUDGET = 600.0


def family_folds(d):
    fams, _ = np.unique(d.family, return_counts=True)
    members = {f: (d.family == f).sum() for f in fams}
    order = sorted(fams, key=lambda f: (-members[f], f))
    ffold = {f: i % 5 for i, f in enumerate(order)}; finner = {f: (i // 5) % 5 == 0 for i, f in enumerate(order)}
    return np.array([ffold[f] for f in d.family]), np.array([finner[f] for f in d.family])


def four(d):
    t4 = np.array([d.flargest[k]["cpu_s"] for k in d.keys]); ok4 = np.array([d.flargest[k]["solved"] for k in d.keys])
    time = np.c_[d.time, t4]; ok = np.c_[d.ok, ok4]
    cost = np.where(ok, time, 2 * BUDGET)
    return time, ok, cost


def compose(time, ok, action, fee):
    t = time[np.arange(len(action)), action]; o = ok[np.arange(len(action)), action]; end = fee + t
    return np.where(o & (end <= BUDGET), end, 2 * BUDGET), np.minimum(end, BUDGET)


def run_selector(d, x, valid, time, ok, cost, folds, inner, fee_acq, acq_ok):
    usable = valid & acq_ok
    action, query, cuts = S.cross_validate(x, usable, cost, folds, inner, time_queries=True)
    fee = fee_acq + np.where(usable, query, 0.0)
    c, cpu = compose(time, ok, action, fee)
    return c, cpu, action, cuts


def summary(name, d, c, cpu, action, labels, cuts=None):
    D = d.cost[:, 0]
    return {"policy": name, "solved": int((c < 2 * BUDGET).sum()), "gain_vs_D_pct": 100 * float(D.sum() - c.sum()) / float(D.sum()),
            "mean_PAR2": float(c.mean()), "total_CPU_h": float(cpu.sum() / 3600),
            "rescued_vs_D": int(((D == 2 * BUDGET) & (c < 2 * BUDGET)).sum()), "lost_vs_D": int(((D < 2 * BUDGET) & (c == 2 * BUDGET)).sum()),
            "actions": {l: int((action == i).sum()) for i, l in enumerate(labels)}, "cuts": cuts}


def majority(d):
    rows, ok = [], []
    for k in d.keys:
        u = d.extract.get(k, {}).get("unit_unique")
        ok.append(bool(u)); rows.append([u["maj_pos_frac"], u["maj_neg_frac"], u["maj_tie_frac"]] if u else [0, 0, 0])
    return np.array(rows), np.array(ok)


def cmd_fourmode(a):
    d = WA.Data(a); time4, ok4, cost4 = four(d); acq_ok, acq_fee = WA.native_fees(d)
    X, ok_uu, uu_fee = WA.unit_unique_matrix(d); maj, ok_maj = majority(d)
    schemes = {"iso folds": (d.folds, d.inner), "whole-family folds": family_folds(d)}
    out = {"VBS4_gain_pct": 100 * float(d.cost[:, 0].sum() - cost4.min(axis=1).sum()) / float(d.cost[:, 0].sum()), "results": []}
    for scheme, (folds, inner) in schemes.items():
        for name, (x, valid, time, ok, cost, extra_fee, labels) in {
            "3 modes, 42 inputs": (d.x42, d.valid42, d.time, d.ok, d.cost, 0.0, ("D", "F+", "F-")),
            "4 modes, 42 inputs": (d.x42, d.valid42, time4, ok4, cost4, 0.0, ("D", "F+", "F-", "F-largest")),
            "4 modes, 42 inputs + majority-sign shares": (np.c_[d.x42, maj], d.valid42 & ok_maj, time4, ok4, cost4, uu_fee, ("D", "F+", "F-", "F-largest")),
        }.items():
            c, cpu, action, cuts = run_selector(d, x, valid, time, ok, cost, folds, inner, acq_fee + extra_fee, acq_ok)
            s = summary(f"{name} [{scheme}]", d, c, cpu, action, labels, cuts); out["results"].append(s)
            WA.save_costs(a, "explore_" + (name + "_" + scheme).replace(" ", "_").replace(",", ""), c)
            print(f"{s['policy']:62s} solved {s['solved']} gain {s['gain_vs_D_pct']:6.2f}% actions {s['actions']} cuts {s['cuts']}", flush=True)
    WA.write(a, "explore_fourmode", out)


def gated_cv(x, valid, cost, folds, inner, k=3):
    """mean3 selector plus novelty gate: nearest-training-neighbour distance (standardised) above tau -> D."""
    from sklearn.neighbors import NearestNeighbors
    n = len(cost); action = np.zeros(n, dtype=int); query = np.zeros(n); taus = []; cuts = []
    for fold in range(int(folds.max()) + 1):
        held = folds == fold; train, val = ~held & ~inner & valid, ~held & inner & valid
        ids = np.flatnonzero(held & valid); vids = np.flatnonzero(val)
        vp, hp, hf = [], [], []
        for seed in S.SEEDS:
            m = S.fit(x[train], cost[train], seed + fold)
            vp.append(S.scores(m, x[val], k)); p, f = S.measured(m, x[ids], k); hp.append(p); hf.append(f)
        vp, hp, hf = map(np.asarray, (vp, hp, hf))
        cut = S.calibrate(vp.mean(axis=0), cost[val], np.zeros(val.sum())); cuts.append(cut)
        mu, sd = x[train].mean(axis=0), x[train].std(axis=0) + 1e-9
        nn = NearestNeighbors(n_neighbors=1).fit((x[train] - mu) / sd)
        t0 = time.process_time(); dh = nn.kneighbors((x[ids] - mu) / sd)[0][:, 0]; per = (time.process_time() - t0) / max(len(ids), 1)
        dv = nn.kneighbors((x[vids] - mu) / sd)[0][:, 0]
        av = S.choose(vp.mean(axis=0), cut); ah = S.choose(hp.mean(axis=0), cut)
        grid = sorted(set(np.quantile(dv, [.25, .5, .7, .8, .9, .95, .99]).tolist() + [math.inf]))
        def val_cost(tau):
            a_ = np.where(dv <= tau, av, 0)
            return float(S.timed_cost(cost[vids, a_], .003).sum())
        tau = min(grid, key=val_cost); taus.append(tau)
        action[ids] = np.where(dh <= tau, ah, 0)
        if cut is not None: query[ids] = hf.sum(axis=0) + per
    return action, query, cuts, taus


def cmd_safe(a):
    d = WA.Data(a); acq_ok, acq_fee = WA.native_fees(d); usable = d.valid42 & acq_ok; out = []
    for scheme, (folds, inner) in {"iso folds": (d.folds, d.inner), "whole-family folds": family_folds(d)}.items():
        action, query, cuts, taus = gated_cv(d.x42, usable, d.cost, folds, inner)
        fee = acq_fee + np.where(usable, query, 0.0)
        c, cpu = compose(d.time, d.ok, action, fee)
        s = summary(f"static + novelty gate [{scheme}]", d, c, cpu, action, ("D", "F+", "F-"), cuts); s["taus"] = [str(round(t, 3)) if t != math.inf else "inf" for t in taus]
        out.append(s); WA.save_costs(a, "explore_safe_" + scheme.replace(" ", "_"), c)
        print(f"{s['policy']:50s} solved {s['solved']} gain {s['gain_vs_D_pct']:6.2f}% actions {s['actions']} taus {s['taus']}", flush=True)
    WA.write(a, "explore_safe", {"results": out})


def cmd_robust(a):
    d = WA.Data(a); root = Path(a.data) / "explore/robust"
    sample = json.loads((Path(a.data) / "explore/robust_sample.json").read_text())
    res = {}
    for f in glob.glob(str(root / "results/*.json")):
        r = json.loads(open(f).read()); res[(r["instance_key"], r["config"])] = r
    modes = ("D", "Fplus", "Fminus")
    base_conf = {r["instance_key"]: r["D_conflicts"] for r in S.read_csv(Path(a.data) / "cluster_v3_analysis/matrix.csv")}
    out = {"population": sample["population"], "strata": {}}
    for stratum in ("R", "G", "C"):
        keys = [r["instance_key"] for r in sample["instances"] if r["stratum"] == stratum]
        st = {"n": len(keys)}
        for cond in ("seed1", "perm1"):
            have = [k for k in keys if all((k, f"{cond}_{m}") in res for m in modes)]
            T = lambda k, m: (res[(k, f"{cond}_{m}")]["cpu_s"] if res[(k, f"{cond}_{m}")]["solved"] else math.inf)
            B = lambda k, m: (d.time[d.index[k], modes.index(m)] if d.ok[d.index[k], modes.index(m)] else math.inf)
            best_same = sum(int(np.argmin([T(k, m) for m in modes]) == np.argmin([B(k, m) for m in modes])) for k in have if min(B(k, m) for m in modes) < math.inf and min(T(k, m) for m in modes) < math.inf)
            both_any = sum(1 for k in have if min(B(k, m) for m in modes) < math.inf and min(T(k, m) for m in modes) < math.inf)
            c = {"complete": len(have), "fastest_mode_same": best_same, "fastest_mode_comparable": both_any}
            if stratum == "R":
                c["D_still_timeout"] = sum(T(k, "D") == math.inf for k in have)
                c["a_forced_mode_still_solves"] = sum(min(T(k, "Fplus"), T(k, "Fminus")) < math.inf for k in have)
                c["rescue_reproduced (D timeout and F solves)"] = sum(T(k, "D") == math.inf and min(T(k, "Fplus"), T(k, "Fminus")) < math.inf for k in have)
                c["same_forced_mode_solves"] = sum(any(B(k, m) < math.inf and T(k, m) < math.inf for m in ("Fplus", "Fminus")) for k in have)
            if stratum in ("G", "C"):
                # does the >= 2x forced-mode advantage over D persist?
                adv_b = [k for k in have if B(k, "D") < math.inf and B(k, "D") >= 1 and min(B(k, "Fplus"), B(k, "Fminus")) * 2 <= B(k, "D")]
                c["baseline_F_2x_faster"] = len(adv_b)
                c["still_F_faster_than_D"] = sum(min(T(k, "Fplus"), T(k, "Fminus")) < T(k, "D") for k in adv_b)
                c["still_F_2x_faster"] = sum(min(T(k, "Fplus"), T(k, "Fminus")) * 2 <= T(k, "D") for k in adv_b)
            # identical reruns? (seed / permutation had no effect)
            c["D_conflicts_identical_to_baseline"] = sum(str(res[(k, f"{cond}_D")]["conflicts"]) == base_conf[k] for k in have)
            c["D_time_ratio_median_both_solved"] = float(np.median([T(k, "D") / B(k, "D") for k in have if T(k, "D") < math.inf and B(k, "D") < math.inf and B(k, "D") >= 1] or [math.nan]))
            st[cond] = c
        out["strata"][stratum] = st
    # population-weighted transferable oracle: best mode chosen on the baseline run, scored on the perturbed runs
    w = {k_: sample["population"][k_] / sum(1 for r in sample["instances"] if r["stratum"] == k_) for k_ in ("R", "G", "C")}
    strat = {r["instance_key"]: r["stratum"] for r in sample["instances"]}
    for cond in ("seed1", "perm1"):
        keys = [k for k in strat if all((k, f"{cond}_{m}") in res for m in modes)]
        ww = np.array([w[strat[k]] for k in keys])
        base = np.array([[d.cost[d.index[k], j] for j in range(3)] for k in keys])
        pert = np.array([[res[(k, f"{cond}_{m}")]["cpu_s"] if res[(k, f"{cond}_{m}")]["solved"] else 1200.0 for m in modes] for k in keys])
        pick = base.argmin(axis=1)
        g = lambda ref, c: 100 * float((ww * (ref - c)).sum() / (ww * ref).sum())
        out[f"weighted_{cond}"] = {"instances": len(keys),
            "VBS_gain_on_baseline_runs_pct": g(base[:, 0], base.min(axis=1)),
            "VBS_gain_on_perturbed_runs_pct": g(pert[:, 0], pert.min(axis=1)),
            "baseline_best_mode_applied_to_perturbed_runs_pct": g(pert[:, 0], pert[np.arange(len(keys)), pick]),
            "always_D_baseline_vs_perturbed_cost_ratio": float((ww * pert[:, 0]).sum() / (ww * base[:, 0]).sum())}
    WA.write(a, "explore_robust", out); print(json.dumps(out, indent=1))


REPORT = __import__("re").compile(r"^c [^ ] +([0-9.]+) +([0-9]+) +([0-9]+) +[0-9]+ +([0-9]+) +[0-9]+ +([0-9]+) +[0-9]+ +[0-9.]+ +[0-9]+ +[0-9]+ +[0-9]+ +[0-9]+ +([0-9]+)% ", __import__("re").M)


def parse_report_lines(path):
    """(seconds, level, restarts, conflicts, trail%) from CaDiCaL progress lines of a gzipped T600 log."""
    import gzip
    text = gzip.open(path, "rt", errors="replace").read()
    return [(float(m[0]), int(m[2]), int(m[3]), int(m[4]), int(m[5])) for m in REPORT.findall(text)]


def cmd_midrun(a):
    """Mid-run version of the level hypothesis from the T600 baseline logs: at t, among instances where no mode
    has finished, is the mode with the lowest progress-line level the eventual fastest?"""
    d = WA.Data(a); modes = ("D", "Fplus", "Fminus")
    snap = json.loads((Path(a.data) / "cluster_v3_analysis/summary.json").read_text())
    shard_of = {Path(e["path"]).parts[-2]: Path(e["path"]).parts[0] for e in snap["evidence"]}
    runs = {(r["instance_key"], r["action"]): r["run_id"] for r in S.read_csv(Path(a.data) / "cluster_v3_analysis/runs.csv")}
    series = {}
    for k in d.keys:
        for m in modes:
            rid = runs[(k, m)]
            series[(k, m)] = parse_report_lines(Path(a.data) / "cluster_v3" / shard_of[rid] / "runs" / rid / "solver.log.gz")
    out = {}
    for t in (10, 30, 100, 300):
        rows = []
        for i, k in enumerate(d.keys):
            if any(d.ok[i, j] and d.time[i, j] <= t for j in range(3)): continue      # someone already finished
            lv = []
            for m in modes:
                pts = [p for p in series[(k, m)] if p[0] <= t]
                lv.append(pts[-1][1] if pts else None)
            if None in lv: continue
            cost = d.cost[i]
            if np.ptp(cost) == 0: continue                                              # no strictly better mode
            rows.append((lv, cost))
        lev = np.array([r[0] for r in rows], dtype=float); cost = np.array([r[1] for r in rows])
        best = cost.argmin(axis=1); low = lev.argmin(axis=1)
        res = {"instances": int(len(rows)), "lowest_level_is_best": float((low == best).mean()), "D_is_best": float((best == 0).mean()),
               "lowest_level_mode_counts": dict(Counter(modes[j] for j in low))}
        for j, mname in ((1, "F+"), (2, "F-")):
            both = cost[:, j] != cost[:, 0]
            rel = (lev[both, j] - lev[both, 0]) / np.maximum(lev[both, 0], 1)
            res[f"{mname}_vs_D_spearman"] = WA.spearman(rel, np.log(cost[both, j] / cost[both, 0]))
        out[f"t{t}"] = res
        print(f"t={t:3d}s n={res['instances']:4d} lowest-level-is-best {res['lowest_level_is_best']:.3f}  D-is-best {res['D_is_best']:.3f}  "
              f"rho F+ {res['F+_vs_D_spearman']['rho']:.3f} (p {res['F+_vs_D_spearman']['p']:.2g})  rho F- {res['F-_vs_D_spearman']['rho']:.3f} (p {res['F-_vs_D_spearman']['p']:.2g})", flush=True)
    WA.write(a, "explore_midrun", out)


def cmd_familyinfo(a):
    """How much do the 42 statistics add beyond family identity? Same recipe and iso folds, free features."""
    d = WA.Data(a); fams = sorted(set(d.family)); onehot = np.array([[f == g for g in fams] for f in d.family], dtype=float)
    out = []
    for name, x, valid in (("family one-hot only", onehot, np.ones(d.n, bool)), ("42 statistics only", d.x42, d.valid42),
                           ("42 statistics + family one-hot", np.c_[d.x42, onehot], d.valid42)):
        action, _, cuts = S.cross_validate(x, valid, d.cost, d.folds, d.inner, time_queries=False)
        c, cpu = compose(d.time, d.ok, action, np.zeros(d.n))
        s_ = summary(name + " [iso folds, free]", d, c, cpu, action, ("D", "F+", "F-"), cuts); out.append(s_)
        print(f"{s_['policy']:55s} solved {s_['solved']} gain {s_['gain_vs_D_pct']:6.2f}% actions {s_['actions']}", flush=True)
    # family-level oracles: best fixed mode per family in-sample, and leave-one-instance-out within the family
    time4, ok4, cost4 = four(d); Dsum = d.cost[:, 0].sum(); bounds = {}
    for name, C in (("3 modes", d.cost), ("4 modes", cost4)):
        ins, loo = np.zeros(d.n), np.zeros(d.n)
        for f in fams:
            i = np.flatnonzero(d.family == f); tot = C[i].sum(axis=0); ins[i] = C[i, tot.argmin()]
            for j in i: loo[j] = C[j, (tot - C[j]).argmin()] if len(i) > 1 else C[j, 0]
        bounds[name] = {"per_instance_VBS_pct": 100 * float(Dsum - C.min(axis=1).sum()) / Dsum,
                        "family_best_in_sample_pct": 100 * float(Dsum - ins.sum()) / Dsum,
                        "family_best_leave_one_out_pct": 100 * float(Dsum - loo.sum()) / Dsum, "leave_one_out_solved": int((loo < 2 * BUDGET).sum())}
    # paired family-cluster bootstrap of the exploration selectors against the 3-mode selector (saved cost arrays)
    cdir = Path(a.out) / "costs"; ci = {}
    ref = np.load(cdir / "explore_3_modes_42_inputs_iso_folds.npy")
    fidx = [np.flatnonzero(d.family == f) for f in fams]; rng = np.random.default_rng(1); B = rng.integers(0, len(fams), (2000, len(fams)))
    fs = lambda c: np.array([c[i].sum() for i in fidx]); Ds, R = fs(d.cost[:, 0]), fs(ref)
    for name in ("explore_4_modes_42_inputs_iso_folds", "explore_4_modes_42_inputs_+_majority-sign_shares_iso_folds", "explore_safe_iso_folds"):
        X = fs(np.load(cdir / f"{name}.npy")); g = np.array([100 * (R[b].sum() - X[b].sum()) / Ds[b].sum() for b in B])
        ci[name] = {"point_vs_3mode_pct": 100 * float(R.sum() - X.sum()) / float(Ds.sum()), "q2.5": float(np.quantile(g, .025)), "q97.5": float(np.quantile(g, .975))}
    print(json.dumps({"bounds": bounds, "vs_3mode": ci}, indent=1))
    WA.write(a, "explore_familyinfo", {"results": out, "family_bounds": bounds, "paired_vs_3mode": ci})


def cmd_robustci(a):
    """Stratified-bootstrap view of the reruns: per-stratum reproduction of the forced-mode advantage, and
    population-weighted gains (static selector with its cluster fees, VBS, baseline-best mode) per condition."""
    d = WA.Data(a); A = Path(a.out).parent.parent / "week20261116/analysis"
    sa = np.load(A / "static_actions.npy"); sq = np.load(A / "static_query_fee.npy")
    fee = np.array([d.extract[k]["native_cpu_s"] + (sq[i] if d.extract[k]["native_ok"] else 0.0) for i, k in enumerate(d.keys)])
    sample = json.loads((Path(a.data) / "explore/robust_sample.json").read_text()); pop = sample["population"]
    strat = {r["instance_key"]: r["stratum"] for r in sample["instances"]}
    res = {}
    for f in glob.glob(str(Path(a.data) / "explore/robust*/results/*.json")):
        r = json.loads(open(f).read()); res[(r["instance_key"], r["config"])] = r
    modes = ("D", "Fplus", "Fminus"); rng = np.random.default_rng(20261113); out = {}
    def times(k, cond):
        if cond == "baseline":
            i = d.index[k]; return [d.time[i, j] if d.ok[i, j] else None for j in range(3)]
        return [res[(k, f"{cond}_{m}")]["cpu_s"] if res[(k, f"{cond}_{m}")]["solved"] else None for m in modes]
    c = lambda t, f=0.0: (t + f) if t is not None and t + f <= BUDGET else 2 * BUDGET
    for cond in ("baseline", "seed1", "perm1", "shuffle1"):
        keys = [k for k in strat if cond == "baseline" or all((k, f"{cond}_{m}") in res for m in modes)]
        if not keys: continue
        rows = []
        for k in keys:
            T = times(k, cond); B = times(k, "baseline"); i = d.index[k]
            dc = c(T[0]); bestb = int(np.argmin([c(t) for t in B]))
            fb = min((B[j] for j in (1, 2) if B[j] is not None), default=None)
            ft = min((T[j] for j in (1, 2) if T[j] is not None), default=None)
            rows.append({"k": k, "s": strat[k], "D": dc, "static": c(T[sa[i]], fee[i]), "vbs": min(c(t) for t in T), "transfer": c(T[bestb]),
                         "rescue": T[0] is None and ft is not None,
                         "adv2x": B[0] is not None and B[0] >= 1 and fb is not None and 2 * fb <= B[0] and ft is not None and (T[0] is None or 2 * ft <= T[0])})
        o = {"instances": len(rows)}
        for st in ("R", "G"):
            sel = [r for r in rows if r["s"] == st]
            if sel:
                key = "rescue" if st == "R" else "adv2x"
                v = np.array([r[key] for r in sel], float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
                o[f"{st}_share_reproduced"] = {"point": float(v.mean()), "q2.5": float(np.quantile(bs, .025)), "q97.5": float(np.quantile(bs, .975)), "n": len(v)}
        if {r["s"] for r in rows} >= {"R", "G", "C"}:
            groups = {st: [r for r in rows if r["s"] == st] for st in ("R", "G", "C")}
            w = {st: pop[st] / len(groups[st]) for st in groups}
            def gains(sel):
                den = sum(w[st] * sum(r["D"] for r in sel[st]) for st in sel)
                return {m: 100 * sum(w[st] * sum(r["D"] - r[m] for r in sel[st]) for st in sel) / den for m in ("static", "vbs", "transfer")}
            point = gains(groups); boots = []
            for _ in range(2000):
                boots.append(gains({st: [g[j] for j in rng.integers(0, len(g), len(g))] for st, g in groups.items()}))
            o["weighted_gain_pct"] = {m: {"point": point[m], "q2.5": float(np.quantile([b[m] for b in boots], .025)),
                                          "q97.5": float(np.quantile([b[m] for b in boots], .975))} for m in point}
        out[cond] = o
        print(cond, json.dumps(o))
    WA.write(a, "explore_robustci", out)


def main():
    p = argparse.ArgumentParser(); p.add_argument("cmd", choices=["fourmode", "safe", "robust", "midrun", "familyinfo", "robustci"])
    for x in ("--data", "--gbd-base", "--gbd-meta", "--inputs", "--out"): p.add_argument(x, required=True)
    a = p.parse_args(); Path(a.out).mkdir(parents=True, exist_ok=True)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=4):
        {"fourmode": cmd_fourmode, "safe": cmd_safe, "robust": cmd_robust, "midrun": cmd_midrun, "familyinfo": cmd_familyinfo, "robustci": cmd_robustci}[a.cmd](a)


if __name__ == "__main__":
    main()
