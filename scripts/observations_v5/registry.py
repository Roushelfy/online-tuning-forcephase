#!/usr/bin/env python3
"""Machine-readable observation registry of goal v5.

  python3 scripts/observations_v5/registry.py [--results results/observations_v5/registry_results.json]

Merges the catalog (configs/observations_v5/catalog.json: 80 observations,
12 decision methods, written by the goal author) with this study's plan:
package, implementing code, feature-name prefixes, first-batch status and
reason. With --results, also the outcome per item (written at the end of
V2/V3 by the analysis scripts). Writes configs/observations_v5/registry.json.

Status values: planned (first batch, in the named package), diagnostic
(robustness check, not a deployable input), analysis (used in the analysis,
not as a deployed input), not_done (with reason; NOT a negative result),
partial (part of the definition implemented; the rest not done).
"""

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "configs", "observations_v5")
OP = "tools/obsprofile.c"
OF = "scripts/observations_v5/obsfeat.py"
OBS = "solver/obs/fpcontrol.cpp + patches/cadical-obs.patch (build/obs), features in " + OF
SEL = "scripts/observations_v5/v5select.py"

P = {  # id -> (status, package(s), code, feature prefixes, note)
    "A01": ("planned", ["R01", "R10", "R11"], OP + " sec_polar/sec_resid", ["a01_", "c01_res_wpos_frac"], ""),
    "A02": ("planned", ["R01", "R10", "R11"], OP + " sec_polar", ["a02_"], ""),
    "A03": ("planned", ["R01", "R10", "R11"], OP + " sec_polar", ["a03_"], "top 10% by occurrence"),
    "A04": ("planned", ["R01", "R10", "R11"], OP + " sec_polar/sec_resid", ["a04_"],
            "weighted (2^-len) violation on original and root residual; the unweighted original counts are v4's p_allpos/allneg_cls_frac"),
    "A05": ("planned", ["R01", "R10", "R11"], OP + " sec_polar", ["a05_"], ""),
    "A06": ("not_done", [], "", [], "second batch (P2); nearest implemented: G01/G02 local search from the endpoints"),
    "A07": ("planned", ["R01", "R10", "R11"], OP + " sec_polar", ["a07_"],
            "exactly-one groups: ALO clause (3..64 literals) with all pairwise binary AMO clauses; coverage reported"),
    "A08": ("not_done", [], "", [], "second batch (P2); residual Horn/anti-Horn fractions are in C01"),
    "A09": ("planned", ["R01", "R10", "R11"], OP + " sec_polar", ["a09_"], "cheap, shares the R01 scan"),
    "A10": ("planned", ["R01", "R10", "R11"], OP + " sec_polar", ["a10_"],
            "weights: binary-clause degree and short-clause (len<=3) degree; no probe activity"),
    "A11": ("planned", ["R01", "R10", "R11"], OP + " sec_resid", ["a11_"], "mixed-polarity residual variables"),
    "A12": ("planned", ["R04"], OP + " sec_comm", ["a12_"], ""),
    "B01": ("planned", ["R02", "R10", "R11"], OP + " sec_resid", ["b01_"], ""),
    "B02": ("planned", ["R02", "R10", "R11"], OP + " sec_bilat", ["b02_"], "16 top-occurrence + 16 random residual variables"),
    "B03": ("planned", ["R02", "R10", "R11"], OP + " sec_bilat", ["b03_"], ""),
    "B04": ("planned", ["R02", "R10", "R11"], OP + " sec_bilat", ["b02_fail"], "failed literals at the root (verifiable implications)"),
    "B05": ("planned", ["R02", "R10", "R11"], OP + " sec_bilat", ["b05_"], ""),
    "B06": ("not_done", [], "", [], "second batch (P2)"),
    "B07": ("planned", ["R02", "R10", "R11"], OP + " sec_bilat", ["b07_"], "decreasing residual occurrence order, depths 4/16/64"),
    "B08": ("not_done", [], "", [], "second batch (P2); the deterministic B07 paths are done"),
    "B09": ("not_done", [], "", [], "second batch (P2)"),
    "B10": ("planned", ["R02", "R10", "R11"], OP + " sec_bilat", ["b10_"], "cheap, from the B07 paths"),
    "C01": ("planned", ["R01", "R10", "R11"], OP + " sec_resid", ["c01_"],
            "root unit-propagation residual = search-entry clause set of the pinned default (preprocess rounds 0, preprocesslight 0)"),
    "C02": ("planned", ["R01", "R10", "R11"], OP + " sec_resid", ["c02_"], ""),
    "C03": ("partial", ["R05"], OBS, ["f12_elim"], "only counts of eliminated/substituted variables after the 2 s D probe; no sign composition (P2)"),
    "C04": ("planned", ["R03"], OP + " sec_graph", ["c04_"], "equivalences from SCCs of the residual binary implication graph"),
    "C05": ("not_done", [], "", [], "second batch (P2)"),
    "C06": ("not_done", [], "", [], "second batch (P2)"),
    "C07": ("not_done", [], "", [], "second batch (P2)"),
    "C08": ("planned", ["R06", "R07", "R08"], OF, ["parse_frac", "search_frac"], "per probe arm, from CaDiCaL's profiling section"),
    "D01": ("planned", ["R03"], OP + " sec_graph", ["d01_"], ""),
    "D02": ("planned", ["R03"], OP + " sec_graph", ["d02_"], ""),
    "D03": ("planned", ["R03"], OP + " sec_graph", ["d03_"], ""),
    "D04": ("planned", ["R04"], OP + " sec_comm", ["d04_"], "3 rounds of label propagation over residual clauses with <= 8 literals"),
    "D05": ("planned", ["R04"], OP + " sec_comm", ["d05_"], ""),
    "D06": ("not_done", [], "", [], "P3"),
    "D07": ("planned", ["R03"], OP + " sec_graph", ["d07_"], ""),
    "D08": ("not_done", [], "", [], "P3"),
    "D09": ("not_done", [], "", [], "P3"),
    "D10": ("planned", ["R04"], OP + " sec_comm", ["d10_"], "2 rounds, sign-aware; colours of the formula and of its global flip"),
    "E01": ("planned", ["R06", "R10", "R11"], OF, ["e02_"], "D/F+/F- 0.2 s each"),
    "E02": ("planned", ["R07"], OF, ["e05_"], "D/F+/F- 0.5 s each"),
    "E03": ("planned", ["R08"], OF, ["ec_"], "512 conflicts, 1 s cap per arm"),
    "E04": ("planned", ["R08"], OF, ["ec_"], "CPU to reach 512 conflicts, parse/search split"),
    "E05": ("planned", ["R06", "R07", "R08", "R10", "R11"], OF, ["_dFp", "_dFm", "_dPM"], "differences F+-D, F--D, F+-F-"),
    "E06": ("planned", ["R06", "R07", "R08"], OF, ["glue", "size"], ""),
    "E07": ("planned", ["R06", "R07", "R08"], OF, ["trail", "best"], ""),
    "E08": ("not_done", [], "", [], "second batch (P2)"),
    "E09": ("planned", ["R06", "R07", "R08"], OF, ["units", "bins", "fixed"], ""),
    "E10": ("not_done", [], "", [], "second batch (P2); window trends of F11 cover part of it"),
    "E11": ("planned", ["R06", "R07"], OF, ["stable", "rephased"], ""),
    "E12": ("planned", ["R11"], SEL, [], "conditional R06 probe (with M10)"),
    "F01": ("planned", ["R05"], OBS, ["f01_"], "audit-v2 corrected flip rate"),
    "F02": ("not_done", [], "", [], "second batch (P2)"),
    "F03": ("planned", ["R05"], OBS, ["f03_"], ""),
    "F04": ("planned", ["R05"], OBS, ["f04_"], ""),
    "F05": ("not_done", [], "", [], "second batch (P2)"),
    "F06": ("not_done", [], "", [], "second batch (P2)"),
    "F07": ("not_done", [], "", [], "second batch (P2)"),
    "F08": ("planned", ["R05"], OBS, ["f08_"], "literal signs of learned clauses (no change of the decision heuristic)"),
    "F09": ("not_done", [], "", [], "second batch (P2)"),
    "F10": ("planned", ["R05"], OBS, ["f10_"], ""),
    "F11": ("planned", ["R05"], OBS, ["f11_"], "windows of 100 conflicts"),
    "F12": ("planned", ["R05"], OBS, ["f12_"], "availability indicators"),
    "G01": ("planned", ["R09"], OP + " sec_ls", ["g01_"], "probSAT, 0.2 s per start"),
    "G02": ("planned", ["R09"], OP + " sec_ls", ["g02_"], ""),
    "G03": ("planned", ["R09"], OP + " sec_ls", ["g03_"], "final assignment of each start"),
    "G04": ("planned", ["R09"], OP + " sec_ls", ["g04_"], ""),
    "G05": ("not_done", [], "", [], "second batch (P2)"),
    "G06": ("planned", ["R09"], OP + " sec_ls", ["g06_"], ""),
    "G07": ("not_done", [], "", [], "P3"),
    "G08": ("not_done", [], "", [], "P3"),
    "H01": ("diagnostic", [], "scripts/observations_v5/v1_engineering.py", [], "global flip on the engineering panel"),
    "H02": ("diagnostic", [], "scripts/observations_v5/v1_engineering.py", [], "variable/clause permutation on the engineering panel"),
    "H03": ("not_done", [], "", [], "P3"),
    "H04": ("analysis", [], SEL, [], "5-NN distance in the training fold's S28 space; gain split by distance tercile"),
    "H05": ("not_done", [], "", [], "second batch (P2)"),
    "H06": ("not_done", [], "", [], "second batch (P2)"),
    "H07": ("not_done", [], "", [], "P3, expensive"),
    "H08": ("not_done", [], "", [], "P3, expensive"),
}
M = {
    "M01": ("planned", SEL, "RG/TG: separate predicted gains for F+ and F- vs D, gate"),
    "M02": ("planned", SEL, "targets are simulated wrapper cost differences in seconds (timeouts and observation CPU included)"),
    "M03": ("planned", SEL, "F+-D and F--D regressed; F+-F- via the argmax"),
    "M04": ("planned", SEL, "theta grid chosen on inner folds; fallback curves"),
    "M05": ("not_done", "", "second batch (P2)"),
    "M06": ("planned", SEL, "RF-gate for at most 3 promoted packages"),
    "M07": ("partial", SEL, "depth <= 2 regression trees are short rules; no rule-list learner"),
    "M08": ("not_done", "", "second batch (P2)"),
    "M09": ("partial", SEL, "regression targets keep near ties near 0; no explicit multi-label training"),
    "M10": ("planned", SEL, "R11 two-stage observation"),
    "M11": ("partial", SEL, "severe regressions reported, not optimised"),
    "M12": ("not_done", "", "P3"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=None)
    a = ap.parse_args()
    cat = json.load(open(os.path.join(CFG, "catalog.json")))
    res = json.load(open(a.results)) if a.results else {}
    obs = []
    for o in cat["observations"]:
        st, pk, code, fp, note = P[o["id"]]
        e = dict(o)
        e.update({"v5_status": st, "packages": pk, "code": code, "feature_prefixes": fp, "v5_note": note})
        if o["id"] in res:
            e["result"] = res[o["id"]]
        obs.append(e)
    meth = []
    for m in cat["decision_methods"]:
        st, code, note = M[m["id"]]
        e = dict(m)
        e.update({"v5_status": st, "code": code, "v5_note": note})
        if m["id"] in res:
            e["result"] = res[m["id"]]
        meth.append(e)
    assert len(obs) == 80 and len(meth) == 12
    out = {"version": 5, "protocol": "docs/OBSERVATION_PROTOCOL_V5.md", "catalog": "configs/observations_v5/catalog.json",
           "status_values": {"planned": "first batch, in the named package(s)", "diagnostic": "robustness check, not a deployed input",
                             "analysis": "used in the analysis only", "partial": "part of the definition implemented",
                             "not_done": "not implemented in this study (not a negative result)"},
           "observations": obs, "decision_methods": meth}
    json.dump(out, open(os.path.join(CFG, "registry.json"), "w"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(Counter(e["v5_status"] for e in obs), Counter(e["v5_status"] for e in meth))


if __name__ == "__main__":
    main()
