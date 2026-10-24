#!/usr/bin/env python3
"""v8 core figures from results/stratified_v8/figdata.json (report.py) and features.

  /mnt/data/zhaofeng/venvs/online-tuning-forcephase/bin/python scripts/stratified_v8/figures.py

Writes reports/stratified_v8/fig{1..5}_*.png.
"""
import json
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RES = os.path.join(ROOT, "results", "stratified_v8")
REP = os.path.join(ROOT, "reports", "stratified_v8")
D = json.load(open(os.path.join(RES, "figdata.json")))
rows = [r for r in D["rows"] if r.get("oracle") is not None]
TYPES, SCALES, ACTS = ("rand3", "col3", "assign"), ("S", "M", "L"), ("D", "Fp", "Fm")
COL = {"D": "#4c72b0", "Fp": "#dd8452", "Fm": "#55a868", "oracle": "#333333"}
NAME = {"D": "D", "Fp": "F+", "Fm": "F−", "oracle": "oracle"}


def fig1():
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), sharey=False)
    for ax, t in zip(axes, TYPES):
        xs = range(len(SCALES))
        for k, m in enumerate(ACTS + ("oracle",)):
            vals = []
            for s in SCALES:
                rs = [r for r in rows if r["type"] == t and r["scale"] == s]
                vals.append(sum(r[m] for r in rs) / len(rs) if rs else float("nan"))
            ax.bar([x + 0.2 * k - 0.3 for x in xs], vals, width=0.2, color=COL[m], label=NAME[m])
        ax.set_yscale("log")
        ax.set_xticks(list(xs))
        ax.set_xticklabels([f"{s}" for s in SCALES])
        ax.set_title(t)
        ax.set_ylabel("mean CPU s (complete)")
    axes[0].legend(fontsize=8)
    fig.suptitle("Fig 1. Mean completed CPU per type x scale (all 54 instances)")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig1_cell_means.png"), dpi=130)


def fig2():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0), sharey=True)
    colr = {("rand3", "SAT"): "#4c72b0", ("rand3", "UNSAT"): "#dd8452", ("col3", "SAT"): "#55a868",
            ("col3", "UNSAT"): "#c44e52", ("assign", "SAT"): "#8172b3", ("assign", "UNSAT"): "#937860"}
    for ax, m in zip(axes, ("Fp", "Fm")):
        for k, t in enumerate(TYPES):
            for ans, mk in (("SAT", "o"), ("UNSAT", "x")):
                rs = [r for r in rows if r["type"] == t and r.get("answer") == ans]
                if not rs:
                    continue
                xs = [k + {"S": -0.2, "M": 0.0, "L": 0.2}[r["scale"]] for r in rs]
                ax.scatter(xs, [math.log2(r[m] / r["D"]) for r in rs], marker=mk, alpha=0.8, color=colr[(t, ans)],
                           label=f"{t} {ans}")
        ax.axhline(0, color="k", lw=0.8)
        ax.set_xticks(range(3))
        ax.set_xticklabels(TYPES)
        ax.set_title(f"log2({NAME[m]} / D)")
    axes[0].set_ylabel("log2 time ratio (<0: faster than D)")
    axes[1].legend(fontsize=7, loc="upper right")
    fig.suptitle("Fig 2. forcephase vs default per instance (all 54; within a type S/M/L left to right)")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig2_ratios.png"), dpi=130)


def fig3():
    fig, ax = plt.subplots(figsize=(10, 3.6))
    labels, bottoms = [], None
    cells = [(t, s) for t in TYPES for s in SCALES]
    import collections
    counts = {m: [] for m in ACTS}
    for t, s in cells:
        c = collections.Counter(r["winner"] for r in rows if r["type"] == t and r["scale"] == s)
        for m in ACTS:
            counts[m].append(c.get(m, 0))
        labels.append(f"{t}\n{s}")
    bottom = [0] * len(cells)
    for m in ACTS:
        ax.bar(range(len(cells)), counts[m], bottom=bottom, color=COL[m], label=NAME[m])
        bottom = [b + v for b, v in zip(bottom, counts[m])]
    ax.set_xticks(range(len(cells)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("instances")
    ax.legend()
    ax.set_title("Fig 3. Fastest action per cell (6 instances each)")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig3_winners.png"), dpi=130)


def fig4():
    fe = json.load(open(os.path.join(RES, "features_dev.json")))["instances"]
    p = os.path.join(RES, "features_holdout.json")
    if os.path.exists(p):
        fe.update(json.load(open(p))["instances"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, f in zip(axes, ("p_bin_frac", "b07_confdepth_neg_log2")):
        for t, mk in zip(TYPES, ("o", "s", "^")):
            rs = [r for r in rows if r["type"] == t and r["instance"] in fe]
            ax.scatter([fe[r["instance"]]["features"][f] for r in rs], [math.log2(r["Fm"] / r["D"]) for r in rs],
                       marker=mk, alpha=0.75, label=t)
        ax.axhline(0, color="k", lw=0.8)
        ax.set_xlabel(f)
        ax.set_ylabel("log2(F− / D)")
        ax.legend(fontsize=8)
    fig.suptitle("Fig 4. Cheap structural indicators vs F− advantage (features separate types, not SAT/UNSAT)")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig4_features.png"), dpi=130)


def fig5():
    hold = [r for r in rows if r["split"] == "holdout" and r.get("W") is not None]
    if not hold:
        return
    hold.sort(key=lambda r: (r["type"], r["scale"], r["instance"]))
    fig, ax = plt.subplots(figsize=(11, 3.8))
    xs = range(len(hold))
    for k, (m, lab) in enumerate((("D", "D"), ("Fm", "SBS = F−"), ("W", "selector W"), ("oracle", "oracle"))):
        ax.bar([x + 0.2 * k - 0.3 for x in xs], [r[m] for r in hold], width=0.2,
               color={"D": COL["D"], "Fm": COL["Fm"], "W": "#c44e52", "oracle": COL["oracle"]}[m], label=lab)
    ax.set_yscale("log")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([r["instance"].replace("v8-", "") for r in hold], rotation=70, fontsize=7)
    ax.set_ylabel("CPU s")
    ax.legend(fontsize=8)
    ax.set_title("Fig 5. Held-out instances: D, SBS, frozen selector (incl. observation), oracle")
    fig.tight_layout()
    fig.savefig(os.path.join(REP, "fig5_holdout.png"), dpi=130)


if __name__ == "__main__":
    os.makedirs(REP, exist_ok=True)
    for f in (fig1, fig2, fig3, fig4, fig5):
        f()
    print("figures written")
