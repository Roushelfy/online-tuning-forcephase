#!/usr/bin/env python3
"""v9 core figures (analysis venv: /mnt/data/zhaofeng/venvs/online-tuning-forcephase/bin/python).

Reads results/online_selection_v9/{dev_table.json, pre_solve.json, selection.json, validation_holdout.json,
mechanism.json}; writes reports/online_selection_v9/fig*.png (figures whose inputs are missing are skipped).
"""
import json
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "online_selection_v9")
REP = os.path.join(ROOT, "reports", "online_selection_v9")
TAUS = [0.1, 0.25, 0.5, 1, 2, 5, 10]
COL = {"D": "#4c72b0", "Fp": "#dd8452", "Fm": "#55a868", "oracle": "#333333", "W_ref": "#c44e52", "W_main": "#8172b3",
       "SBS": "#937860"}


def load(name):
    p = os.path.join(RES, name)
    return json.load(open(p)) if os.path.exists(p) else None


def fig1(pre):
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    solved = [pre["per_tau"][repr(float(t))]["solved_main"] / 270 for t in TAUS]
    ax[0].plot(TAUS, solved, "o-")
    ax[0].set_xscale("log")
    ax[0].set_xlabel("probe window tau (CPU s)")
    ax[0].set_ylabel("fraction of 270 dev instances solved by the D probe")
    ax[0].set_title("D probe coverage")
    for a, c in (("Fp", COL["Fp"]), ("Fm", COL["Fm"])):
        ax[1].plot(TAUS, [pre["gates"][f"P({t},{a})"]["mean"] for t in TAUS], "o-", color=c, label=f"D probe -> {a}")
    for m in ("D", "Fp", "Fm", "oracle"):
        ax[1].axhline(pre["fixed"][m], color=COL[m], ls="--", lw=1, label=f"always {m}" if m != "oracle" else "oracle")
    ax[1].set_xscale("log")
    ax[1].set_xlabel("tau (CPU s)")
    ax[1].set_ylabel("mean CPU s (dev, cost model)")
    ax[1].legend(fontsize=7)
    ax[1].set_title("time gates on development")
    fig.suptitle("Fig 1. Default pre-solve: coverage and development cost")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig1_presolve_dev.png"), dpi=130)


def fig2(val):
    p = val["panels"]["holdout"]
    if "by_cell" not in p:
        return
    cells = list(p["by_cell"])
    methods = [m for m in ("D", "Fp", "Fm", "W_ref", "W_main", "oracle") if m in p["by_cell"][cells[0]]]
    fig, ax = plt.subplots(figsize=(12, 4))
    w = 0.8 / len(methods)
    for k, m in enumerate(methods):
        ax.bar([x + w * k - 0.4 + w / 2 for x in range(len(cells))], [p["by_cell"][c][m] for c in cells], width=w,
               color=COL.get(m), label=m)
    ax.set_yscale("log")
    ax.set_xticks(range(len(cells)))
    ax.set_xticklabels(cells, rotation=30, fontsize=8)
    ax.set_ylabel("mean CPU s (complete)")
    ax.legend(fontsize=8)
    ax.set_title("Fig 2. Held-out 270: mean CPU per type x scale")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig2_holdout_cells.png"), dpi=130)


def fig3(val):
    fig, ax = plt.subplots(figsize=(8, 3.8))
    labels, mids, los, his = [], [], [], []
    for pn in ("holdout", "H1", "H2", "H3"):
        p = val["panels"].get(pn)
        if not p or "ci" not in p:
            continue
        for key in sorted(k for k in p["ci"] if k.endswith("_vs_D") and k.split("_vs_")[0] in ("W_ref", "W_main", "Fp", "Fm", "SBS")):
            g = p["summary"]["gain_percent_vs_baseline"].get(key.split("_vs_")[0])
            if g is None:
                continue
            labels.append(f"{pn}: {key.replace('_vs_D', '')}")
            mids.append(g)
            los.append(g - p["ci"][key][0])
            his.append(p["ci"][key][1] - g)
    ax.errorbar(range(len(labels)), mids, yerr=[los, his], fmt="o", capsize=3)
    ax.axhline(0, color="k", lw=0.8)
    ax.axhline(5, color="gray", ls=":", lw=0.8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=60, fontsize=7)
    ax.set_ylabel("gain vs D, % (95% cell-stratified bootstrap)")
    ax.set_title("Fig 3. Held-out gains vs D by block")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig3_holdout_gains.png"), dpi=130)


def fig4(val):
    p = val["panels"]["holdout"]
    if "per_instance" not in p:
        return
    w = "W_main" if "W_main" in p["per_instance"][0] and p["per_instance"][0]["W_main"] is not None else "W_ref"
    d = sorted(r["D"] - r[w] for r in p["per_instance"])
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar(range(len(d)), d, width=1.0, color=["#c44e52" if x < 0 else "#55a868" for x in d])
    ax.set_yscale("symlog", linthresh=1)
    ax.set_xlabel("held-out instances (sorted)")
    ax.set_ylabel(f"D - {w} CPU s (>0: wrapper saves)")
    ax.set_title(f"Fig 4. Per-instance saving of {w} vs D (held-out 270)")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig4_holdout_instances.png"), dpi=130)


def fig5(mech):
    groups = [g for g in ("rand3-SAT", "rand3-UNSAT", "col3-SAT", "col3-UNSAT", "assign2-SAT", "assign2-UNSAT")
              if g in mech["groups"]]
    names = list(mech["groups"][groups[0]]["contrasts"])
    M = [[mech["groups"][g]["contrasts"][n]["median_log2"] for g in groups] for n in names]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    im = ax.imshow(M, cmap="RdBu_r", vmin=-3, vmax=3, aspect="auto")
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([f"{g}\n(n={mech['groups'][g]['n']})" for g in groups], fontsize=8)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=7)
    for i in range(len(names)):
        for j in range(len(groups)):
            ax.text(j, i, f"{M[i][j]:+.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, label="median log2 time ratio (<0: first config faster)")
    ax.set_title("Fig 5. Rephase / forcing / initial-phase ablation (54 dev instances)")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig5_mechanism.png"), dpi=130)


if __name__ == "__main__":
    os.makedirs(REP, exist_ok=True)
    pre, val, mech = load("pre_solve.json"), load("validation_holdout.json"), load("mechanism.json")
    if pre:
        fig1(pre)
    if val:
        fig2(val)
        fig3(val)
        fig4(val)
    if mech:
        fig5(mech)
    print("figures written")
