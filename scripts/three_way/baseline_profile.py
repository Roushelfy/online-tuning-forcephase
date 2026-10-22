#!/usr/bin/env python3
"""S1a + S1b: three fixed actions on the dev panel, winner groups and their
observable characteristics (docs/THREE_WAY_PROTOCOL.md sections 5-7).

  $FP_PY scripts/three_way/baseline_profile.py [--out reports/three_way]

Reads only dev (train + val) records. Writes
  results/three_way/dev_fixed.csv        per (instance, action) run
  results/three_way/winner_profiles.csv  per instance: costs, group, features
  reports/three_way/BASELINE_PROFILE.md  + figures/
"""

import argparse
import collections
import csv
import math
import os
import random
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import twdata as TD  # noqa: E402
import twlib  # noqa: E402

ACTS, LBL, PAR2, T = TD.ACTS, TD.LABEL, TD.PAR2, TD.T
MARGINS = (1.5, 1.2, 2.0)  # primary first
SEED = 20261022


def group_of(costs, statuses, margin):
    if any(s not in ("solved", "timeout") for s in statuses.values()):
        return "invalid", None, None, ""
    if all(s == "timeout" for s in statuses.values()):
        return "all-timeout", None, None, ""
    order = sorted(ACTS, key=lambda a: (costs[a], ACTS.index(a)))
    best, second = order[0], order[1]
    m = (costs[second] + 1) / (costs[best] + 1)
    near = "|".join(a for a in ACTS if (costs[a] + 1) / (costs[best] + 1) < margin)
    if m >= margin:
        sub = "exclusive" if statuses[second] != "solved" else "faster"
        return f"{best}-adv", sub, m, near
    return "close", None, m, near


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    if ok.sum() < 8 or np.nanstd(x[ok]) == 0:
        return float("nan")
    return stats.spearmanr(x[ok], y[ok]).correlation


def within_family(x, fam):
    """Rank-transform, then centre within family (family-demeaned ranks)."""
    x = np.asarray(x, float)
    r = np.full_like(x, np.nan)
    ok = ~np.isnan(x)
    r[ok] = stats.rankdata(x[ok])
    out = np.full_like(x, np.nan)
    for f in set(fam):
        idx = [i for i, g in enumerate(fam) if g == f and ok[i]]
        if len(idx) >= 2:
            out[idx] = r[idx] - r[idx].mean()
    return out


