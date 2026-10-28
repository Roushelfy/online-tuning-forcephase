#!/usr/bin/env python3
"""Goal v11 core figures (analysis venv). Reads results/broad_scope_v11/{baselines,selection,validation_*}.json and
writes reports/broad_scope_v11/fig*.png; figures whose inputs are missing are skipped.

  $FP_PY scripts/broad_scope_v11/figures.py
"""
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "broad_scope_v11")
REP = os.path.join(ROOT, "reports", "broad_scope_v11")
COL = {"D": "#4c72b0", "Fp": "#dd8452", "Fm": "#55a868", "oracle": "#333333", "W_main": "#8172b3",
       "W_struct": "#c44e52", "W_nc": "#937860", "W_v10": "#999999", "SBS": "#64b5cd"}
LAB = {"D": "D", "Fp": "F+", "Fm": "F−", "W_main": "main", "W_struct": "structural control", "W_nc": "matched control",
       "W_v10": "v10 (historical)", "oracle": "oracle", "SBS": "dev SBS"}
FAMS = ["rand3", "col3", "assign2", "vcover", "jssp", "bwplan", "factor", "qcp"]


def load(name):
    p = os.path.join(RES, name)
    return json.load(open(p)) if os.path.exists(p) else None


def fig1(b):
    """Per family x level: solved-instance mean CPU of each mode (log), timeouts marked."""
    cells = [f"{f}|{lv}" for f in FAMS for lv in ("S", "M", "L") if f"{f}|{lv}" in b["cells"]]
    fig, ax = plt.subplots(figsize=(13, 4))
    w = 0.2
    for k, a in enumerate(("D", "Fp", "Fm")):
        ys, to = [], []
        for c in cells:
            m = b["cells"][c]["modes"][a]
            ys.append(m["total_actual_cpu"] / b["cells"][c]["n"])
            to.append(b["cells"][c]["n"] - m["solved"])
        xs = np.arange(len(cells)) + (k - 1.5) * w
        ax.bar(xs, ys, w, color=COL[a], label=LAB[a])
        for x, y, t in zip(xs, ys, to):
            if t:
                ax.text(x, y * 1.1, f"{t}✗", ha="center", fontsize=6, color="red")
    ax.bar(np.arange(len(cells)) + 1.5 * w, [b["cells"][c]["oracle"]["mean_lower_bound"] for c in cells], w,
           color=COL["oracle"], label="oracle")
    ax.set_yscale("log")
    ax.set_xticks(range(len(cells)))
    ax.set_xticklabels(cells, rotation=70, fontsize=7)
    ax.set_ylabel("mean actual CPU s per instance (timeouts at their cap, red = count)")
    ax.set_title("v11 training pool (discovery + development, 528): three fixed modes per family x level")
    ax.legend(fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig1_pool_cells.png"), dpi=130)


def fig2(b):
    """Within-type vs between-type: SBS, family-best fixed flag, oracle per family (relative to SBS)."""
    dec = b["decomposition"]["by_family"]
    fams = [f for f in FAMS if f in b["families"]]
    sbs = dec["sbs"]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    for k, (lab, get) in enumerate((("dev SBS (" + sbs + ")", lambda f: b["families"][f]["modes"][sbs]["total_actual_cpu"]),
                                    ("family flag", lambda f: b["families"][f]["modes"][dec["group_actions"][f]]["total_actual_cpu"]),
                                    ("oracle", lambda f: b["families"][f]["oracle"]["total"]))):
        ys = [get(f) / b["families"][f]["modes"][sbs]["total_actual_cpu"] for f in fams]
        ax.bar(np.arange(len(fams)) + (k - 1) * 0.27, ys, 0.27, label=lab,
               color=[COL["SBS"], COL["W_struct"], COL["oracle"]][k])
    ax.set_xticks(range(len(fams)))
    ax.set_xticklabels([f"{f}\n→{dec['group_actions'][f].replace('Fp', 'F+').replace('Fm', 'F−')}" for f in fams], fontsize=8)
    ax.set_ylabel("total CPU relative to dev SBS")
    cap = dec["captured_fraction_of_cpu_space"]
    ax.set_title(f"Fixed flag per family captures {100 * cap:.0f}% of the SBS→oracle CPU space (posthoc, in-sample)"
                 if cap is not None else "Family flag vs oracle")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig2_family_flag_vs_oracle.png"), dpi=130)


def fig3(b):
    """Stability of the fastest mode under re-encoding, flipall, perm and solver seeds, per family."""
    s = b["diagnostics"]["summary"]
    ops = ["enc", "flipall", "perm", "seed1", "seed2"]
    M = np.full((len(ops), len(FAMS)), np.nan)
    for i, op in enumerate(ops):
        for j, f in enumerate(FAMS):
            c = s.get(f"{op}|{f}")
            if c and c.get("n"):
                key = "fastest_same_after_swap" if op == "flipall" else "fastest_same"
                M[i, j] = c.get(key, 0) / c["n"]
    fig, ax = plt.subplots(figsize=(9, 3.4))
    im = ax.imshow(M, vmin=0, vmax=1, cmap="viridis")
    for i in range(len(ops)):
        for j in range(len(FAMS)):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=8, color="w" if M[i, j] < 0.5 else "k")
    ax.set_xticks(range(len(FAMS)))
    ax.set_xticklabels(FAMS)
    ax.set_yticks(range(len(ops)))
    ax.set_yticklabels(["alt. encoding", "flipall (F+↔F−)", "perm", "seed 1", "seed 2"])
    ax.set_title("Fastest mode unchanged (fraction of base instances)")
    fig.colorbar(im, ax=ax, fraction=0.03)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig3_encoding_stability.png"), dpi=130)


