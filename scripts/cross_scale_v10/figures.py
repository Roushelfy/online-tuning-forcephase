#!/usr/bin/env python3
"""Goal v10 core figures (analysis venv). Reads results/cross_scale_v10/{baselines,selection,validation_*}.json and
writes reports/cross_scale_v10/fig*.png; figures whose inputs are missing are skipped.

  $FP_PY scripts/cross_scale_v10/figures.py
"""
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "cross_scale_v10")
REP = os.path.join(ROOT, "reports", "cross_scale_v10")
COL = {"D": "#4c72b0", "Fp": "#dd8452", "Fm": "#55a868", "oracle": "#333333", "W_main": "#8172b3", "W_ref": "#c44e52",
       "SBS": "#937860"}
LAB = {"D": "D", "Fp": "F+", "Fm": "F−", "W_main": "main (B)", "W_ref": "control (D 2 s → F−)", "oracle": "oracle"}


def load(name):
    p = os.path.join(RES, name)
    return json.load(open(p)) if os.path.exists(p) else None


def fig1(b):
    cells = list(b["dev"]["cells"])
    fig, ax = plt.subplots(figsize=(11, 3.8))
    w = 0.2
    for k, a in enumerate(("D", "Fp", "Fm")):
        ax.bar([x + (k - 1.5) * w for x in range(len(cells))], [b["dev"]["cells"][c]["complete_mean"][a] for c in cells],
               w, color=COL[a], label=LAB[a])
    ax.bar([x + 1.5 * w for x in range(len(cells))], [b["dev"]["cells"][c]["oracle_mean"] for c in cells], w,
           color=COL["oracle"], label="oracle")
    ax.set_yscale("log")
    ax.set_xticks(range(len(cells)))
    ax.set_xticklabels(cells, rotation=0, fontsize=8)
    ax.set_ylabel("mean CPU s (complete, 30 per cell)")
    ax.set_title("v10 development set: fixed modes per type x level (dev SBS = F−)")
    ax.legend(fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig1_dev_cells.png"), dpi=130)


def fig2(s):
    fams = ["fixed_D", "fixed_Fp", "fixed_Fm", "SBS", "A", "N_B", "B", "B_v9", "N_C", "C", "REF", "oracle"]
    names = ["D", "F+", "F−", "SBS", "A", "N_B", "B*", "B_v9", "N_C", "C", "REF", "oracle"]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    tot = [s["families"][f]["total"] for f in fams]
    colors = ["#bbbbbb" if f not in ("B", "N_B", "N_C", "C", "A") else ("#8172b3" if f == "B" else "#7aa6c2") for f in fams]
    ax.bar(range(len(fams)), tot, color=colors)
    for k, f in enumerate(fams):
        ax.text(k, tot[k] + 60, f"{tot[k]:.0f}", ha="center", fontsize=7)
    ax.set_xticks(range(len(fams)))
    ax.set_xticklabels(names)
    ax.set_ylabel("outer-CV total CPU s (270 dev)")
    ax.set_title("Nested grouped CV on development data (all families solve 270/270); * = frozen main")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig2_dev_families.png"), dpi=130)


def fig3(s):
    cov = s["coverage"]["probes"]
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    for arm in ("D", "Fp", "Fm"):
        ks = sorted((float(k.split("@")[1]), v) for k, v in cov.items() if k.startswith(arm + "@"))
        ax.plot([t for t, _ in ks], [v["answered"] / 270 for _, v in ks], "o-", color=COL[arm], label=f"{LAB[arm]} answers")
        ax.plot([t for t, _ in ks], [v["not_started"] / 270 for _, v in ks], "x--", color=COL[arm], alpha=0.6,
                label=f"{LAB[arm]} no search yet")
    ax.set_xscale("log")
    ax.set_xlabel("probe window tau (CPU s)")
    ax.set_ylabel("fraction of 270 dev instances")
    ax.set_title("Probe coverage on development data")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig3_probe_coverage.png"), dpi=130)


def fig4(vc):
    groups = ["all"] + [g for g in sorted(vc["groups"]) if g.startswith(("block:", "type:", "level:"))]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    for j, ref in enumerate(("D", "SBS")):
        for k, m in enumerate(("W_main", "W_ref") + (("Fp", "Fm") if ref == "D" else ())):
            xs, ys, lo, hi = [], [], [], []
            for g_i, g in enumerate(groups):
                st = vc["all"] if g == "all" else vc["groups"][g]
                c = st["comparisons"].get(f"{m}_vs_{ref}")
                if not c or "gain" not in c:
                    continue
                xs.append(g_i + (k - 1.5) * 0.18)
                ys.append(100 * c["gain"])
                lo.append(100 * (c["gain"] - c["ci"][0]))
                hi.append(100 * (c["ci"][1] - c["gain"]))
            ax[j].errorbar(xs, ys, yerr=[lo, hi], fmt="o", color=COL.get(m), label=LAB.get(m, m), capsize=2, ms=4)
        ax[j].axhline(0, color="k", lw=0.8)
        if ref == "SBS":
            ax[j].axhline(5, color="k", lw=0.6, ls=":")
        ax[j].set_xticks(range(len(groups)))
        ax[j].set_xticklabels([g.split(":")[-1] for g in groups], rotation=45, fontsize=8)
        ax[j].set_ylabel(f"CPU reduction vs {'D' if ref == 'D' else 'dev SBS (F−)'} (%)")
        ax[j].set_title(f"Confirmation 270: gain vs {ref} with 95% CI")
        ax[j].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig4_confirm_gains.png"), dpi=130)


def cactus(ax, v, title, methods=("D", "Fp", "Fm", "W_main", "W_ref")):
    per = v["per_instance"]
    for m in methods:
        ts = sorted(per[i][m]["cpu"] for i in per if per[i][m]["solved"])
        ax.plot(ts, range(1, len(ts) + 1), color=COL.get(m), label=f"{LAB.get(m, m)} ({len(ts)})")
    ax.set_xscale("log")
    ax.set_xlabel("CPU s (limit 3600)")
    ax.set_ylabel("instances solved")
    ax.set_title(title)
    ax.legend(fontsize=7)


def fig5(ve, vx):
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    if ve:
        cactus(ax[0], ve, f"Scale extrapolation ({ve['all']['n']})")
    if vx:
        cactus(ax[1], vx, f"External SATLIB families ({vx['all']['n']})")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig5_extrap_external.png"), dpi=130)


def fig6(st):
    fig, ax = plt.subplots(figsize=(6.5, 4))
    cactus(ax, st, "Old 55 competition problems (stress test, 3600 s)", methods=st["methods"])
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig6_stress_old55.png"), dpi=130)


def main():
    os.makedirs(REP, exist_ok=True)
    b, s = load("baselines.json"), load("selection.json")
    if b:
        fig1(b)
    if s:
        fig2(s)
        fig3(s)
    vc = load("validation_confirm.json")
    if vc:
        fig4(vc)
    ve, vx = load("validation_extrapolation.json"), load("validation_external.json")
    if ve or vx:
        fig5(ve, vx)
    st = load("stress_old55.json")
    if st:
        fig6(st)


if __name__ == "__main__":
    main()
