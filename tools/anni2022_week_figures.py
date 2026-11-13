"""Figures for the week-2026-11-16 report (static PNGs, light surface; default categorical palette in fixed order).

  PY tools/anni2022_week_figures.py --data DATA --analysis ANALYSIS --out FIG_DIR
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anni2022_probe_lib as P  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.grid": True, "grid.color": GRID,
                     "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
                     "legend.frameon": False, "lines.linewidth": 2, "axes.axisbelow": True})


def cumulative(a, costs, names, out):
    fig, ax = plt.subplots(figsize=(8, 5))
    for j, (label, key) in enumerate(names):
        c = costs[key]; solved = np.sort(c[c < 1200])
        ax.step(np.r_[0, solved, 600], np.r_[0, np.arange(1, len(solved) + 1), len(solved)], where="post", color=SERIES[j], label=f"{label} ({len(solved)})")
    ax.set(xlim=(0, 600), xlabel="total CPU s per instance (fees, probes and solver; budget 600 s)", ylabel="instances solved (verified)",
           title="Solved within the 600 CPU s budget, 4719 instances")
    ax.legend(loc="lower right"); fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def level_figure(a, out):
    probe = json.loads((Path(a.analysis) / "probe.json").read_text())["level_hypothesis"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), gridspec_kw={"width_ratios": [1, 1.3]})
    ws = ["w0.5", "w2", "w5"]; x = np.arange(len(ws)); bw = 0.26
    lo = [probe[w]["level_ema"]["lowest_is_best_share"] for w in ws]
    cl = [probe[w]["conflict_level_mean"]["lowest_is_best_share"] for w in ws]
    db = [probe[w]["level_ema"]["D_is_best_share"] for w in ws]
    for k, (vals, lab) in enumerate(((lo, "mode with lowest level EMA"), (cl, "mode with lowest mean conflict level"), (db, "always D (reference)"))):
        axes[0].bar(x + (k - 1) * bw, vals, bw - 0.02, color=SERIES[k], label=lab)
    axes[0].axhline(1 / 3, color=INK2, linestyle="--", linewidth=1); axes[0].text(2.45, 1 / 3 + 0.01, "chance 1/3", color=INK2, ha="right", fontsize=9)
    axes[0].set(xticks=x, xticklabels=["0.5 s", "2 s", "5 s"], ylim=(0, 0.6), ylabel="share of instances where it is the best mode",
                title="Does the lowest early level pick the best mode?")
    axes[0].legend(loc="upper left", fontsize=8.5)
    # scatter at w = 2: relative level difference F+ vs D against log10 cost ratio
    rows = sorted(csv.DictReader(open(Path(a.data) / "cluster_v3_analysis/matrix.csv")), key=lambda r: r["instance_key"])
    keys = [r["instance_key"] for r in rows]; probes = P.load_probes(Path(a.data) / "week20261116/probe5", keys)
    xs, ys = [], []
    for r, k in zip(rows, keys):
        if P.probe_phase(probes[k], 2.0)[0]: continue
        f = P.features(probes[k], 2.0)
        if f["D"] is None or f["Fplus"] is None: continue
        cd, cf = float(r["D_par2"]), float(r["Fplus_par2"])
        if cd == cf: continue
        xs.append((f["Fplus"]["level_ema"] - f["D"]["level_ema"]) / max(abs(f["D"]["level_ema"]), 1e-9)); ys.append(math.log10(cf / cd))
    xs, ys = np.clip(xs, -1.5, 1.5), np.array(ys)
    axes[1].scatter(xs, ys, s=10, color=SERIES[0], alpha=0.35, linewidths=0)
    axes[1].axhline(0, color=INK2, linewidth=1); axes[1].axvline(0, color=INK2, linewidth=1)
    s = probe["w2"]["level_ema"]["F+_vs_D"]["spearman_rel_level_vs_log_cost_ratio"]
    axes[1].set(xlabel="(level F+ - level D) / level D at 2 s  (clipped to +-1.5)", ylabel="log10(final cost F+ / final cost D)",
                title=f"F+ vs D at 2 s: Spearman rho = {s['rho']:.3f} (n = {s['n']}, p = {s['p']:.2f})")
    axes[1].text(-1.45, 2.6, "F+ worse", color=INK2, fontsize=9); axes[1].text(-1.45, -2.9, "F+ better", color=INK2, fontsize=9)
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def family_figure(a, out):
    fam = json.loads((Path(a.analysis) / "family.json").read_text())
    st = fam["per_policy"]["static_cluster"]; top = st["top_family_contributions_s"]
    names = [t[0] for t in top][::-1]; vals = [t[1] / 3600 for t in top][::-1]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(names, vals, color=[SERIES[0] if v >= 0 else SERIES[1] for v in vals], height=0.6)
    ax.axvline(0, color=INK2, linewidth=1)
    g = fam["static_family_grouped_cv"]["gain_vs_D_pct"]; b = st["balanced_5_per_family_gain_pct"]
    ax.set(xlabel="PAR-2 hours saved vs D (negative = lost)",
           title=f"Static selector: largest family contributions (of {fam['families']} families)\n"
                 f"overall {st['overall_gain_pct']:.2f}% | without top family {st['gain_without_top_family_pct']:.2f}%\n"
                 f"5 per family {b['mean']:.2f}% | whole families held out in training {g:.2f}%")
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def summary_figure(a, out):
    fam = json.loads((Path(a.analysis) / "family.json").read_text())["per_policy"]
    items = [("static selector (42 inputs)", "static_cluster"), ("+ unique-literal features", "ablation_base42+unique"),
             ("+ unit features", "ablation_base42+unit"), ("+ unique + unit", "ablation_base42+unique+unit"),
             ("2 s probes + learned choice", "probe_w2_continue_learned:dynamic"), ("2 s probes + lowest level", "probe_w2_continue_rule:min_level_ema"),
             ("F-largest (fixed)", "flargest"), ("F+ (fixed)", "Fplus"), ("F- (fixed)", "Fminus")]
    items = [(l, k) for l, k in items if k in fam]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    y = np.arange(len(items))[::-1]
    for yi, (label, key) in zip(y, items):
        c = fam[key]["family_bootstrap_gain_ci"]
        ax.plot([c["q2.5"], c["q97.5"]], [yi, yi], color=INK2, linewidth=1.5)
        ax.plot([c["point"]], [yi], "o", color=SERIES[0] if c["point"] >= 0 else SERIES[1], markersize=8)
        ax.text(max(c["q97.5"], c["point"]) + 0.6, yi, f"{c['point']:.2f}%", va="center", fontsize=9, color=INK)
    ax.axvline(0, color=INK2, linewidth=1)
    ax.set(yticks=y, yticklabels=[l for l, _ in items], xlabel="PAR-2 change vs always D, % (95% family-cluster bootstrap)",
           title="Selection methods and fixed modes vs D (4719 instances, 600 CPU s)")
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def main():
    p = argparse.ArgumentParser(); [p.add_argument(x, required=True) for x in ("--data", "--analysis", "--out")]; a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = sorted(csv.DictReader(open(Path(a.data) / "cluster_v3_analysis/matrix.csv")), key=lambda r: r["instance_key"])
    costs = {m: np.array([float(r[m + "_par2"]) for r in rows]) for m in ("D", "Fplus", "Fminus")}
    costs["VBS"] = np.minimum.reduce([costs["D"], costs["Fplus"], costs["Fminus"]])
    for f in (Path(a.analysis) / "costs").glob("*.npy"): costs[f.stem] = np.load(f)
    names = [("D", "D"), ("F+", "Fplus"), ("F-", "Fminus"), ("static selector", "static_cluster"),
             ("2 s probes + learned choice", "probe_w2_continue_learned:dynamic"), ("VBS {D,F+,F-}", "VBS")]
    if "flargest" in costs: names.insert(3, ("F-largest", "flargest"))
    cumulative(a, costs, names, out / "fig1_cumulative_solved.png")
    level_figure(a, out / "fig2_level_hypothesis.png")
    family_figure(a, out / "fig3_family_contributions.png")
    summary_figure(a, out / "fig4_methods_vs_D.png")
    print(sorted(p.name for p in out.glob("*.png")))


if __name__ == "__main__":
    main()
