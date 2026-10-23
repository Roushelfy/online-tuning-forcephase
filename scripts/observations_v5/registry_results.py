#!/usr/bin/env python3
"""Per-item outcomes for the registry (written after V2, before/after V3).

  python3 scripts/observations_v5/registry_results.py && \\
  python3 scripts/observations_v5/registry.py --results results/observations_v5/registry_results.json

For every implemented observation: number of features, strongest Spearman
rho with r_F+ / r_F- (screen), number of 'consistent' features, and the
OOF net gain of its packages with RG/TG plus the paired increment over S28.
For decision methods: the comparisons that implement them. Status words:
'done: no signal shown' / 'done: weak signal, no increment' etc. are
descriptive and refer to this panel only.
"""

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import registry as REG  # noqa: E402

ROOT = REG.ROOT
RES = os.path.join(ROOT, "results", "observations_v5")


def f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def main():
    screen = list(csv.DictReader(open(os.path.join(RES, "screen.csv"))))
    sel = {r["name"]: r for r in csv.DictReader(open(os.path.join(RES, "selection.csv")))}
    ab = {(r["test"], r["package"], r["reader"]): r for r in csv.DictReader(open(os.path.join(RES, "ablation.csv")))}
    out = {}
    for oid, (st, pk, code, fp, note) in REG.P.items():
        if st not in ("planned", "partial") or not fp:
            continue
        feats = [r for r in screen if any(r["feature"].startswith(p) or p in r["feature"] for p in fp)
                 and (not pk or r["package"] in pk)]
        rp = max((abs(f(r["rho_Fp"])) for r in feats if not math.isnan(f(r["rho_Fp"]))), default=float("nan"))
        rm = max((abs(f(r["rho_Fm"])) for r in feats if not math.isnan(f(r["rho_Fm"]))), default=float("nan"))
        cons = sum(int(r["consistent_Fp"]) + int(r["consistent_Fm"]) for r in feats)
        pkres = {}
        for p in pk:
            for rd in ("RG", "TG"):
                r = sel.get(f"{p}|{rd}")
                if r:
                    inc = ab.get(("observation_increment", p, rd))
                    pkres[f"{p}|{rd}"] = {"gain_pct": round(f(r["gain_pct"]), 2),
                                          "ci": [round(f(r["gain_pct_lo"]), 2), round(f(r["gain_pct_hi"]), 2)],
                                          "increment_vs_S28_s": None if not inc else
                                          [round(f(inc["diff"]), 2), round(f(inc["lo"]), 2), round(f(inc["hi"]), 2)]}
        any_pos = any(v["ci"][0] > 0 for v in pkres.values())
        any_inc = any(v["increment_vs_S28_s"] and v["increment_vs_S28_s"][1] > 0 for v in pkres.values())
        status = ("done: package beats always-D" if any_pos else
                  "done: increment over S28 shown" if any_inc else
                  "done: weak univariate signal, no gain or increment shown" if cons else
                  "done: no signal shown")
        out[oid] = {"status": status, "n_features": len(feats), "max_abs_rho_Fp": round(rp, 3) if not math.isnan(rp) else None,
                    "max_abs_rho_Fm": round(rm, 3) if not math.isnan(rm) else None, "consistent_tests": cons,
                    "packages": pkres, "scope": "dev 401, outer 5-fold OOF; see reports/observations_v5/"}
    for oid in ("H01", "H02"):
        out[oid] = {"status": "done: diagnostic", "report": "reports/observations_v5/V1_ENGINEERING.md section 4"}
    out["H04"] = {"status": "done: analysis", "report": "reports/observations_v5/SELECTION_AND_ABLATION.md section 6"}
    meth = {"M01": ["RG", "TG"], "M02": ["RG", "TG"], "M03": ["RG", "TG"], "M04": ["RG", "TG"], "M06": ["RF"],
            "M07": ["TG"], "M09": ["RG", "TG"], "M10": ["R11"], "M11": ["RG", "TG"]}
    for mid, rds in meth.items():
        rows = [r for r in sel.values() if (r["reader"] in rds and r["package"] not in ("S28",)) or
                (mid == "M10" and r["package"] == "R11")]
        best = max(rows, key=lambda r: f(r["gain_pct"]))
        vs_old = [r for r in ab.values() if r["test"] == "reader_vs_old"]
        out[mid] = {"status": "done: no comparison beats always-D" if f(best["gain_pct_lo"]) <= 0 else "done: beats always-D",
                    "best": best["name"], "best_gain_pct": round(f(best["gain_pct"]), 2),
                    "best_ci": [round(f(best["gain_pct_lo"]), 2), round(f(best["gain_pct_hi"]), 2)]}
        if mid in ("M01", "M02", "M04"):
            out[mid]["vs_v4_readers_same_input"] = f"{sum(f(r['lo']) > 0 for r in vs_old)}/{len(vs_old)} paired CIs > 0"
    json.dump(out, open(os.path.join(RES, "registry_results.json"), "w"), indent=1, ensure_ascii=False)
    import collections
    print(collections.Counter(v["status"] for v in out.values()))


if __name__ == "__main__":
    main()
