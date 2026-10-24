#!/usr/bin/env python3
"""v8 pilot plans, scale calibration and formal-size choice
(docs/STRATIFIED_PROTOCOL_V8.md sections 2-3). Standard library only.

  calibrate.py gen-plan --round 1                 -> configs/stratified_v8/pilot_r1_gen.json
  calibrate.py run-plan --manifest M --stage S    -> configs/stratified_v8/<S>.json (D/Fp/Fm [+ D repeat])
  calibrate.py analyze                            -> prints pilot costs; writes round-2 gen plan if needed
  calibrate.py final                              -> configs/stratified_v8/scales.json (parameters, N, tau)
"""

import argparse
import glob
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "stratified_v8")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "stratified_v8")
P = json.load(open(os.path.join(CFG, "protocol.json")))
G = json.load(open(os.path.join(CFG, "generators.json")))
TYPES, SCALES = P["types"], P["scales"]
PIL = P["pilot"]
ENV_SETUP_H = 0.02


def seed(rnd, t, s):
    return 8000000 + 1000 * rnd + 100 * TYPES.index(t) + 10 * SCALES.index(s)


def gen_plan(rnd, params):
    inst = [{"id": f"v8p-r{rnd}-{t}-{s}", "type": t, "scale": s, "param": params[t][s], "seed": seed(rnd, t, s),
             "role": "pilot", "round": rnd} for t in TYPES for s in SCALES if s in params.get(t, {})]
    out = os.path.join(CFG, f"pilot_r{rnd}_gen.json")
    json.dump({"stage": f"pilot_r{rnd}", "instances": inst}, open(out, "w"), indent=1)
    print(out, len(inst))


def run_plan(manifest, stage, repeat_d, cap, methods=("D", "Fp", "Fm")):
    man = json.load(open(manifest))
    jobs = []
    for r in man["instances"]:
        for m in methods:
            jobs.append({"instance": r["id"], "sha256": r["sha256"], "method": m, "rep": 0, "cap_cpu": cap})
        if repeat_d:
            jobs.append({"instance": r["id"], "sha256": r["sha256"], "method": "D", "rep": 1, "cap_cpu": cap})
    out = os.path.join(CFG, f"{stage}.json")
    json.dump({"stage": stage, "manifest": os.path.relpath(manifest, ROOT), "jobs": jobs}, open(out, "w"), indent=1)
    print(out, len(jobs))


def load_stage(stage):
    recs = []
    for p in glob.glob(os.path.join(RUNS, stage, "*.json")):
        if p.endswith("progress.json"):
            continue
        recs.append(json.load(open(p)))
    return recs


def pilot_points():
    """One row per pilot instance: cost c (mean of D/Fp/Fm), censored flag, checker CPU, conflicts."""
    rows, solver, checker, noise = [], 0.0, 0.0, []
    for rnd in (1, 2):
        mp = os.path.join(ROOT, "results", "stratified_v8", f"pilot_r{rnd}_manifest.json")
        if not os.path.exists(mp):
            continue
        man = {r["id"]: r for r in json.load(open(mp))["instances"]}
        recs = load_stage(f"pilot_r{rnd}")
        by = {}
        for r in recs:
            by.setdefault(r["instance"], {})[(r["method"], r.get("rep", 0))] = r
            solver += r.get("cpu") or 0.0
            checker += ((r.get("verification") or {}).get("cpu") or 0.0)
        for iid, m in man.items():
            rr = by.get(iid, {})
            mains = [rr.get((a, 0)) for a in ("D", "Fp", "Fm")]
            if any(x is None or x["status"] == "not_started" for x in mains):
                rows.append({"id": iid, "type": m["type"], "scale": m["scale"], "param": m["param"], "round": rnd,
                             "c": None, "complete": False, "missing": True})
                continue
            cs = [x["cpu"] for x in mains]
            ok = [x["status"] == "solved" for x in mains]
            row = {"id": iid, "type": m["type"], "scale": m["scale"], "param": m["param"], "round": rnd,
                   "c": sum(cs) / 3, "sum3": sum(cs), "complete": all(ok), "missing": False,
                   "times": dict(zip(("D", "Fp", "Fm"), cs)), "statuses": dict(zip(("D", "Fp", "Fm"), [x["status"] for x in mains])),
                   "conflicts_D": (mains[0].get("stats") or {}).get("conflicts"),
                   "answer": {10: "SAT", 20: "UNSAT"}.get(mains[0].get("exit_code")),
                   "vars": m["vars"], "clauses": m["clauses"]}
            d2 = rr.get(("D", 1))
            if d2 and d2["status"] == "solved" and mains[0]["status"] == "solved":
                mu = (d2["cpu"] + mains[0]["cpu"]) / 2
                row["D_repeat"] = d2["cpu"]
                if mu >= 0.5:
                    noise.append(abs(d2["cpu"] - mains[0]["cpu"]) / mu)
            rows.append(row)
    return rows, solver, checker, noise


