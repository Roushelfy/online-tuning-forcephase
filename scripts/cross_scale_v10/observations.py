#!/usr/bin/env python3
"""Goal v10 S3 descriptive checks (docs/CROSS_SCALE_PROTOCOL_V10.md section 6): coverage, observation cost and
prefix validity on the development set. Descriptive only -- nothing here selects a strategy.

  $FP_PY scripts/cross_scale_v10/observations.py   -> results/cross_scale_v10/observations.json

Prefix validity: on the instances not answered by the probes, Spearman correlation between each arm-difference
feature (F+ - D, F- - D) at tau and the realised log2 cost ratio log2(t_F / t_D) of the complete runs; and the
"most progress wins" heuristic (pick the arm with the highest conflict rate), which the protocol does NOT register
as a strategy -- it shows whether 'fewer / more conflicts' can be read as 'faster'.
"""
import collections
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402
import devlib as L  # noqa: E402


def rank(v):
    o = sorted(range(len(v)), key=lambda k: v[k])
    r = [0.0] * len(v)
    k = 0
    while k < len(o):
        j = k
        while j + 1 < len(o) and v[o[j + 1]] == v[o[k]]:
            j += 1
        for t in range(k, j + 1):
            r[o[t]] = (k + j) / 2.0
        k = j + 1
    return r


def spearman(x, y):
    if len(x) < 5:
        return None
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return sxy / (sx * sy) if sx and sy else None


def main():
    rows = L.dev_table()
    out = {"validity": {}, "greedy_progress": {}, "static_vs_ratio": {}}
    for tau in (0.1, 0.5, 2.0):
        sched = [("D", tau), ("Fp", tau), ("Fm", tau)]
        prs = {i: L.pre(r, True, sched) for i, r in rows.items()}
        U = [i for i in rows if not prs[i].answered and all(prs[i].started.get(a) for a in ("D", "Fp", "Fm"))
             and all(rows[i]["ok"].get(a) for a in L.ACTS)]
        res = {"n": len(U)}
        for tag, a in (("dP_", "Fp"), ("dM_", "Fm")):
            y = [math.log2(rows[i]["t"][a] / rows[i]["t"]["D"]) for i in U]
            for f in common.DIFF:
                xs = [(prs[i].x.get(tag + f), yy) for i, yy in zip(U, y) if prs[i].x.get(tag + f) is not None]
                res[tag + f] = spearman([p for p, _ in xs], [q for _, q in xs])
            # within-cell correlations (does the signal survive beyond type / scale?)
            by = collections.defaultdict(list)
            for i, yy in zip(U, y):
                v = prs[i].x.get(tag + "conf_rate")
                if v is not None:
                    by[L.cell(rows[i])].append((v, yy))
            res[tag + "conf_rate_within_cell"] = {f"{c[0]}-{c[1]}": spearman([p for p, _ in v], [q for _, q in v])
                                                   for c, v in sorted(by.items())}
        out["validity"][str(tau)] = res
        # greedy: arm with the highest conflict rate in its prefix, from scratch (descriptive)
        tot, n = collections.Counter(), 0
        for i in U:
            best = max(("D", "Fp", "Fm"), key=lambda a: prs[i].x.get(common.PREFIX[a] + "conf_rate") or -1)
            for a in ("greedy",) + L.ACTS:
                act = best if a == "greedy" else a
                tot[a] += rows[i]["t"][act]
            n += 1
        out["greedy_progress"][str(tau)] = {"n": n, "total_after_probes": dict(tot)}
    # static: correlation of each static feature with log2(t_Fp / t_D) on all solved dev instances (type proxies)
    U = [i for i in rows if all(rows[i]["ok"].get(a) for a in L.ACTS)]
    for a in ("Fp", "Fm"):
        y = [math.log2(rows[i]["t"][a] / rows[i]["t"]["D"]) for i in U]
        out["static_vs_ratio"][a] = {f: spearman([rows[i]["m"]["static"]["features"][f] or 0.0 for i in U], y)
                                     for f in common.STATIC}
    json.dump(out, open(os.path.join(L.RES, "observations.json"), "w"), indent=1, sort_keys=True)
    for tau, r in out["validity"].items():
        print(tau, r["n"], {k: round(v, 2) for k, v in r.items() if isinstance(v, float)})
        print("   greedy", out["greedy_progress"][tau])


if __name__ == "__main__":
    main()
