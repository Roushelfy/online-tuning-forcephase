#!/usr/bin/env python3
"""Goal v10 generation and run plans (docs/CROSS_SCALE_PROTOCOL_V10.md sections 3, 5, 8). Standard library only.

  plans.py pilot-gen                 configs/cross_scale_v10/pilot_gen.json from scales_candidate.json
  plans.py pilot-plan                plans/pilot.json (D only) from results/cross_scale_v10/pilot_manifest.json
  plans.py pilot-decide              scales.json by the pre-registered pilot rule (protocol section 3.3)
  plans.py formal-gen                formal_gen.json (3 types x 3 dev levels x 60 + 3 types x 30 extrapolation)
  plans.py formal-plans              split.json, panel lists, plans/s1_dev.json, plans/measure_dev.json,
                                     robust_variants.json (54 renaming variants)
  plans.py robust-plan               plans/robust_dev.json (seed 1 and renaming variants x D/F+/F-)
  plans.py deploy-plans              after the rule freeze: plans/confirm.json, extrap.json, external.json, deploy_dev.json
"""
import argparse
import glob
import hashlib
import json
import math
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "cross_scale_v10")
RES = os.path.join(ROOT, "results", "cross_scale_v10")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "cross_scale_v10")
TYPES = ("rand3", "col3", "assign2")
LEVELS = ("S", "M", "L", "X")
DEV_LEVELS = ("S", "M", "L")
GEN9 = json.load(open(os.path.join(ROOT, "configs", "online_selection_v9", "generators.json")))
MEASURE = {"static": True, "probes": [{"arm": "D", "tau": t} for t in (0.1, 0.5, 2.0, 5.0)]
           + [{"arm": a, "tau": t} for a in ("Fp", "Fm") for t in (0.1, 0.5, 2.0)]}
BANDS = {"S": (0.05, 2.0, 0.3), "M": (0.5, 20.0, 3.0), "L": (2.0, 200.0, 30.0)}
X_MAX_D = 1200.0


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")


def structure(t):
    return "F" if t == "assign2" else None


def split_hash(i):
    return hashlib.sha256((i + ":v10split").encode()).hexdigest()


def records(stage):
    out = []
    for p in glob.glob(os.path.join(RUNS, stage, "*.json")):
        if not p.endswith(("progress.json", "effective_plan.json")):
            out.append(json.load(open(p)))
    return out


# ------------------------------------------------------------------ pilot

def pilot_gen():
    sc = json.load(open(os.path.join(CFG, "scales_candidate.json")))["params"]
    inst = []
    for ti, t in enumerate(TYPES):
        for li, lv in enumerate(LEVELS):
            for j in range(6):
                inst.append({"id": f"v10p-{t}-{lv}-{j}", "type": t, "level": lv, "param": sc[t][lv],
                             "seed": 10900000 + 1000 * ti + 100 * li + j, "structure": structure(t), "role": "pilot"})
    dump(os.path.join(CFG, "pilot_gen.json"), {"stage": "pilot", "instances": inst})
    print(len(inst), "pilot instances")


def plan_from_manifest(man, ids, methods, stage, extra=None):
    rows = {r["id"]: r for r in json.load(open(man))["instances"]}
    jobs = []
    for i in ids:
        for m in methods:
            j = {"instance": i, "sha256": rows[i]["sha256"], "method": m, "rep": 0}
            j.update(extra or {})
            jobs.append(j)
    return {"stage": stage, "jobs": jobs}


def queue_order(rows, key_rank):
    lv_order = {"L": 0, "M": 1, "S": 2, "X": 3}
    return sorted(rows, key=lambda r: (lv_order[r["level"]], TYPES.index(r["type"]), key_rank(r)))


def pilot_plan():
    man = os.path.join(RES, "pilot_manifest.json")
    rows = queue_order(json.load(open(man))["instances"], lambda r: r["id"])
    dump(os.path.join(CFG, "plans", "pilot.json"), plan_from_manifest(man, [r["id"] for r in rows], ["D"], "pilot"))


