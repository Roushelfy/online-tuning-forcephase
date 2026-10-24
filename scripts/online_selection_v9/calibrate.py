#!/usr/bin/env python3
"""v9 pilot plans and scale / structure calibration (docs/ONLINE_SELECTION_PROTOCOL_V9.md section 2.2).
Standard library only.

  calibrate.py gen-r1                               -> configs/online_selection_v9/pilot_r1_gen.json
  calibrate.py run-plan --manifest M --stage S      -> configs/online_selection_v9/<S>.json (D/Fp/Fm, no caps)
  calibrate.py gen-r2                               -> assign2 structure round D/E/F (protocol deviation 2)
  calibrate.py analyze [--write-r3]                 -> pilot costs; assign2 structure + scale round-3 plan
  calibrate.py final                                -> configs/online_selection_v9/scales.json
Pilot runs are never capped (resource policy); a run still going counts as '>= its current CPU' once it
has passed 600 s (decision rule), read from the stage heartbeat.
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
CFG = os.path.join(ROOT, "configs", "online_selection_v9")
RES = os.path.join(ROOT, "results", "online_selection_v9")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
RUNS = os.path.join(DATA, "runs", "online_selection_v9")
P = json.load(open(os.path.join(CFG, "protocol.json")))
G = json.load(open(os.path.join(CFG, "generators.json")))
PIL = P["pilot"]
TI, SI = P["type_index"], P["scale_index"]
SCALES = ("S", "M", "L")
BANDS, TARGETS = PIL["bands_cpu_seconds"], PIL["targets_cpu_seconds"]
KEEP_V8_OVERRIDE = {"col3-L"}  # protocol section 12, deviation 1


def seed(rnd, t, cell, rep):
    return 9000000 + 1000 * rnd + 100 * TI[t] + 10 * cell + rep


def gen_r1():
    r1 = PIL["round1"]
    inst = []
    for t in ("rand3", "col3"):
        for s in SCALES:
            for k in range(r1["replicates"]):
                inst.append({"id": f"v9p-r1-{t}-{s}-{k}", "type": t, "scale": s, "param": r1[t][s],
                             "seed": seed(1, t, SI[s], k), "round": 1})
    a = r1["assign2"]
    cell = 0
    for st in a["structures"]:
        for T in a["T"]:
            for k in range(a["replicates"]):
                inst.append({"id": f"v9p-r1-assign2-{st}-T{T}-{k}", "type": "assign2", "structure": st, "param": T,
                             "seed": seed(1, "assign2", cell, k), "round": 1})
            cell += 1
    json.dump({"stage": "pilot_r1", "instances": inst}, open(os.path.join(CFG, "pilot_r1_gen.json"), "w"), indent=1)
    print(len(inst))


def run_plan(manifest, stage):
    man = json.load(open(manifest))
    jobs = [{"instance": r["id"], "sha256": r["sha256"], "method": m, "rep": 0}
            for r in man["instances"] for m in ("D", "Fp", "Fm")]
    json.dump({"stage": stage, "manifest": os.path.relpath(manifest, ROOT), "jobs": jobs},
              open(os.path.join(CFG, f"{stage}.json"), "w"), indent=1)
    print(stage, len(jobs))


def stage_state(stage):
    """{(instance, method): (cpu, status, record or None)} incl. running jobs from the heartbeat."""
    d = os.path.join(RUNS, stage)
    out = {}
    for p in glob.glob(os.path.join(d, "*.json")):
        if p.endswith(("progress.json", "effective_plan.json")):
            continue
        r = json.load(open(p))
        out[(r["instance"], r["method"])] = (r["cpu"], r["status"], r)
    hb = os.path.join(d, "progress.json")
    ep = os.path.join(d, "effective_plan.json")
    if os.path.exists(hb) and os.path.exists(ep):
        sys.path.insert(0, HERE)
        import runner  # noqa: E402
        ids = {runner.job_key(j, stage)[1]: j for j in json.load(open(ep))["jobs"]}
        for j in json.load(open(hb)).get("jobs", []):
            spec = ids.get(j["id"])
            if spec and (spec["instance"], spec["method"]) not in out:
                out[(spec["instance"], spec["method"])] = (j["cpu"], "running", None)
    return out


def points():
    rows = []
    for rnd in (1, 2, 3):
        mp = os.path.join(RES, f"pilot_r{rnd}_manifest.json")
        if not os.path.exists(mp):
            continue
        st = stage_state(f"pilot_r{rnd}")
        for m in json.load(open(mp))["instances"]:
            v = [st.get((m["id"], a)) for a in ("D", "Fp", "Fm")]
            row = {k: m.get(k) for k in ("id", "type", "scale", "structure", "param", "round", "vars", "clauses")}
            if any(x is None for x in v):
                row.update(c=None, decided=False)
            else:
                cpus = [x[0] for x in v]
                done = [x[1] == "solved" for x in v]
                row.update(c=sum(cpus) / 3, sum3=sum(cpus), complete=all(done),
                           decided=all(d or c >= 600 for d, c in zip(done, cpus)),
                           times=dict(zip(("D", "Fp", "Fm"), cpus)), statuses=dict(zip(("D", "Fp", "Fm"), [x[1] for x in v])),
                           conflicts_D=((v[0][2] or {}).get("stats") or {}).get("conflicts"),
                           answer={10: "SAT", 20: "UNSAT"}.get((v[0][2] or {}).get("exit_code")))
            rows.append(row)
    return rows


def gidx(t, p):
    return G[t]["grid"].index(p)


def in_band(c, s):
    return c is not None and BANDS[s][0] <= c <= BANDS[s][1]


def bracket_choice(t, s, pts):
    """v8 deviation-2 rule: in-band point closest to target; else interpolate between bracketing points;
    else extrapolate from the nearest point with the least-squares slope (log c per grid step)."""
    tgt = math.log(TARGETS[s])
    cand = [r for r in pts if in_band(r["c"], s)]
    if cand:
        return gidx(t, min(cand, key=lambda r: abs(math.log(r["c"]) - tgt))["param"])
    a, b = BANDS[s]
    below = [r for r in pts if r["c"] < a]
    above = [r for r in pts if r["c"] > b]
    if below and above:
        lo = max(below, key=lambda r: gidx(t, r["param"]))
        hi = min(above, key=lambda r: gidx(t, r["param"]))
        gl, gh = gidx(t, lo["param"]), gidx(t, hi["param"])
        if gl < gh:
            if gh - gl >= 2:
                pos = gl + (tgt - math.log(lo["c"])) / (math.log(hi["c"]) - math.log(lo["c"])) * (gh - gl)
                return min(gh - 1, max(gl + 1, int(round(pos))))
            return gidx(t, min((lo, hi), key=lambda r: (abs(math.log(r["c"]) - tgt), r["c"]))["param"])
    xs = [gidx(t, r["param"]) for r in pts]
    ys = [math.log(max(r["c"], 1e-3)) for r in pts]
    sl = 0.0
    if len(set(xs)) >= 2:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sl = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    ref = min(pts, key=lambda r: abs(math.log(max(r["c"], 1e-3)) - tgt))
    g = gidx(t, ref["param"])
    if sl <= 0.05:
        g2 = g + (3 if tgt > math.log(max(ref["c"], 1e-3)) else -3)
    else:
        g2 = int(round(g + (tgt - math.log(max(ref["c"], 1e-3))) / sl))
    return max(0, min(len(G[t]["grid"]) - 1, g2))


def order(t, idx):
    n = len(G[t]["grid"])
    out = dict(idx)
    for a, b in (("S", "M"), ("M", "L")):
        if out[b] <= out[a]:
            out[b] = min(n - 1, out[a] + 1)
    if not out["S"] < out["M"] < out["L"]:
        raise SystemExit(f"{t}: cannot order {out}")
    return out


def snap(t, T):
    return min(G[t]["grid"], key=lambda g: (abs(math.log(g) - math.log(T)), g))


def choose_structure(rows):
    r1 = [r for r in rows if r["type"] == "assign2" and r["round"] in (1, 2)]
    score = {}
    for st in G["assign2"]["structures"]:
        rs = [r for r in r1 if r["structure"] == st and r["c"] is not None]
        n_ok = sum(1 for r in rs if 1 <= r["c"] <= 600 and (r.get("conflicts_D") or 0) >= 1e4)
        both = len({r.get("answer") for r in rs} & {"SAT", "UNSAT"}) == 2
        med = statistics.median(math.log(max(r["c"], 1e-3)) for r in rs) if rs else 99
        score[st] = (-n_ok, 0 if both else 1, abs(med - math.log(10)), "ABCDEF".index(st))
    best = min(score, key=lambda s: score[s])
    return best, score


def assign2_scales(rows, st):
    rs = [r for r in rows if r["type"] == "assign2" and r["round"] in (1, 2) and r["structure"] == st]
    by = {}
    for r in rs:
        by.setdefault(r["param"], []).append(r["c"])
    Ts = sorted(by)
    med = {T: statistics.median(by[T]) for T in Ts}
    sl = (math.log(med[Ts[1]]) - math.log(med[Ts[0]])) / (math.log(Ts[1]) - math.log(Ts[0]))
    if sl <= 0:
        return dict(PIL["assign2_fallback_scales"]), sl
    out = {}
    for s in SCALES:
        T = Ts[0] * math.exp((math.log(TARGETS[s]) - math.log(med[Ts[0]])) / sl)
        out[s] = snap("assign2", T)
    idx = order("assign2", {s: gidx("assign2", out[s]) for s in SCALES})
    return {s: G["assign2"]["grid"][idx[s]] for s in SCALES}, sl


def gen_r2():
    inst, cell = [], 0
    for st in ("D", "E", "F"):
        for T in (250, 400):
            for k in range(2):
                inst.append({"id": f"v9p-r2-assign2-{st}-T{T}-{k}", "type": "assign2", "structure": st, "param": T,
                             "seed": seed(2, "assign2", cell, k), "round": 2})
            cell += 1
    json.dump({"stage": "pilot_r2", "note": "protocol deviation 2: assign2 structure round", "instances": inst},
              open(os.path.join(CFG, "pilot_r2_gen.json"), "w"), indent=1)
    print(len(inst))


def analyze(write):
    rows = points()
    for r in rows:
        print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()
                          if k not in ("times", "statuses")}))
    if not all(r["decided"] for r in rows):
        print("pilot not yet decidable:", [r["id"] for r in rows if not r["decided"]])
        return
    if write:
        st, score = choose_structure(rows)
        sc, sl = assign2_scales(rows, st)
        print("assign2 structure", st, score, "scales", sc, "slope", sl)
        inst = [{"id": f"v9p-r3-assign2-{st}-{s}-{k}", "type": "assign2", "structure": st, "scale": s, "param": sc[s],
                 "seed": seed(3, "assign2", SI[s], k), "round": 3}
                for s in SCALES for k in range(PIL["round2_assign2_replicates"])]
        json.dump({"stage": "pilot_r3", "structure": st, "structure_score": score, "slope_loglog": sl,
                   "instances": inst}, open(os.path.join(CFG, "pilot_r3_gen.json"), "w"), indent=1)


def final():
    rows = points()
    if not all(r["decided"] for r in rows):
        raise SystemExit("pilot not decidable yet")
    out = {"params": {}, "details": {}}
    for t in ("rand3", "col3"):
        out["params"][t] = {}
        for s in SCALES:
            rs = [r for r in rows if r["type"] == t and r["scale"] == s]
            med = statistics.median(r["c"] for r in rs)
            lo, hi = BANDS[s][0] / 5, BANDS[s][1] * 5
            keep = lo <= med <= hi or f"{t}-{s}" in KEEP_V8_OVERRIDE  # deviation 1 (col3-L)
            p = PIL["round1"][t][s]
            if not keep:
                pts = [r for r in rows if r["type"] == t]
                p = G[t]["grid"][bracket_choice(t, s, pts)]
            out["params"][t][s] = p
            out["details"][f"{t}-{s}"] = {"median_c": med, "kept_v8": keep, "range": [lo, hi]}
    r3 = json.load(open(os.path.join(CFG, "pilot_r3_gen.json")))
    st = r3["structure"]
    pts = [r for r in rows if r["type"] == "assign2" and r["structure"] == st]
    idx = {}
    for s in SCALES:
        rs = [r for r in pts if r["round"] == 3 and r["scale"] == s]
        med = statistics.median(r["c"] for r in rs)
        if in_band(med, s):
            idx[s] = gidx("assign2", rs[0]["param"])
        else:
            byT = {}
            for r in pts:
                byT.setdefault(r["param"], []).append(r["c"])
            mpts = [{"param": T, "c": statistics.median(v)} for T, v in byT.items()]
            idx[s] = bracket_choice("assign2", s, mpts)
        out["details"][f"assign2-{s}"] = {"round3_median_c": med, "in_band": in_band(med, s)}
    idx = order("assign2", idx)
    out["params"]["assign2"] = {s: G["assign2"]["grid"][idx[s]] for s in SCALES}
    out["assign2_structure"] = st
    out["params"]["assign0"] = P["formal"]["controls"]["T"]
    TL = out["params"]["assign2"]["L"]
    out["extrapolation"] = {"rand3": P["formal"]["extrapolation"]["rand3"], "col3": P["formal"]["extrapolation"]["col3"],
                            "assign2": [snap25(1.2 * TL), snap25(1.4 * TL)]}
    json.dump(out, open(os.path.join(CFG, "scales.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


def snap25(x):
    g = G["assign2"]["grid"]
    if x <= g[-1]:
        return min((v for v in g if v >= x), default=g[-1])
    return int(math.ceil(x / 25.0) * 25)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-r1")
    sub.add_parser("gen-r2")
    r = sub.add_parser("run-plan")
    r.add_argument("--manifest", required=True)
    r.add_argument("--stage", required=True)
    an = sub.add_parser("analyze")
    an.add_argument("--write-r3", action="store_true")
    sub.add_parser("final")
    a = ap.parse_args()
    if a.cmd == "gen-r1":
        gen_r1()
    elif a.cmd == "run-plan":
        run_plan(a.manifest, a.stage)
    elif a.cmd == "gen-r2":
        gen_r2()
    elif a.cmd == "analyze":
        analyze(a.write_r3)
    else:
        final()


if __name__ == "__main__":
    main()