def fig4(s):
    fams = ["fixed_D", "fixed_Fp", "fixed_Fm", "SBS", "ST", "TR", "PR", "NC", "V10", "label_route", "oracle"]
    names = ["D", "F+", "F−", "SBS", "ST", "TR", "PR", "NC", "V10", "label→flag*", "oracle"]
    fig, ax = plt.subplots(1, 2, figsize=(13, 3.8))
    tot = [s["summary"][f]["total"] for f in fams]
    sol = [s["summary"][f]["solved"] for f in fams]
    main = s["main_family"]
    colors = ["#8172b3" if f == main else ("#c44e52" if f == s["structural_control"] else "#bbbbbb") for f in fams]
    ax[0].bar(range(len(fams)), tot, color=colors)
    for k in range(len(fams)):
        ax[0].text(k, tot[k] * 1.01, f"{sol[k]}", ha="center", fontsize=7)
    ax[0].set_xticks(range(len(fams)))
    ax[0].set_xticklabels(names, fontsize=8)
    ax[0].set_ylabel("outer-CV total actual CPU s (labels: solved)")
    ax[0].set_title(f"Nested grouped CV on the pool (n = {s['n']}); main = {main}, * posthoc")
    lofo = s["diagnostics"]["leave_one_family_out"]["by_heldout"]
    for k, f in enumerate(("SBS", "ST", "TR", "PR", "label_route")):
        ys = []
        for fam in FAMS:
            g = lofo[f].get(fam)
            base = lofo["SBS"].get(fam)
            ys.append(1 - g["total"] / base["total"] if g and base and base["total"] else np.nan)
        ax[1].bar(np.arange(len(FAMS)) + (k - 2) * 0.16, [100 * y for y in ys], 0.16, label=f)
    ax[1].axhline(0, color="k", lw=0.8)
    ax[1].set_xticks(range(len(FAMS)))
    ax[1].set_xticklabels(FAMS, fontsize=8)
    ax[1].set_ylabel("CPU reduction vs SBS on the held-out family (%)")
    ax[1].set_title("Leave-one-family-out (family unseen in training)")
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig4_cv_methods.png"), dpi=130)