def cluster_boot_rho(x, y, fam, n=1000, seed=SEED):
    fams = sorted(set(fam))
    by = collections.defaultdict(list)
    for i, f in enumerate(fam):
        by[f].append(i)
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        idx = [i for f in rng.choices(fams, k=len(fams)) for i in by[f]]
        v = spearman([x[i] for i in idx], [y[i] for i in idx])
        if not math.isnan(v):
            vals.append(v)
    vals.sort()
    if len(vals) < 50:
        return (float("nan"), float("nan"))
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def fmt(x, d=2):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(TD.ROOT, "reports", "three_way"))
    a = ap.parse_args()
    figdir = os.path.join(a.out, "figures")
    os.makedirs(figdir, exist_ok=True)
    man = TD.manifest()
    dev = TD.split_hashes("dev")
    assert all(man[h]["split"] in ("train", "val") for h in dev)
    fixed = TD.fixed_records(os.path.join(TD.ROOT, "configs", "three_way", "tw_dev_fixed.json"))
    prof = TD.twrun_records("profile", TD.hashes_file("dev"))
    probe = TD.twrun_records("probe", TD.hashes_file("dev"))

    # ------------------------------------------------ per-run table (S1a)
    runrows = []
    for h in dev:
        for act in ACTS:
            r = fixed[h][act]
            runrows.append({"hash": h, "action": LBL[act], "status": r["status"], "cpu": r.get("cpu"),
                            "cost": TD.cost(r), "result": r.get("result"),
                            "verified_by": (r.get("verification") or {}).get("method"),
                            "run_id": r.get("run_id"), "exp": r.get("exp"), "reused": int(r["_reused_from"] is not None)})
    with open(os.path.join(TD.ROOT, "results", "three_way", "dev_fixed.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(runrows[0]))
        w.writeheader()
        w.writerows(runrows)

    # ------------------------------------------------ per-instance profile rows
    rows = []
    for h in dev:
        m = man[h]
        st = {a_: fixed[h][a_]["status"] for a_ in ACTS}
        c = {a_: TD.cost(fixed[h][a_]) for a_ in ACTS}
        res = {fixed[h][a_].get("result") for a_ in ACTS} - {None}
        row = {"hash": h, "split": m["split"], "year": m["quota_year"], "family_group": m["family_group"],
               "stratum": m["stratum"], "prior_exposure": m["prior_exposure"], "gbd_result": m["gbd_result"],
               "observed_result": "conflict" if len(res) > 1 else (res.pop() if res else "unknown")}
        for a_ in ACTS:
            row[f"status_{a_}"] = st[a_]
            row[f"cost_{a_}"] = round(c[a_], 4)
        for mg in MARGINS:
            g, sub, mval, near = group_of(c, st, mg)
            sfx = "" if mg == MARGINS[0] else f"_m{mg}"
            row["group" + sfx] = g
            if mg == MARGINS[0]:
                row["subtype"] = sub or ""
                row["margin"] = None if mval is None else round(mval, 4)
                row["near_best"] = near
        row["oracle"] = min(c.values())
        row["r_Fp"] = math.log2((c["Fp"] + 1) / (c["D"] + 1))
        row["r_Fm"] = math.log2((c["Fm"] + 1) / (c["D"] + 1))
        p = prof.get(h)
        sf = twlib.static_features(p["profile"]) if p else {k: None for k in twlib.STATIC_FEATURES}
        row.update(sf)
        row["profile_cpu"] = p["profile"].get("cpu") if p else None
        for b in TD.BUDGETS:
            pr = probe.get((h, b))
            tag = f"b{b:g}"
            if pr is None:
                row[f"probe_{tag}_solved"] = None
                continue
            row[f"probe_{tag}_solved"] = int(pr["solved"])
            row[f"probe_{tag}_cpu"] = pr["cpu"]
            pf = twlib.probe_features(pr, p["profile"] if p else {"error": "missing"})
            for k, v in pf.items():
                row[f"{k}@{tag}"] = v
        rows.append(row)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(TD.ROOT, "results", "three_way", "winner_profiles.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # ------------------------------------------------ S1a summary
    L = ["# S1：dev 面板上三种固定动作的逐题对照与优势组特点", "",
         "由 `scripts/three_way/baseline_profile.py` 生成；只读 dev（train + val，401 个实例）记录。规则见 "
         "[THREE_WAY_PROTOCOL.md](../../docs/THREE_WAY_PROTOCOL.md) 第 5–7 节；逐题数据见 "
         "`results/three_way/winner_profiles.csv` 与 `dev_fixed.csv`。cost = 解出时的 CPU 秒，否则 PAR2 = 600。", ""]
    n = len(rows)
    stat_cnt = collections.Counter((r["action"], r["status"]) for r in runrows)
    reused = sum(r["reused"] for r in runrows)
    L += ["## 1. 运行与验证", "",
          f"- {len(runrows)} 次运行（{n} 实例 × 3 动作）：复用第一轮 {reused} 次，本轮新跑 {len(runrows) - reused} 次。",
          "- 状态：" + "；".join(f"{LBL[a_]} " + ", ".join(f"{s} {stat_cnt[(LBL[a_], s)]}" for s in
                                                       sorted({s for (x, s) in stat_cnt if x == LBL[a_]})) for a_ in ACTS),
          "- 每个 solved 都经过独立检查（SAT：checkmodel；UNSAT：lrat-trim）。", ""]
    # per-action table
    def summary(sel, act=None, oracle=False):
        cs = [r["oracle"] if oracle else r[f"cost_{act}"] for r in sel]
        solved = sum(x < PAR2 for x in cs)
        return solved, sum(cs) / len(cs)
    tab = ["| 动作 | solved | SAT | UNSAT | mean PAR2 | train PAR2 | val PAR2 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for act in ACTS:
        s_, p_ = summary(rows, act)
        sat = sum(1 for r in rows if r[f"status_{act}"] == "solved" and r["observed_result"] == "SAT")
        uns = sum(1 for r in rows if r[f"status_{act}"] == "solved" and r["observed_result"] == "UNSAT")
        tr = summary([r for r in rows if r["split"] == "train"], act)[1]
        va = summary([r for r in rows if r["split"] == "val"], act)[1]
        tab.append(f"| {LBL[act]} | {s_} | {sat} | {uns} | {p_:.1f} | {tr:.1f} | {va:.1f} |")
    s_, p_ = summary(rows, oracle=True)
    tab.append(f"| hindsight oracle（不可部署） | {s_} | | | {p_:.1f} | {summary([r for r in rows if r['split']=='train'], oracle=True)[1]:.1f} | "
               f"{summary([r for r in rows if r['split']=='val'], oracle=True)[1]:.1f} |")
    best_fixed = min(ACTS, key=lambda a_: summary(rows, a_)[1])
    L += ["## 2. 三动作总体对照（S1a）", ""] + tab + [""]
    gains = sorted((r[f"cost_{best_fixed}"] - r["oracle"] for r in rows), reverse=True)
    tot = sum(gains)
    pos = [g for g in gains if g > 1e-9]
    L += [f"- dev 上 mean PAR2 最低的固定动作：**{LBL[best_fixed]}**（候选的“最佳固定动作”，第 8 节正式确定）。",
          f"- oracle 相对 {LBL[best_fixed]} 的总增益 {tot:.0f} 秒（每题平均 {tot / n:.1f} 秒，"
          f"{100 * tot / sum(r[f'cost_{best_fixed}'] for r in rows):.1f}%）；有正增益的实例 {len(pos)} 个，"
          f"前 10 个占 {100 * sum(gains[:10]) / tot:.0f}%，前 25 个占 {100 * sum(gains[:25]) / tot:.0f}%。", ""]
    # pairwise
    L += ["两两比较（x-only = 只有 x 解出；faster = 两者都解出且 (c_y+1)/(c_x+1) ≥ 1.5）：", "",
          "| x vs y | x-only | y-only | x faster | y faster | 都解出且接近 | 都未解出 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for x, y in (("D", "Fp"), ("D", "Fm"), ("Fp", "Fm")):
        xo = sum(r[f"status_{x}"] == "solved" and r[f"status_{y}"] != "solved" for r in rows)
        yo = sum(r[f"status_{y}"] == "solved" and r[f"status_{x}"] != "solved" for r in rows)
        both = [r for r in rows if r[f"status_{x}"] == "solved" and r[f"status_{y}"] == "solved"]
        xf = sum((r[f"cost_{y}"] + 1) / (r[f"cost_{x}"] + 1) >= 1.5 for r in both)
        yf = sum((r[f"cost_{x}"] + 1) / (r[f"cost_{y}"] + 1) >= 1.5 for r in both)
        nn = sum(r[f"status_{x}"] != "solved" and r[f"status_{y}"] != "solved" for r in rows)
        L.append(f"| {LBL[x]} vs {LBL[y]} | {xo} | {yo} | {xf} | {yf} | {len(both) - xf - yf} | {nn} |")
    L.append("")

    # ------------------------------------------------ groups
    order = ["D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout", "invalid"]
    glabel = {"D-adv": "D 优势", "Fp-adv": "F+ 优势", "Fm-adv": "F− 优势", "close": "差距很小", "all-timeout": "三者都超时", "invalid": "无可靠结果"}
    L += ["## 3. 优势分组（S1b，margin 阈值 1.5；敏感性 1.2 / 2.0）", "",
          "| 组 | 实例（m=1.5） | 其中 exclusive | 其中 faster | m=1.2 | m=2.0 | train | val | 组内 PAR2 收益（相对" + LBL[best_fixed] + "，秒） |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for g in order:
        sel = [r for r in rows if r["group"] == g]
        gain = sum(r[f"cost_{best_fixed}"] - r["oracle"] for r in sel)
        L.append(f"| {glabel[g]} | {len(sel)} | {sum(r['subtype'] == 'exclusive' for r in sel)} | "
                 f"{sum(r['subtype'] == 'faster' for r in sel)} | {sum(r['group_m1.2'] == g for r in rows)} | "
                 f"{sum(r['group_m2.0'] == g for r in rows)} | {sum(r['split'] == 'train' for r in sel)} | "
                 f"{sum(r['split'] == 'val' for r in sel)} | {gain:.0f} |")
    close = collections.Counter(r["near_best"] for r in rows if r["group"] == "close")
    L += ["", "“差距很小”组的近优集合：" + "，".join(f"{k.replace('Fp', 'F+').replace('Fm', 'F−')} {v}" for k, v in close.most_common()), ""]
    # by year / result
    L += ["按配额年与事后结果（observed：任一动作解出时的答案）：", "",
          "| 组 | " + " | ".join(("2022", "2023", "2024", "2025", "2026")) + " | SAT | UNSAT | unknown |",
          "|---|" + "---:|" * 8]
    for g in order:
        sel = [r for r in rows if r["group"] == g]
        L.append(f"| {glabel[g]} | " + " | ".join(str(sum(r["year"] == y for r in sel)) for y in ("2022", "2023", "2024", "2025", "2026"))
                 + " | " + " | ".join(str(sum(r["observed_result"] == x for r in sel)) for x in ("SAT", "UNSAT", "unknown")) + " |")
    # families
    fam = collections.defaultdict(list)
    for r in rows:
        fam[r["family_group"]].append(r)
    L += ["", "### 家族集中度", "",
          "每个优势组中实例最多的家族（括号内为该家族 dev 实例总数）：", ""]
    for g in ("D-adv", "Fp-adv", "Fm-adv"):
        c = collections.Counter(r["family_group"] for r in rows if r["group"] == g)
        tot_g = sum(c.values())
        L.append(f"- {glabel[g]}（{tot_g}，来自 {len(c)} 个家族）：" +
                 "，".join(f"{k} {v}（{len(fam[k])}）" for k, v in c.most_common(8)))
    L += ["", "家族级别（dev 实例 ≥ 5 的家族；PAR2 秒，cost 最低者加粗）：", "",
          "| 家族组 | n | D | F+ | F− | D/F+/F− 优势 | close | 都超时 |", "|---|---:|---:|---:|---:|---|---:|---:|"]
    for k in sorted(fam, key=lambda k: -len(fam[k])):
        sel = fam[k]
        if len(sel) < 5:
            continue
        par = {a_: sum(r[f"cost_{a_}"] for r in sel) / len(sel) for a_ in ACTS}
        b_ = min(par, key=par.get)
        cells = [(f"**{par[a_]:.0f}**" if a_ == b_ else f"{par[a_]:.0f}") for a_ in ACTS]
        L.append(f"| {k} | {len(sel)} | " + " | ".join(cells) + " | " +
                 "/".join(str(sum(r["group"] == f"{a_}-adv" for r in sel)) for a_ in ACTS) +
                 f" | {sum(r['group'] == 'close' for r in sel)} | {sum(r['group'] == 'all-timeout' for r in sel)} |")
    L.append("")

    # ------------------------------------------------ features vs groups
    fam_of = [r["family_group"] for r in rows]
    informative = [i for i, r in enumerate(rows) if r["group"] not in ("all-timeout", "invalid")]
    feats = [(k, k, "静态") for k in twlib.STATIC_FEATURES]
    for b in TD.BUDGETS:
        feats += [(f"{k}@b{b:g}", f"{k}@{b:g}s", "试跑") for k in twlib.PROBE_FEATURES if k not in ("q_started",)]
    resp = {"r_F+": [rows[i]["r_Fp"] for i in informative], "r_F−": [rows[i]["r_Fm"] for i in informative],
            "r_F+ − r_F−": [rows[i]["r_Fp"] - rows[i]["r_Fm"] for i in informative]}
    famI = [fam_of[i] for i in informative]
    splitI = [rows[i]["split"] for i in informative]
    res_rows = []
    for col, name, kind in feats:
        x = [rows[i].get(col) for i in informative]
        x = [np.nan if v is None else float(v) for v in x]
        if np.all(np.isnan(x)):
            continue
        rec = {"feature": name, "kind": kind}
        for rn, y in resp.items():
            rho = spearman(x, y)
            lo, hi = cluster_boot_rho(x, y, famI, n=400)
            rw = spearman(within_family(x, famI), within_family(y, famI))
            rtr = spearman([x[j] for j in range(len(x)) if splitI[j] == "train"], [y[j] for j in range(len(y)) if splitI[j] == "train"])
            rva = spearman([x[j] for j in range(len(x)) if splitI[j] == "val"], [y[j] for j in range(len(y)) if splitI[j] == "val"])
            if not math.isnan(lo) and (lo > 0 or hi < 0):
                same = all((not math.isnan(v)) and np.sign(v) == np.sign(rho) and abs(v) >= 0.1 for v in (rw, rtr, rva))
                lab = "稳定" if same else "相关"
            else:
                lab = "未确认"
            rec[rn] = (rho, lo, hi, rw, rtr, rva, lab)
        res_rows.append(rec)
    L += ["## 4. 可观察特点：特征与相对 D 的代价比", "",
          f"响应量（{len(informative)} 个非“都超时 / 无可靠结果”实例）：r_F+ = log2((c_F+ + 1)/(c_D + 1))，r_F− 同理；"
          "负值表示比 D 快。ρ 为 Spearman；CI 为按家族组的 cluster bootstrap（400 次）；ρ_fam 为家族内中心化后的秩相关；"
          "train/val 为两个 split 分别计算的 ρ。标签：**稳定** = CI 不含 0，且家族内、train、val 三个 ρ 都与整体同号、绝对值都 ≥ 0.1；"
          "**相关** = CI 不含 0，但不满足其余条件；**未确认** = CI 含 0。", ""]
    for rn in resp:
        top = sorted([r for r in res_rows if rn in r], key=lambda r: -abs(r[rn][0] if not math.isnan(r[rn][0]) else 0))[:14]
        L += [f"### {rn}：|ρ| 最大的 14 个特征", "", "| 特征 | 类 | ρ [CI] | ρ_fam | ρ train / val | 标签 |", "|---|---|---|---:|---|---|"]
        for r in top:
            rho, lo, hi, rw, rtr, rva, lab = r[rn]
            L.append(f"| {r['feature']} | {r['kind']} | {fmt(rho)} [{fmt(lo)}, {fmt(hi)}] | {fmt(rw)} | {fmt(rtr)} / {fmt(rva)} | {lab} |")
        L.append("")
    cnt = collections.Counter((r["kind"], r[rn][6]) for r in res_rows for rn in resp if rn in r)
    L += ["标签计数（全部特征 × 3 个响应量）：" + "，".join(f"{k[0]}-{k[1]} {v}" for k, v in sorted(cnt.items())), ""]

    # hypothesis: polarity
    L += ["### 极性假说（“正文字多 → F+，负文字多 → F−”）", ""]
    for k in ("p_pos_lit_frac", "p_var_bal_mean", "p_allneg_cls_frac", "p_allpos_cls_frac", "p_binneg_frac"):
        r = next(x for x in res_rows if x["feature"] == k)
        rho, lo, hi, rw, rtr, rva, lab = r["r_F+ − r_F−"]
        L.append(f"- {k} 与 r_F+ − r_F−：ρ = {fmt(rho)} [{fmt(lo)}, {fmt(hi)}]，家族内 {fmt(rw)}，train/val {fmt(rtr)}/{fmt(rva)} → {lab}")
    L.append("")

    # group medians for a fixed list of features
    show = ["p_log_vars", "p_cv_ratio", "p_len_mean", "p_bin_frac", "p_pos_lit_frac", "p_horn_frac", "p_antihorn_frac",
            "p_allneg_cls_frac", "p_var_bal_mean", "p_var_absbal_mean", "p_occ_cv"]
    L += ["### 各组的静态特征中位数 [四分位]", "", "| 特征 | " + " | ".join(glabel[g] for g in order[:5]) + " |", "|---|" + "---|" * 5]
    for k in show:
        cells = []
        for g in order[:5]:
            v = np.array([r[k] for r in rows if r["group"] == g and r[k] is not None], float)
            cells.append("—" if not len(v) else f"{np.median(v):.3g} [{np.percentile(v, 25):.3g}, {np.percentile(v, 75):.3g}]")
        L.append(f"| {k} | " + " | ".join(cells) + " |")
    L.append("")
    # probe stats per group at 2 s
    pshow = ["q_log_conflicts", "q_conf_per_sec_log", "q_neg_dec_frac", "q_saved_src_frac", "q_cp_saved_neg_frac", "q_fixed_frac", "q_learned_len"]
    for b in TD.BUDGETS:
        tag = f"b{b:g}"
        solved = sum(1 for r in rows if r.get(f"probe_{tag}_solved") == 1)
        L.append(f"- 试跑 {b:g} s：dev 上直接解出 {solved} 个实例（D 的前缀，已验证）；"
                 f"平均试跑 CPU {np.mean([r[f'probe_{tag}_cpu'] for r in rows if r.get(f'probe_{tag}_cpu') is not None]):.3f} s。")
    L += ["", "各组的 2 s 试跑统计中位数：", "", "| 特征 | " + " | ".join(glabel[g] for g in order[:5]) + " |", "|---|" + "---|" * 5]
    for k in pshow:
        cells = []
        for g in order[:5]:
            v = np.array([r.get(f"{k}@b2") for r in rows if r["group"] == g and r.get(f"{k}@b2") is not None], float)
            cells.append("—" if not len(v) else f"{np.median(v):.3g}")
        L.append(f"| {k} | " + " | ".join(cells) + " |")
    L.append("")

    # ------------------------------------------------ figures
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = {"D": "#2a78d6", "Fp": "#eda100", "Fm": "#1baf7a", "oracle": "#52514e"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    # cactus
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for act in ACTS:
        xs = sorted(r[f"cost_{act}"] for r in rows if r[f"status_{act}"] == "solved")
        ax.plot(range(1, len(xs) + 1), xs, label=f"{LBL[act]} ({len(xs)})", color=col[act], lw=1.8)
    xs = sorted(r["oracle"] for r in rows if r["oracle"] < PAR2)
    ax.plot(range(1, len(xs) + 1), xs, label=f"oracle ({len(xs)})", color=col["oracle"], lw=1.2, ls="--")
    ax.set_yscale("log"); ax.set_xlabel("solved instances (dev, 401)"); ax.set_ylabel("CPU seconds")
    ax.grid(alpha=.3); ax.legend(frameon=False); ax.set_title("Three fixed actions on dev: cactus", loc="left")
    fig.tight_layout(); fig.savefig(os.path.join(figdir, "dev_cactus.png"), dpi=150); plt.close(fig)
    # groups + gain concentration
    fig, axs = plt.subplots(1, 2, figsize=(9.6, 3.8))
    cnts = [sum(r["group"] == g for r in rows) for g in order]
    elabel = {"D-adv": "D better", "Fp-adv": "F+ better", "Fm-adv": "F- better", "close": "close", "all-timeout": "all time out", "invalid": "invalid"}
    axs[0].barh([elabel[g] for g in order][::-1], cnts[::-1], color=["#2a78d6", "#eda100", "#1baf7a", "#a7a6a0", "#d8d7d0", "#e87ba4"][::-1])
    for i, v in enumerate(cnts[::-1]):
        axs[0].text(v + 2, i, str(v), va="center")
    axs[0].set_xlabel("dev instances"); axs[0].set_title("Winner groups (margin 1.5)", loc="left")
    cum = np.cumsum(gains) / tot if tot > 0 else np.zeros(len(gains))
    axs[1].plot(range(1, len(gains) + 1), 100 * cum, color="#52514e")
    axs[1].set_xscale("log"); axs[1].set_xlabel(f"instances, sorted by oracle gain over {LBL[best_fixed]}")
    axs[1].set_ylabel("% of total oracle gain"); axs[1].grid(alpha=.3); axs[1].set_title("Gain concentration", loc="left")
    fig.tight_layout(); fig.savefig(os.path.join(figdir, "dev_groups.png"), dpi=150); plt.close(fig)
    # feature distributions
    fshow = ["p_pos_lit_frac", "p_var_bal_mean", "p_log_vars", "p_bin_frac", "p_horn_frac", "p_allneg_cls_frac",
             "q_neg_dec_frac@b2", "q_conf_per_sec_log@b2"]
    fig, axs = plt.subplots(2, 4, figsize=(12, 5.6))
    gl = order[:5]
    for ax, k in zip(axs.flat, fshow):
        data = [[r.get(k) for r in rows if r["group"] == g and r.get(k) is not None] for g in gl]
        ax.boxplot(data, tick_labels=["D", "F+", "F-", "close", "TO"], showfliers=False)
        for j, d in enumerate(data):
            ax.scatter(np.random.RandomState(j).normal(j + 1, 0.06, len(d)), d, s=5, alpha=.35, color="#52514e")
        ax.set_title(k, fontsize=9); ax.grid(alpha=.25)
    fig.suptitle("Candidate features by winner group (dev; TO = all three time out)", x=0.01, ha="left")
    fig.tight_layout(); fig.savefig(os.path.join(figdir, "dev_features_by_group.png"), dpi=150); plt.close(fig)
    L += ["## 5. 图", "", "![cactus](figures/dev_cactus.png)", "", "![groups](figures/dev_groups.png)", "",
          "![features](figures/dev_features_by_group.png)", ""]
    open(os.path.join(a.out, "BASELINE_PROFILE_tables.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