def v9_points():
    """(type, param) -> list of v9 D CPU (dev, holdout, extrapolation, pilots; assign2 structure F only)."""
    rows = {}
    for m in ("formal_manifest.json", "pilot_r1_manifest.json", "pilot_r2_manifest.json", "pilot_r3_manifest.json"):
        for r in json.load(open(os.path.join(ROOT, "results", "online_selection_v9", m)))["instances"]:
            rows[r["id"]] = r
    pts = {}
    for st in ("s1_dev", "holdout", "extrap", "pilot_r1", "pilot_r2", "pilot_r3"):
        for p in glob.glob(os.path.join(DATA, "runs", "online_selection_v9", st, "*.json")):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            r = json.load(open(p))
            m = rows.get(r["instance"])
            if not m or r["method"] != "D" or r.get("seed", 0) or m["type"] not in TYPES:
                continue
            if m["type"] == "assign2" and m.get("structure", "F") != "F":
                continue
            pts.setdefault((m["type"], m["param"]), []).append(min(r["cpu"], 3600.0))
    return pts


def geo(xs):
    return math.exp(statistics.mean(math.log(max(x, 1e-3)) for x in xs))


def pilot_decide():
    cand = json.load(open(os.path.join(CFG, "scales_candidate.json")))["params"]
    man = {r["id"]: r for r in json.load(open(os.path.join(RES, "pilot_manifest.json")))["instances"]}
    cpu = {}
    for r in records("pilot"):
        if r["method"] == "D" and r["instance"] in man:
            cpu[r["instance"]] = (min(r["cpu"], 3600.0), r["status"])
    # a run still in progress counts with its current CPU as a lower bound (like a run past 3600 s); used only when
    # the rule's outcome cannot depend on the final value (checked below)
    prog = os.path.join(RUNS, "pilot", "progress.json")
    running = {}
    if os.path.exists(prog):
        ids_by_run = {}
        plan = json.load(open(os.path.join(CFG, "plans", "pilot.json")))
        eff = os.path.join(RUNS, "pilot", "effective_plan.json")
        for j in json.load(open(eff))["jobs"] if os.path.exists(eff) else plan["jobs"]:
            ids_by_run[j["instance"]] = j
        for j in json.load(open(prog))["jobs"]:
            running[j["id"]] = j["cpu"]
    lower_bound_ids = []
    if len(cpu) < len(man) and running:
        import sys as _s
        _s.path.insert(0, HERE)
        import runner as _r  # job ids are computed exactly as the runner does
        for spec in json.load(open(os.path.join(RUNS, "pilot", "effective_plan.json")))["jobs"]:
            _, jid = _r.job_key(spec, "pilot")
            if spec["instance"] not in cpu and jid in running:
                cpu[spec["instance"]] = (min(running[jid], 3600.0), "running (lower bound)")
                lower_bound_ids.append(spec["instance"])
    v9 = v9_points()
    out, detail = {t: {} for t in TYPES}, {}
    for t in TYPES:
        pts = [(p, geo(xs), len(xs)) for (tt, p), xs in v9.items() if tt == t and len(xs) >= 10]
        lv_stats = {}
        for lv in LEVELS:
            xs = [cpu[i][0] for i in man if man[i]["type"] == t and man[i]["level"] == lv and i in cpu]
            if len(xs) != 6:
                raise SystemExit(f"pilot {t} {lv}: {len(xs)} of 6 records")
            lv_stats[lv] = {"param": cand[t][lv], "geo": geo(xs), "max": max(xs), "cpu": sorted(xs),
                            "statuses": sorted(cpu[i][1] for i in man if man[i]["type"] == t and man[i]["level"] == lv)}
            pts.append((cand[t][lv], lv_stats[lv]["geo"], 6))
        # least squares of ln(geo) on the size parameter, one point per (source, param)
        xs, ys = [p for p, _, _ in pts], [math.log(g) for _, g, _ in pts]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        a0 = my - b * mx
        grid = GEN9[t]["grid"]
        new = dict(cand[t])
        for lv in DEV_LEVELS:
            lo, hi, target = BANDS[lv]
            g = lv_stats[lv]["geo"]
            if lo <= g <= hi or b <= 0:
                lv_stats[lv]["rule"] = "kept (in band)" if lo <= g <= hi else "kept (non-positive slope)"
                continue
            want = (math.log(target) - a0) / b
            new[lv] = min(grid, key=lambda p: (abs(p - want), p))
            lv_stats[lv]["rule"] = f"moved: fitted param for {target} s = {want:.1f} -> grid {new[lv]}"
        xs_ = lv_stats["X"]
        if xs_["max"] > X_MAX_D:
            below = [p for p in grid if new["L"] < p < cand[t]["X"]]
            new["X"] = max(below) if below else min(p for p in grid if p > new["L"])
            xs_["rule"] = f"pilot max D {xs_['max']:.0f} s > {X_MAX_D:.0f} s -> one grid step down: {new['X']}"
        else:
            xs_["rule"] = "kept (pilot max D within coverage bound)"
        if not (new["S"] < new["M"] < new["L"] < new["X"]):
            for lv in LEVELS:
                lv_stats[lv]["rule"] += "; order violated -> candidate kept"
            new = dict(cand[t])
        out[t] = new
        detail[t] = {"levels": lv_stats, "fit": {"intercept": a0, "slope": b, "points": pts}}
    for i in lower_bound_ids:  # the outcome must not depend on the unfinished value
        t, lv = man[i]["type"], man[i]["level"]
        if lv != "X" or detail[t]["levels"]["X"]["max"] <= X_MAX_D:
            raise SystemExit(f"{i} still running and the rule outcome could depend on it; wait")
    dump(os.path.join(CFG, "scales.json"), {"params": out, "details": detail, "bands": BANDS, "x_max_d": X_MAX_D,
                                             "assign2_structure": "F", "lower_bound_runs": lower_bound_ids})
    print(json.dumps(out))