def fig5(vc):
    """Confirmation 240: (a) solved per family and method; (b) CPU change vs D (= dev SBS = main) per family where
    both sides are complete, 95% CI (paired stratified bootstrap)."""
    fams = [f for f in FAMS if "family:" + f in vc["groups"]]
    ms = ["D", "Fp", "Fm", "W_struct", "W_v10"]
    fig, ax = plt.subplots(1, 2, figsize=(14, 4))
    for k, m in enumerate(ms):
        ys = [vc["groups"]["family:" + f]["methods"][m]["solved"] for f in fams]
        ax[0].bar(np.arange(len(fams)) + (k - 2) * 0.16, ys, 0.16, color=COL.get(m), label=LAB.get(m, m))
    ax[0].set_xticks(range(len(fams)))
    ax[0].set_xticklabels(fams, fontsize=8)
    ax[0].set_ylabel("solved / 30 (cap 3600 s)")
    tot = {m: vc["all"]["methods"][m]["solved"] for m in ms}
    ax[0].set_title("Confirmation 240: solved per family (" + ", ".join(f"{LAB.get(m, m)} {tot[m]}" for m in ms) + ")",
                    fontsize=8)
    ax[0].legend(fontsize=7, ncol=3)
    for k, (m, key) in enumerate((("Fp", "Fp_vs_D"), ("Fm", "Fm_vs_D"), ("W_struct", "W_struct_vs_SBS"), ("W_v10", "W_v10_vs_SBS"))):
        xs, ys, lo, hi = [], [], [], []
        for j, f in enumerate(fams):
            c = vc["groups"]["family:" + f]["comparisons"].get(key)
            if not c or "gain" not in c:
                continue
            g = max(c["gain"], -2.0)
            xs.append(j + (k - 1.5) * 0.18)
            ys.append(100 * g)
            lo.append(100 * max(0.0, g - max(c["ci"][0], -2.0)))
            hi.append(100 * max(0.0, max(c["ci"][1], -2.0) - g))
        ax[1].errorbar(xs, ys, yerr=[lo, hi], fmt="o", capsize=2, ms=4, color=COL.get(m), label=LAB.get(m, m) + " vs D")
    ax[1].axhline(0, color="k", lw=0.8)
    ax[1].set_ylim(-200, 60)
    ax[1].set_xticks(range(len(fams)))
    ax[1].set_xticklabels(fams, fontsize=8)
    ax[1].set_ylabel("CPU reduction vs D (%), clipped at -200")
    ax[1].set_title("Complete families only (col3, rand3, vcover have timeouts: see solved counts)", fontsize=8)
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig5_confirm_gains.png"), dpi=130)


def cactus(ax, v, ids, title, methods):
    per = v["per_instance"]
    for m in methods:
        ts = sorted(per[i][m]["cpu"] for i in ids if per[i][m]["solved"])
        ax.plot(ts, range(1, len(ts) + 1), color=COL.get(m), label=f"{LAB.get(m, m)} ({len(ts)})")
    ax.set_xscale("log")
    ax.set_xlabel("CPU s (cap 3600)")
    ax.set_ylabel("instances solved")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=7)


def fig6(vp):
    methods = [m for m in ("D", "Fp", "Fm", "W_main", "W_struct", "W_v10") if m in vp["all"]["methods"]]
    per = vp["per_instance"]
    man = {r["id"]: r for r in json.load(open(os.path.join(RES, "public_formal_manifest.json")))["instances"]}
    unseen = [i for i in per if man[i].get("unseen_in_v11_training")]
    rel = [i for i in per if not man[i].get("unseen_in_v11_training")]
    comp = [i for i in per if man[i]["source"].startswith("comp")]
    fig, ax = plt.subplots(1, 3, figsize=(15, 4))
    cactus(ax[0], vp, unseen, f"Public, families unseen in v11 training ({len(unseen)})", methods)
    cactus(ax[1], vp, rel, f"Public, families related to a v11 family ({len(rel)})", methods)
    cactus(ax[2], vp, comp, f"Public, competition years 2022-2026 ({len(comp)})", methods)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig6_public.png"), dpi=130)


def main():
    os.makedirs(REP, exist_ok=True)
    b, s = load("baselines.json"), load("selection.json")
    if b:
        fig1(b)
        fig2(b)
        if b.get("diagnostics"):
            fig3(b)
    if s:
        fig4(s)
    vc = load("validation_confirm.json")
    if vc:
        fig5(vc)
    vp = load("validation_public.json")
    if vp:
        fig6(vp)


if __name__ == "__main__":
    main()