def gidx(t, p):
    return G[t]["grid"].index(p)


def slope(points):
    xs = [gidx(r["type"], r["param"]) for r in points]
    ys = [math.log(max(r["c"], 1e-3)) for r in points]
    if len(set(xs)) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def in_band(c, s):
    lo, hi = PIL["bands_cpu_seconds"][s]
    return c is not None and lo <= c <= hi


def predict(t, s, ref, sl):
    """Grid index predicted for target of scale s from reference point ref."""
    grid = G[t]["grid"]
    g = gidx(t, ref["param"])
    tgt = math.log(PIL["targets_cpu_seconds"][s])
    lc = math.log(max(ref["c"], 1e-3))
    direction = 1 if tgt > lc else -1
    if sl is None or sl < PIL["min_slope_log_per_grid_step"]:
        g2 = g + direction * PIL["fallback_grid_steps"]
    else:
        g2 = int(round(g + (tgt - lc) / sl))
        if g2 == g:
            g2 = g + direction
    return max(0, min(len(grid) - 1, g2))


def enforce_order(t, idx):
    """idx: {S: g, M: g, L: g} -> strictly increasing, moving later scales up when needed."""
    grid = G[t]["grid"]
    out = dict(idx)
    for a, b in (("S", "M"), ("M", "L")):
        if out[b] <= out[a]:
            out[b] = min(len(grid) - 1, out[a] + 1)
    if out["M"] <= out["S"]:
        out["S"] = max(0, out["M"] - 1)
    return out


def analyze(write):
    rows, solver, checker, noise = pilot_points()
    for r in sorted(rows, key=lambda r: (r["round"], TYPES.index(r["type"]), SCALES.index(r["scale"]))):
        print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}))
    print(json.dumps({"solver_cpu_h": solver / 3600, "checker_cpu_h": checker / 3600, "noise": noise}))
    r1 = [r for r in rows if r["round"] == 1]
    if not write:
        return rows
    params = {}
    for t in TYPES:
        pts = [r for r in r1 if r["type"] == t and r["c"] is not None]
        sl = slope(pts)
        want = {}
        for s in SCALES:
            ref = next((r for r in pts if r["scale"] == s), None)
            if ref is None or in_band(ref["c"], s):
                want[s] = gidx(t, ref["param"]) if ref else None
                continue
            want[s] = predict(t, s, ref, sl)
        fixed = enforce_order(t, {s: (want[s] if want[s] is not None else 0) for s in SCALES})
        for s in SCALES:
            ref = next((r for r in pts if r["scale"] == s), None)
            if ref is not None and not in_band(ref["c"], s):
                params.setdefault(t, {})[s] = G[t]["grid"][fixed[s]]
        print(t, "slope", sl, "->", params.get(t))
    if params:
        gen_plan(2, params)
    else:
        print("all round-1 cells in band: no round 2")
    return rows