# ------------------------------------------------------------------ formal panels

def formal_gen():
    sc = json.load(open(os.path.join(CFG, "scales.json")))["params"]
    inst = []
    for ti, t in enumerate(TYPES):
        for li, lv in enumerate(LEVELS):
            n = 30 if lv == "X" else 60
            for j in range(n):
                inst.append({"id": f"v10-{t}-{lv}-{j:02d}", "type": t, "level": lv, "param": sc[t][lv],
                             "seed": 10000000 + 100000 * ti + 10000 * li + j, "structure": structure(t),
                             "role": "extrapolation" if lv == "X" else "core"})
    dump(os.path.join(CFG, "formal_gen.json"), {"stage": "formal", "instances": inst})
    print(len(inst), "formal instances")


def dedupe_audit():
    """SHA-256, clause-set and renaming-invariant hashes: v10 (pilot + formal) against each other and against every
    v8 / v9 manifest. Any collision stops the pipeline (protocol section 3.4)."""
    seen, coll, n = {}, [], 0
    mans = (sorted(glob.glob(os.path.join(ROOT, "results", "stratified_v8", "*manifest.json")))
            + sorted(glob.glob(os.path.join(ROOT, "results", "online_selection_v9", "*manifest.json")))
            + [os.path.join(RES, "pilot_manifest.json"), os.path.join(RES, "formal_manifest.json")])
    for mp in mans:
        if not os.path.exists(mp):
            continue
        for r in json.load(open(mp)).get("instances", []):
            n += mp.startswith(RES)
            for k in ("sha256", "canonical_sha256", "invariant_sha256"):
                if not r.get(k):
                    continue
                tag = os.path.relpath(mp, ROOT) + ":" + r["id"]
                if (k, r[k]) in seen and seen[(k, r[k])] != tag and mp.startswith(RES):  # collisions involving v10
                    coll.append({"hash": k, "a": seen[(k, r[k])], "b": tag})
                seen.setdefault((k, r[k]), tag)
    out = {"manifests": [os.path.relpath(m, ROOT) for m in mans if os.path.exists(m)], "v10_instances": n,
           "collisions": coll}
    dump(os.path.join(RES, "dedupe_audit.json"), out)
    if coll:
        raise SystemExit(f"{len(coll)} hash collisions, see results/cross_scale_v10/dedupe_audit.json")
    print("dedupe audit:", n, "v10 instances, no collisions")


