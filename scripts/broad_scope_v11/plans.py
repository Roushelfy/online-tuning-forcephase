#!/usr/bin/env python3
"""Goal v11 generation and run plans (docs/BROAD_SCOPE_PROTOCOL_V11.md sections 3-6). Standard library only.

  plans.py explore-gen [--round 2]   configs/broad_scope_v11/explore_gen[_r2].json (protocol 3.4)
  plans.py plan --manifest M --stage S --methods D[,Fp,Fm] [--measure] [--seeds 1,2] [--ids-from F]
                                     generic run plan configs/broad_scope_v11/plans/<S>.json
  plans.py explore-decide            scales_candidate.json: secondary parameters + S/M/L size candidates
  plans.py pilot-gen                 pilot_gen.json (8 families x 3 levels x 4, seeds 8000+)
  plans.py pilot-decide              scales.json by the pilot band rule (protocol 3.5)
  plans.py formal-gen                formal_gen.json (discovery 288, development 240, confirmation 240)
  plans.py variants-gen              variants_gen.json (protocol 6) and the seed-repeat list
"""
import argparse
import glob
import json
import math
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "broad_scope_v11")
RES = os.path.join(ROOT, "results", "broad_scope_v11")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "broad_scope_v11")
GEN11 = json.load(open(os.path.join(CFG, "generators.json")))
PANEL = json.load(open(os.path.join(CFG, "panel_rule.json")))
GEN9 = json.load(open(os.path.join(ROOT, "configs", "online_selection_v9", "generators.json")))
FAMS = PANEL["families"]
NEW = ("vcover", "jssp", "bwplan", "factor", "qcp")
BRIDGE = ("rand3", "col3", "assign2")
LEVELS = ("S", "M", "L")
SECONDARY = {"vcover": "budget_frac", "jssp": "rho", "bwplan": "gamma", "qcp": "preassign_frac"}
MEASURE = {"static": True, "probes": [{"arm": "D", "tau": t} for t in (0.1, 0.5, 2.0)]}
GENERATED = set(FAMS)


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")


def load(path):
    return json.load(open(path))


def grid(fam):
    return GEN9[fam]["grid"] if fam in BRIDGE else GEN11[fam]["size_grid"]


def records(stage):
    out = []
    for p in glob.glob(os.path.join(RUNS, stage, "*.json")):
        if not p.endswith(("progress.json", "effective_plan.json")):
            out.append(load(p))
    return out


def solved(r):
    return r.get("exit_code") in (10, 20) and (r.get("verification") or {}).get("ok") and r["cpu"] <= 3600.0


# ------------------------------------------------------------------ exploration (protocol 3.4)

def explore_gen(rnd, extra=None):
    ex = GEN11["explore"]
    rows = []
    seed0 = ex["seed_start"] + {1: 0, 2: 500, 3: 700}[rnd]
    for fam in NEW:
        sizes = (extra or {}).get(fam) if rnd > 1 else ex[fam]
        if not sizes:
            continue
        if fam == "factor":
            for b in sizes:
                for k in range(ex["factor_seeds"]):
                    s = seed0 + k
                    rows.append({"id": f"v11x-factor-{b}-s{s}", "family": fam, "size": b, "seed": s, "role": "explore"})
            continue
        key = SECONDARY[fam]
        for val in GEN11[fam]["grid"][key]:
            for n in sizes:
                for k in range(ex["seeds_per_value"]):
                    s = seed0 + k
                    rows.append({"id": f"v11x-{fam}-{n}-{key}{val}-s{s}", "family": fam, "size": n, "seed": s,
                                 "params": {key: val}, "role": "explore"})
    dump(os.path.join(CFG, "explore_gen" + ("" if rnd == 1 else f"_r{rnd}") + ".json"), {"instances": rows})
    print(len(rows), "exploration instances")