def final(ledger_extra_h):
    rows, solver, checker, noise = pilot_points()
    choice, est = {}, {}
    for t in TYPES:
        pts = [r for r in rows if r["type"] == t and r["c"] is not None]
        idx = {}
        for s in SCALES:
            cand = [r for r in pts if in_band(r["c"], s)]
            if cand:
                best = min(cand, key=lambda r: abs(math.log(r["c"]) - math.log(PIL["targets_cpu_seconds"][s])))
                idx[s] = gidx(t, best["param"])
            else:
                done = [r for r in pts if r["complete"]]
                sl = slope(done) if len(done) >= 2 else None
                ref = min(pts, key=lambda r: abs(math.log(max(r["c"], 1e-3)) - math.log(PIL["targets_cpu_seconds"][s])))
                idx[s] = predict(t, s, ref, sl)
        idx = enforce_order(t, idx)
        for s in SCALES:
            p = G[t]["grid"][idx[s]]
            meas = [r for r in pts if r["param"] == p]
            if meas:
                c3 = sum(r["sum3"] for r in meas) / len(meas)
                src = "measured"
            else:
                done = [r for r in pts if r["complete"]]
                sl = slope(done) if len(done) >= 2 else None
                ref = min(pts, key=lambda r: abs(gidx(t, r["param"]) - idx[s]))
                sl = sl if sl and sl > 0 else PIL["min_slope_log_per_grid_step"]
                c3 = 3 * math.exp(math.log(max(ref["c"], 1e-3)) + sl * (idx[s] - gidx(t, ref["param"])))
                src = f"extrapolated from {ref['id']} (slope {sl:.3f}/step)"
            choice.setdefault(t, {})[s] = p
            est[f"{t}-{s}"] = {"param": p, "C3_seconds": c3, "source": src}
    kappa = 1 + (checker / solver if solver > 0 else 0)
    gen_cpu = 0.0
    for rnd in (1, 2):
        mp = os.path.join(ROOT, "results", "stratified_v8", f"pilot_r{rnd}_manifest.json")
        if os.path.exists(mp):
            gen_cpu += json.load(open(mp))["gen_cpu_total"]
    ledger = P["budget"]["used_before_v8"] + ENV_SETUP_H + (solver + checker + gen_cpu) / 3600 + ledger_extra_h
    F = P["formal"]
    B_f = P["budget"]["cumulative_cap_cpu_hours"] - ledger - F["analysis_reserve_cpu_hours"] - F["final_reserve_cpu_hours"]
    sumC = sum(v["C3_seconds"] for v in est.values())
    costs = {}
    for n in F["sizes"]:
        nd, nh = F["per_cell"][str(n)]
        costs[n] = (F["tail_factor"] * kappa * sumC * (nd + nh * (1 + F["wrapper_cost_fraction_of_three_modes"]))
                    + F["observation_cost_per_instance_seconds"] * n) / 3600
    feasible = [n for n in F["sizes"] if costs[n] <= B_f]
    N = max(feasible) if feasible else None
    r = statistics.median(noise) if noise else None
    A = P["advantage_threshold"]
    tau_rel = max(A["tau_rel_min"], A["tau_rel_noise_multiplier"] * r) if r is not None else A["tau_rel_min"]
    out = {"params": choice, "estimates": est, "kappa": kappa, "tail_factor": F["tail_factor"],
           "ledger_after_pilot_cpu_hours": ledger,
           "ledger_parts": {"before_v8": P["budget"]["used_before_v8"], "env_setup": ENV_SETUP_H,
                            "generation": gen_cpu / 3600, "pilot_solver": solver / 3600, "pilot_checker": checker / 3600,
                            "extra": ledger_extra_h},
           "formal_budget_B_f_cpu_hours": B_f, "estimated_cost_cpu_hours": costs, "N": N,
           "per_cell": F["per_cell"][str(N)] if N else None,
           "timing_noise_median_rel": r, "timing_noise_pairs": noise, "tau_rel": tau_rel, "tau_abs": A["tau_abs_seconds"]}
    if N:
        nd, nh = F["per_cell"][str(N)]
        out["S1_budget_cpu_hours"] = B_f - F["tail_factor"] * kappa * sumC * nh * (1 + F["wrapper_cost_fraction_of_three_modes"]) / 3600
    json.dump(out, open(os.path.join(CFG, "scales.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen-plan")
    g.add_argument("--round", type=int, required=True)
    r = sub.add_parser("run-plan")
    r.add_argument("--manifest", required=True)
    r.add_argument("--stage", required=True)
    r.add_argument("--repeat-d", action="store_true")
    r.add_argument("--cap", type=float, default=PIL["cap_cpu_per_run"])
    an = sub.add_parser("analyze")
    an.add_argument("--write-round2", action="store_true")
    f = sub.add_parser("final")
    f.add_argument("--ledger-extra-hours", type=float, default=0.0)
    a = ap.parse_args()
    if a.cmd == "gen-plan":
        if a.round != 1:
            sys.exit("round 2 plans come from `analyze --write-round2`")
        gen_plan(1, PIL["round1_params"])
    elif a.cmd == "run-plan":
        run_plan(a.manifest, a.stage, a.repeat_d, a.cap)
    elif a.cmd == "analyze":
        analyze(a.write_round2)
    else:
        final(a.ledger_extra_hours)


if __name__ == "__main__":
    main()