def formal_plans():
    dedupe_audit()
    man_path = os.path.join(RES, "formal_manifest.json")
    rows = json.load(open(man_path))["instances"]
    split, panels = {}, {"dev": [], "confirm": [], "H1": [], "H2": [], "H3": [], "extrapolation": []}
    for t in TYPES:
        for lv in LEVELS:
            cell = sorted((r for r in rows if r["type"] == t and r["level"] == lv), key=lambda r: split_hash(r["id"]))
            for k, r in enumerate(cell):
                if lv == "X":
                    s, blk = "extrapolation", None
                else:
                    s = "dev" if k < 30 else "confirm"
                    blk = None if k < 30 else ("H1", "H2", "H3")[(k - 30) // 10]
                split[r["id"]] = {"type": t, "level": lv, "param": r["param"], "split": s, "block": blk, "rank": k,
                                  "split_hash": split_hash(r["id"]), "fold": k % 5 if s == "dev" else None}
                panels[s].append(r["id"])
                if blk:
                    panels[blk].append(r["id"])
    dump(os.path.join(CFG, "split.json"), split)
    for name, ids in panels.items():
        with open(os.path.join(CFG, f"panel_{name}.txt"), "w") as f:
            f.write(f"# v10 panel {name} ({len(ids)} instances), scripts/cross_scale_v10/plans.py formal-plans\n")
            f.writelines(i + "\n" for i in sorted(ids))
    dev = queue_order([r for r in rows if split[r["id"]]["split"] == "dev"], lambda r: split[r["id"]]["rank"])
    ids = [r["id"] for r in dev]
    dump(os.path.join(CFG, "plans", "s1_dev.json"), plan_from_manifest(man_path, ids, ["D", "Fp", "Fm"], "s1_dev"))
    dump(os.path.join(CFG, "plans", "measure_dev.json"),
         plan_from_manifest(man_path, ids, ["MEASURE"], "measure_dev", {"measure": MEASURE}))
    robust = [r["id"] for r in dev if split[r["id"]]["rank"] < 6]
    dump(os.path.join(CFG, "robust_variants.json"),
         {"variants": [{"id": i + "-perm1", "base": i, "op": "perm", "seed": 1} for i in robust]})
    with open(os.path.join(CFG, "panel_robust.txt"), "w") as f:
        f.write(f"# v10 robustness diagnostic: the 6 lowest-ranked dev instances per cell ({len(robust)})\n")
        f.writelines(i + "\n" for i in sorted(robust))
    print({k: len(v) for k, v in panels.items()}, "robust", len(robust))


def robust_plan():
    man_path = os.path.join(RES, "formal_manifest.json")
    rows = {r["id"]: r for r in json.load(open(man_path))["instances"]}
    var = {v["base"]: v for v in json.load(open(os.path.join(RES, "variants_manifest.json")))["variants"]}
    ids = [l.strip() for l in open(os.path.join(CFG, "panel_robust.txt")) if l.strip() and not l.startswith("#")]
    split = json.load(open(os.path.join(CFG, "split.json")))
    ids = [r["id"] for r in queue_order([rows[i] for i in ids], lambda r: split[r["id"]]["rank"])]
    jobs = []
    for i in ids:
        for m in ("D", "Fp", "Fm"):
            jobs.append({"instance": i, "sha256": rows[i]["sha256"], "method": m, "rep": 0, "seed": 1})
        v = var[i]
        for m in ("D", "Fp", "Fm"):
            jobs.append({"instance": i, "sha256": v["sha256"], "method": m, "rep": 0, "variant": "perm1",
                         "cnf": os.path.join(DATA, v["path"])})
    dump(os.path.join(CFG, "plans", "robust_dev.json"), {"stage": "robust_dev", "jobs": jobs})
    print(len(jobs), "robust jobs")


def deploy_plans():
    """After the rule freeze (protocol section 7.5): fixed arms + frozen wrappers, interleaved per instance."""
    fr = json.load(open(os.path.join(CFG, "frozen", "FREEZE.json")))
    wrappers = [w for w in (fr.get("main_wrapper"), fr.get("reference_wrapper")) if w]
    split = json.load(open(os.path.join(CFG, "split.json")))
    man_path = os.path.join(RES, "formal_manifest.json")
    rows = {r["id"]: r for r in json.load(open(man_path))["instances"]}

    def jobs_for(ids, sha):
        jobs = []
        for i in ids:
            b = {"instance": i, "sha256": sha[i], "rep": 0}
            jobs += [dict(b, method=m) for m in ("D", "Fp", "Fm")]
            jobs += [dict(b, method="W", strategy=w) for w in wrappers]
        return jobs
    sha = {i: r["sha256"] for i, r in rows.items()}
    conf = [i for i in split if split[i]["split"] == "confirm"]
    conf = [r["id"] for r in sorted((rows[i] for i in conf),
                                    key=lambda r: (split[r["id"]]["block"], ("L", "M", "S").index(r["level"]),
                                                   TYPES.index(r["type"]), split[r["id"]]["rank"]))]
    dump(os.path.join(CFG, "plans", "confirm.json"), {"stage": "confirm", "jobs": jobs_for(conf, sha)})
    ext = [r["id"] for r in sorted((rows[i] for i in split if split[i]["split"] == "extrapolation"),
                                   key=lambda r: (TYPES.index(r["type"]), split[r["id"]]["rank"]))]
    dump(os.path.join(CFG, "plans", "extrap.json"), {"stage": "extrap", "jobs": jobs_for(ext, sha)})
    em = json.load(open(os.path.join(RES, "external_manifest.json")))["instances"]
    esha = {r["id"]: r["sha256"] for r in em}
    dump(os.path.join(CFG, "plans", "external.json"), {"stage": "external", "jobs": jobs_for([r["id"] for r in em], esha)})
    dev = [r["id"] for r in queue_order([rows[i] for i in split if split[i]["split"] == "dev"], lambda r: split[r["id"]]["rank"])]
    dump(os.path.join(CFG, "plans", "deploy_dev.json"),
         {"stage": "deploy_dev", "jobs": [{"instance": i, "sha256": sha[i], "rep": 0, "method": "W", "strategy": w}
                                          for i in dev for w in wrappers]})
    print("confirm", len(conf), "extrap", len(ext), "external", len(em), "wrappers", wrappers)


def stress_plans():
    """Optional old-55 stress test (protocol section 9): decompress the 55 competition CNFs, then
    plans/stress_old55.json (55 x frozen wrappers) and plans/stress_old55_fixed.json (3600 s F+ / F- runs for the
    records that only have v6's 300 s bound in the 3600 s view)."""
    import lzma
    out_dir = os.path.join(DATA, "cross_scale_v10", "stress_cnf")
    os.makedirs(out_dir, exist_ok=True)
    ids = [l.split()[0] for l in open(os.path.join(ROOT, "configs", "stable_selection_v6", "validate_hashes.txt"))
           if l.strip() and not l.startswith("#")]
    sha = {}
    for h in ids:
        dst = os.path.join(out_dir, h + ".cnf")
        if not os.path.exists(dst):
            with lzma.open(os.path.join(DATA, "benchmarks", "cnf", h + ".cnf.xz"), "rb") as fi, open(dst + ".tmp", "wb") as fo:
                while True:
                    b = fi.read(1 << 24)
                    if not b:
                        break
                    fo.write(b)
            os.rename(dst + ".tmp", dst)
        hh = hashlib.sha256()
        with open(dst, "rb") as f:
            for b in iter(lambda: f.read(1 << 24), b""):
                hh.update(b)
        sha[h] = hh.hexdigest()
    fr = json.load(open(os.path.join(CFG, "frozen", "FREEZE.json")))
    wrappers = [w for w in (fr.get("main_wrapper"), fr.get("reference_wrapper")) if w]
    jobs = [{"instance": h, "sha256": sha[h], "rep": 0, "method": "W", "strategy": w,
             "cnf": os.path.join(out_dir, h + ".cnf")} for h in ids for w in wrappers]
    dump(os.path.join(CFG, "plans", "stress_old55.json"), {"stage": "stress_old55", "jobs": jobs})
    view = json.load(open(os.path.join(ROOT, "results", "online_selection_v9", "timeout_3600_view.json")))["old55"]["methods"]
    fixed = [{"instance": h, "sha256": sha[h], "rep": 0, "method": m, "cnf": os.path.join(out_dir, h + ".cnf")}
             for m in ("Fp", "Fm") for h in view[m]["not_reconstructable_ids"]]
    dump(os.path.join(CFG, "plans", "stress_old55_fixed.json"), {"stage": "stress_old55_fixed", "jobs": fixed})
    dump(os.path.join(RES, "stress_cnf_sha256.json"), sha)
    print(len(jobs), "wrapper jobs,", len(fixed), "fixed jobs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pilot-gen", "pilot-plan", "pilot-decide", "formal-gen", "formal-plans",
                                    "robust-plan", "deploy-plans", "stress-plans"])
    a = ap.parse_args()
    {"pilot-gen": pilot_gen, "pilot-plan": pilot_plan, "pilot-decide": pilot_decide, "formal-gen": formal_gen,
     "formal-plans": formal_plans, "robust-plan": robust_plan, "deploy-plans": deploy_plans,
     "stress-plans": stress_plans}[a.cmd]()


if __name__ == "__main__":
    main()