def fit(points):
    """Least squares of ln(cpu) on size; points (size, cpu)."""
    xs, ys = [p[0] for p in points], [math.log(max(p[1], 1e-3)) for p in points]
    if len(set(xs)) < 2:
        return None, None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def pick_sizes(fam, a, b, targets):
    out = {}
    for lv in LEVELS:
        t = targets[lv]
        out[lv] = min(grid(fam), key=lambda s: (abs((a + b * s) - math.log(t)), s))
    return out


def explore_decide():
    targets = PANEL["targets_median_D_cpu"]
    mans = [p for p in (os.path.join(RES, f"explore{s}_manifest.json") for s in ("", "_r2", "_r3", "_r4"))
            if os.path.exists(p)]
    rows = {r["id"]: r for m in mans for r in load(m)["instances"]}
    recs = [r for st in ("explore", "explore_r2", "explore_r3", "explore_r4") for r in records(st)]
    out = {"targets": targets, "families": {}, "rule": "protocol 3.4"}
    for fam in NEW:
        pts = []
        for r in recs:
            row = rows.get(r["instance"])
            if not row or row["family"] != fam:
                continue
            cpu = r["cpu"] if solved(r) else 3600.0
            pts.append({"size": row["size"], "params": row.get("params") or {}, "cpu": cpu, "solved": bool(solved(r)),
                        "status": r["status"]})
        d = {"points": sorted(pts, key=lambda p: (json.dumps(p["params"], sort_keys=True), p["size"]))}
        if fam in SECONDARY:
            key = SECONDARY[fam]
            vals = GEN11[fam]["grid"][key]
            frac = {}
            for v in vals:
                pv = [p for p in pts if p["params"].get(key) == v]
                frac[v] = sum(1 for p in pv if p["solved"] and 1.0 <= p["cpu"] <= 600.0) / max(1, len(pv))
            mid = vals[len(vals) // 2]
            best = max(vals, key=lambda v: (frac[v], v == mid))
            d.update(secondary={"param": key, "fraction_in_1_600": frac, "chosen": best})
            use = [p for p in pts if p["params"].get(key) == best]
        else:
            use = pts
        a, b = fit([(p["size"], p["cpu"]) for p in use])
        d["fit"] = {"intercept": a, "slope": b, "log": "natural"}
        d["coverage"] = {"all_below_1s": all(p["cpu"] < 1 for p in use), "all_above_600s": all(p["cpu"] > 600 for p in use)}
        if b is not None and b > 0:
            d["candidates"] = pick_sizes(fam, a, b, targets)
        out["families"][fam] = d
    v10 = load(os.path.join(ROOT, "configs", "cross_scale_v10", "scales.json"))["details"]
    for fam in BRIDGE:
        f = v10[fam]["fit"]
        out["families"][fam] = {"fit": {"intercept": f["intercept"], "slope": f["slope"], "log": "natural",
                                        "source": "configs/cross_scale_v10/scales.json (geometric-mean fit of v9/v10 D runs)"},
                                "candidates": pick_sizes(fam, f["intercept"], f["slope"], targets)}
    dump(os.path.join(CFG, "scales_candidate.json"), out)
    for fam, d in out["families"].items():
        print(fam, d.get("secondary", {}).get("chosen"), d.get("candidates"), d.get("coverage"))


# ------------------------------------------------------------------ pilot (protocol 3.5)

def chosen_params(fam, sc):
    d = sc["families"][fam]
    return {d["secondary"]["param"]: d["secondary"]["chosen"]} if d.get("secondary") else None


def pilot_gen(only=None, skip=None, out="pilot_gen.json"):
    sc = load(os.path.join(CFG, "scales_candidate.json"))
    rows = []
    for fam in FAMS:
        if (only and fam not in only) or (skip and fam in skip):
            continue
        for lv in LEVELS:
            size = sc["families"][fam]["candidates"][lv]
            for k in range(PANEL["pilot"]["per_cell"]):
                s = PANEL["pilot"]["seed_start"] + k
                r = {"id": f"v11p-{fam}-{lv}-s{s}", "family": fam, "size": size, "seed": s, "level": lv, "role": "pilot"}
                p = chosen_params(fam, sc)
                if p:
                    r["params"] = p
                rows.append(r)
    dump(os.path.join(CFG, out), {"instances": rows})
    print(len(rows), "pilot instances")


def pilot_decide():
    sc = load(os.path.join(CFG, "scales_candidate.json"))
    rows = {r["id"]: r for m in ("pilot_manifest.json", "pilot_jssp_manifest.json") if os.path.exists(os.path.join(RES, m))
            for r in load(os.path.join(RES, m))["instances"]}
    recs = records("pilot") + records("pilot_jssp")
    bands = PANEL["pilot_bands"]
    out = {"rule": "protocol 3.5", "families": {}}
    for fam in FAMS:
        cand = sc["families"][fam]["candidates"]
        g = grid(fam)
        lv_out, sizes = {}, {}
        for lv in LEVELS:
            rs = [r for r in recs if rows[r["instance"]]["family"] == fam and rows[r["instance"]]["level"] == lv]
            cpus = sorted(r["cpu"] if solved(r) else 3600.0 for r in rs)
            med = statistics.median(cpus) if cpus else None
            started = sum(1 for r in rs if (r.get("stats") or {}).get("conflicts"))
            lo, hi = bands[lv]
            size = cand[lv]
            rule = "kept (in band)"
            if med is not None and not (lo <= med <= hi):
                i = g.index(size)
                j = i + 1 if med < lo else i - 1
                if 0 <= j < len(g):
                    size, rule = g[j], f"moved one grid step ({'up' if med < lo else 'down'}) from {cand[lv]}"
                else:
                    rule = "out of band at the grid end (disclosed)"
            lv_out[lv] = {"candidate": cand[lv], "cpu": cpus, "median": med, "solved": sum(1 for r in rs if solved(r)),
                          "n": len(rs), "reached_search": started, "statuses": sorted(r["status"] for r in rs),
                          "rule": rule}
            sizes[lv] = size
        if not (sizes["S"] < sizes["M"] < sizes["L"]):
            for lv in LEVELS:
                if sizes[lv] != cand[lv]:
                    lv_out[lv]["rule"] += "; order S < M < L violated -> candidate kept"
                    sizes[lv] = cand[lv]
        for lv in LEVELS:
            lv_out[lv]["size"] = sizes[lv]
        out["families"][fam] = {"levels": lv_out, "params": chosen_params(fam, sc)}
    dump(os.path.join(CFG, "scales.json"), out)
    for fam, d in out["families"].items():
        print(fam, {lv: (v["size"], round(v["median"], 2) if v["median"] is not None else None, v["rule"])
                    for lv, v in d["levels"].items()}, d["params"])


# ------------------------------------------------------------------ formal panels (protocol 3.6)

def formal_gen():
    sc = load(os.path.join(CFG, "scales.json"))
    rows = []
    for panel in ("discovery", "development", "confirmation"):
        pr = PANEL["panels"][panel]
        for fam in FAMS:
            for lv in LEVELS:
                d = sc["families"][fam]
                for k in range(pr["per_cell"]):
                    s = pr["seed_start"] + k
                    r = {"id": f"v11-{fam}-{lv}-s{s}", "family": fam, "size": d["levels"][lv]["size"], "seed": s,
                         "level": lv, "role": panel}
                    if d.get("params"):
                        r["params"] = d["params"]
                    if panel == "confirmation":
                        r["block"] = block_of(lv, k)
                    rows.append(r)
    dump(os.path.join(CFG, "formal_gen.json"), {"instances": rows})
    print(len(rows), "formal instances")


def block_of(lv, k):
    b = PANEL["confirmation_blocks"]
    n = 0
    for h in ("H1", "H2", "H3"):
        n += b[h][lv]
        if k < n:
            return h
    raise ValueError((lv, k))


def variants_gen():
    man = load(os.path.join(RES, "formal_manifest.json"))["instances"]
    disc = sorted((r for r in man if r["role"] == "discovery"), key=lambda r: (r["family"], r["level"], r["seed"]))
    base, seeds = [], []
    for fam in FAMS:
        for lv in LEVELS:
            cell = [r for r in disc if r["family"] == fam and r["level"] == lv]
            base += cell[:2]
            seeds.append(cell[0])
    alt = {"col3": "log", "vcover": "totalizer", "jssp": "time", "qcp": "extended"}
    var = []
    for r in base:
        if r["family"] in alt:
            var.append({"id": r["id"] + "-enc" + alt[r["family"]], "base": r["id"], "op": "enc:" + alt[r["family"]], "seed": 0})
        var.append({"id": r["id"] + "-flipall", "base": r["id"], "op": "flipall", "seed": 0})
        var.append({"id": r["id"] + "-perm1", "base": r["id"], "op": "perm", "seed": 1})
    dump(os.path.join(CFG, "variants_gen.json"), {"base_manifests": ["results/broad_scope_v11/formal_manifest.json"],
                                                  "base": [r["id"] for r in base], "variants": var,
                                                  "seed_repeat_base": [r["id"] for r in seeds]})
    print(len(base), "base,", len(var), "variants,", len(seeds), "seed-repeat base")


# ------------------------------------------------------------------ generic run plan

def plan(manifests, stage, methods, measure, seeds, ids_from, roles, wrapper_strats):
    rows = []
    for m in manifests:
        rows += load(m)["instances"]
    if ids_from:
        want = load(ids_from)
        want = set(want if isinstance(want, list) else want.get("ids") or want.get("seed_repeat_base"))
        rows = [r for r in rows if r["id"] in want]
    if roles:
        rows = [r for r in rows if r.get("role") in roles]
    jobs = []
    for r in rows:
        base = {"instance": r["id"], "sha256": r["sha256"], "rep": 0}
        if r.get("path") and not r["path"].startswith("broad_scope_v11/cnf/"):
            base["cnf"] = os.path.join(DATA, r["path"])
        if r.get("family") in GENERATED and r.get("op") not in ("flipall", "perm"):
            base["keep_model"] = True
        for s in seeds:
            for a in methods:
                j = dict(base, method=a)
                if s:
                    j["seed"] = s
                jobs.append(j)
        if measure:
            jobs.append(dict(base, method="MEASURE", measure=MEASURE))
        for st in wrapper_strats:
            j = dict(base, method="W", strategy=st["strategy"])
            if st.get("wrapper"):
                j["wrapper"] = st["wrapper"]
            jobs.append(j)
    dump(os.path.join(CFG, "plans", stage + ".json"), {"stage": stage, "jobs": jobs})
    print(stage, len(jobs), "jobs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--extra")
    ap.add_argument("--manifest", action="append")
    ap.add_argument("--stage")
    ap.add_argument("--methods", default="")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--ids-from")
    ap.add_argument("--roles")
    ap.add_argument("--strategy", action="append", default=[], help="path[:wrapper]")
    ap.add_argument("--only")
    ap.add_argument("--skip")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "explore-gen":
        explore_gen(a.round, json.loads(a.extra) if a.extra else None)
    elif a.cmd == "explore-decide":
        explore_decide()
    elif a.cmd == "pilot-gen":
        pilot_gen(a.only.split(",") if a.only else None, a.skip.split(",") if a.skip else None, a.out or "pilot_gen.json")
    elif a.cmd == "pilot-decide":
        pilot_decide()
    elif a.cmd == "formal-gen":
        formal_gen()
    elif a.cmd == "variants-gen":
        variants_gen()
    elif a.cmd == "plan":
        strats = []
        for s in a.strategy:
            p, _, w = s.partition(":")
            strats.append({"strategy": p, "wrapper": w or None})
        plan(a.manifest, a.stage, [m for m in a.methods.split(",") if m], a.measure,
             [int(x) for x in a.seeds.split(",")], a.ids_from, set(a.roles.split(",")) if a.roles else None, strats)
    else:
        raise SystemExit("unknown command " + a.cmd)


if __name__ == "__main__":
    main()
