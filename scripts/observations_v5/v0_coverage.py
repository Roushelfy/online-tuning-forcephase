#!/usr/bin/env python3
"""V0 of goal v5: real coverage of the v4 observations and where the v4
selectors lost (only existing v4 records; no new solver run).

  $FP_PY scripts/observations_v5/v0_coverage.py

Reads results/three_way/winner_profiles.csv (dev), the v4 D-probe records,
results/three_way/test_results.csv and the v4 wrapper records (historical
test). Re-runs the 12 v4 CV candidates with the v4 code (twselect.py, same
folds and kappa) to get per-instance out-of-fold choices.

Writes results/observations_v5/v0_*.csv and reports/observations_v5/V0_TABLES.md
(included in COVERAGE_AND_ERRORS.md).
"""

import collections
import csv
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "three_way"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import twdata as TD  # noqa: E402
import twselect as TS  # noqa: E402

RES = os.path.join(ROOT, "results", "observations_v5")
REP = os.path.join(ROOT, "reports", "observations_v5")
KAPPA = 0.08  # v4 wrapper constant (THREE_WAY_PROTOCOL.md)
ACTS, LBL, PAR2, T = TD.ACTS, TD.LABEL, TD.PAR2, TD.T
GROUPS = ("D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout")
GLBL = {"D-adv": "D 优势", "Fp-adv": "F+ 优势", "Fm-adv": "F− 优势", "close": "接近", "all-timeout": "全部超时"}


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def pct(a, b):
    return "—" if not b else f"{100.0 * a / b:.0f}%"


# ------------------------------------------------------------ 1. coverage

def coverage(rows):
    probe = TD.twrun_records("probe", TD.hashes_file("dev"))
    out, table = [], []
    for b in TD.BUDGETS:
        cnt = collections.defaultdict(collections.Counter)
        for r in rows:
            pr = probe.get((r["hash"], b))
            g = r["group"]
            for key in ("all", g):
                c = cnt[key]
                c["n"] += 1
                if pr is None:
                    c["missing_record"] += 1
                    continue
                st, fin = pr.get("stats") or {}, pr.get("final") or {}
                conf, dec = st.get("conflicts") or 0, st.get("decisions") or 0
                src = fin.get("dec_src") or [0] * 7
                c["solved"] += int(pr["solved"])
                c["no_final"] += int(not fin)
                c["started"] += int(conf > 0 or dec > 0)
                c["conf_ge_100"] += int(conf >= 100)
                c["restart"] += int((fin.get("restarts") or st.get("restarts") or 0) > 0)
                c["checkpoint"] += int(bool((pr.get("checkpoint") or {}).get("f")))
                c["stable"] += int((fin.get("stabphases") or 0) > 0)
                c["target_dec"] += int((src[3] or 0) > 0)
                c["rephased"] += int((fin.get("rephased") or 0) > 0)
                c["elim_stat"] += int("eliminated" in st)
                out.append({"hash": r["hash"], "budget": b, "group": g, "cpu": pr["cpu"], "solved": int(pr["solved"]),
                            "conflicts": conf, "decisions": dec, "restarts": fin.get("restarts"),
                            "stabphases": fin.get("stabphases"), "rephased": fin.get("rephased"),
                            "target_dec": src[3], "checkpoint": int(bool((pr.get("checkpoint") or {}).get("f"))),
                            "has_final": int(bool(fin))})
        table.append((b, cnt))
    return out, table


def feature_missing(rows):
    """Share of dev rows where each v4 probe feature is missing (None/NaN), per budget."""
    import twlib
    res = {}
    for b in TD.BUDGETS:
        tag = f"b{b:g}"
        res[b] = {k: sum(fnum(r.get(f"{k}@{tag}")) is None for r in rows) / len(rows) for k in twlib.PROBE_FEATURES}
    return res


# --------------------------------------------- 2. per-instance OOF errors

def oof_choices(rows):
    D = TS.Data(rows, KAPPA)
    fold = TS.folds(D.fam)
    out = {}
    for b, m in TS.CANDIDATES:
        names, X = D.features(b)
        C, o, ps = D.sim_costs(b)
        pred = np.zeros(D.n, int)
        for k in range(5):
            tr, te = fold != k, fold == k
            model = TS.fit(m, X[tr], C[tr], names)
            pred[te] = TS.predict_all(model, X[te], names)
        out[(b, m)] = (pred, C[np.arange(D.n), pred], C, o, ps)
    return D, fold, out


def decompose(dcost, cost, choice, probe_solved, d_solved, sel_solved):
    """Contributions (seconds, summed) to cost - dcost, i.e. positive = loss vs always-D (no observation)."""
    diff = cost - dcost
    cat = []
    for i in range(len(cost)):
        if probe_solved[i]:
            c = "probe answered"
        elif choice[i] == 0:
            c = "kept D"
        elif diff[i] < -1e-9:
            c = "deviation, right"
        elif diff[i] > 1e-9:
            c = "deviation, wrong"
        else:
            c = "deviation, tie"
        cat.append(c)
    flips = ["solved→timeout" if d_solved[i] and not sel_solved[i] else
             "timeout→solved" if (not d_solved[i]) and sel_solved[i] else "" for i in range(len(cost))]
    return diff, cat, flips


def magnitude(x):
    a = abs(x)
    return "<1 s" if a < 1 else "1–10 s" if a < 10 else "10–100 s" if a < 100 else "≥100 s"


def main():
    os.makedirs(RES, exist_ok=True)
    os.makedirs(REP, exist_ok=True)
    rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "winner_profiles.csv")))]
    n = len(rows)
    L = ["# V0 表格（由 `scripts/observations_v5/v0_coverage.py` 生成）", ""]

    # ---- coverage
    cov_rows, table = coverage(rows)
    with open(os.path.join(RES, "v0_probe_coverage.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cov_rows[0]))
        w.writeheader()
        w.writerows(cov_rows)
    L += ["## A. v4 D 试跑的真实覆盖（dev 401）", "",
          "每格是满足条件的实例比例。started = 有任何决策或冲突；restart / stable / target 决策 / rephase 取自遥测 final 记录；"
          "checkpoint = 达到 1,000 次冲突、写出 checkpoint 特征（v4 的 6 个 q_cp_* 特征只在此时有值）。", "",
          "| 预算 | 组 | n | 试跑解出 | started | ≥100 冲突 | ≥1 restart | checkpoint | 进入 stable | 有 target 决策 | rephase 过 |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for b, cnt in table:
        for key in ("all",) + GROUPS:
            c = cnt[key]
            L.append(f"| {b:g} s | {'全部' if key == 'all' else GLBL[key]} | {c['n']} | {pct(c['solved'], c['n'])} | "
                     f"{pct(c['started'], c['n'])} | {pct(c['conf_ge_100'], c['n'])} | {pct(c['restart'], c['n'])} | "
                     f"{pct(c['checkpoint'], c['n'])} | {pct(c['stable'], c['n'])} | {pct(c['target_dec'], c['n'])} | "
                     f"{pct(c['rephased'], c['n'])} |")
    L.append("")
    nofinal = {b: cnt["all"]["no_final"] for b, cnt in table}
    L += [f"缺 final 遥测记录：" + "，".join(f"{b:g} s {v} 题" for b, v in nofinal.items()) + "（多为解析/初始化还没结束就到预算）。", ""]
    miss = feature_missing(rows)
    import twlib
    L += ["### v4 试跑特征的缺失率（dev，None/NaN 的比例）", "",
          "| 特征 | 0.1 s | 0.5 s | 2 s |", "|---|---:|---:|---:|"]
    for k in twlib.PROBE_FEATURES:
        L.append(f"| `{k}` | {miss[0.1][k]:.0%} | {miss[0.5][k]:.0%} | {miss[2.0][k]:.0%} |")
    L += ["", "v4 的树把缺失编码成哨兵值 −10，logistic 用训练集中位数填补；两者都没有单独的缺失指示。"
          "`q_target_src_frac` 等比例在没进入 stable 时是 0 而不是缺失：它表示“机制尚未触发”，不是“观察到 target 不起作用”。", ""]

    # ---- OOF errors
    D, fold, oof = oof_choices(rows)
    dcost = D.c[:, 0]
    d_solved = D.solved[:, 0]
    L += ["## B. v4 选择器的逐题收益与损失（dev，家族 5 折 OOF；v4 代码、折与 κ 原样重跑）", "",
          "收益/损失相对“不观察、始终 D”（dev PAR2 382.10）。正数 = 比始终 D 差（损失秒数之和 / 401）。"
          "“保留 D”一行的损失只来自观察开销（及开销把 D 推过截止的情况）。", ""]
    per_inst = []
    summ = []
    for (b, m), (pred, cost, C, o, ps) in oof.items():
        sel_solved = cost < PAR2
        diff, cat, flips = decompose(dcost, cost, pred, ps, d_solved, sel_solved)
        name = f"{'static' if b is None else f'probe{b:g}'}-{m}"
        cc = collections.defaultdict(lambda: [0, 0.0])
        for i in range(n):
            cc[cat[i]][0] += 1
            cc[cat[i]][1] += diff[i]
        fl = collections.Counter(f for f in flips if f)
        summ.append({"candidate": name, "par2": cost.mean(), "vs_D_pct": 100 * (dcost.mean() - cost.mean()) / dcost.mean(),
                     **{f"n_{k}": cc[k][0] for k in ("kept D", "deviation, right", "deviation, wrong", "deviation, tie", "probe answered")},
                     **{f"sec_{k}": cc[k][1] / n for k in ("kept D", "deviation, right", "deviation, wrong", "deviation, tie", "probe answered")},
                     "solved_to_timeout": fl["solved→timeout"], "timeout_to_solved": fl["timeout→solved"]})
        if (b, m) in ((None, "logreg"), (0.1, "logreg")):
            for i in range(n):
                per_inst.append({"candidate": name, "hash": D.rows[i]["hash"], "family_group": D.fam[i], "fold": int(fold[i]),
                                 "group": D.rows[i]["group"], "choice": LBL[ACTS[pred[i]]], "cost": round(cost[i], 4),
                                 "cost_D": dcost[i], "diff_vs_D": round(diff[i], 4), "category": cat[i], "flip": flips[i],
                                 "magnitude": magnitude(diff[i]), "overhead": round(o[i], 4)})
    with open(os.path.join(RES, "v0_oof_errors.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_inst[0]))
        w.writeheader()
        w.writerows(per_inst)
    with open(os.path.join(RES, "v0_oof_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0]))
        w.writeheader()
        w.writerows(summ)
    L += ["| 候选 | OOF PAR2 | 相对 D | 保留 D：题数 / 秒 | 正确偏离：题数 / 秒 | 错误偏离：题数 / 秒 | 试跑解出：题数 / 秒 | D 解出→超时 | D 超时→解出 |",
          "|---|---:|---:|---|---|---|---|---:|---:|"]
    for s in summ:
        L.append(f"| {s['candidate']} | {s['par2']:.2f} | {s['vs_D_pct']:+.1f}% | {s['n_kept D']} / {s['sec_kept D']:+.2f} | "
                 f"{s['n_deviation, right']} / {s['sec_deviation, right']:+.2f} | {s['n_deviation, wrong']} / {s['sec_deviation, wrong']:+.2f} | "
                 f"{s['n_probe answered']} / {s['sec_probe answered']:+.2f} | {s['solved_to_timeout']} | {s['timeout_to_solved']} |")
    L += ["", "秒数是该类实例的 (选择器成本 − D 成本) 之和除以 401，即对 mean PAR2 差的贡献；负 = 节省。"
          "偏离为平手的实例（两者都超时等）未列出，贡献为 0。", ""]

    # magnitude breakdown for the two v4 picks
    L += ["### 两个 v4 冻结流程（static-logreg、probe0.1-logreg）的偏离按幅度分解", "",
          "| 候选 | 类别 | <1 s | 1–10 s | 10–100 s | ≥100 s | 合计秒/401 |", "|---|---|---:|---:|---:|---:|---:|"]
    for name in ("static-logreg", "probe0.1-logreg"):
        sel = [r for r in per_inst if r["candidate"] == name]
        for catg in ("deviation, right", "deviation, wrong"):
            mm = collections.Counter(r["magnitude"] for r in sel if r["category"] == catg)
            tot = sum(r["diff_vs_D"] for r in sel if r["category"] == catg) / n
            L.append(f"| {name} | {catg} | {mm['<1 s']} | {mm['1–10 s']} | {mm['10–100 s']} | {mm['≥100 s']} | {tot:+.2f} |")
    L.append("")
    # concentration of the losses
    for name in ("static-logreg", "probe0.1-logreg"):
        sel = sorted((r for r in per_inst if r["candidate"] == name), key=lambda r: -r["diff_vs_D"])
        loss = [r for r in sel if r["diff_vs_D"] > 0]
        tot = sum(r["diff_vs_D"] for r in loss)
        top10 = sum(r["diff_vs_D"] for r in loss[:10])
        gain = [r for r in sel if r["diff_vs_D"] < 0]
        L.append(f"- {name}：损失实例 {len(loss)} 个共 {tot:.0f} 秒，前 10 个占 {pct(top10, tot)}；"
                 f"收益实例 {len(gain)} 个共 {-sum(r['diff_vs_D'] for r in gain):.0f} 秒。"
                 f"前 10 大损失中 D 解出→超时 {sum(r['flip'] == 'solved→timeout' for r in loss[:10])} 个。")
    L.append("")

    # ---- logistic weights vs absolute regret
    srt = np.sort(D.c, 1)
    w = np.log2((srt[:, 1] + 1) / (srt[:, 0] + 1))
    absreg = srt[:, 1] - srt[:, 0]
    keep = w > 1e-9
    from scipy import stats as sst
    rho = sst.spearmanr(w[keep], absreg[keep]).correlation
    top = np.argsort(-w)[:40]
    micro = int(sum(srt[i, 1] < 10 for i in top))
    small = keep & (absreg < 10)
    L += ["## C. v4 logistic 的样本权重与真实绝对损失", "",
          f"v4 logistic 的权重是 log2((第二名 + 1)/(第一名 + 1))。在权重 > 0 的 {int(keep.sum())} 个 dev 实例上，"
          f"它与“第二名 − 第一名”的绝对秒数的 Spearman ρ = {rho:.2f}。权重最高的 40 个实例中，有 {micro} 个第二名也在 10 秒内解出。"
          f"绝对差 < 10 秒的 {int(small.sum())} 个实例占权重总量的 {w[small].sum() / w[keep].sum():.1%}，"
          f"却只占绝对差总量的 {absreg[small].sum() / absreg[keep].sum():.1%}。"
          "因此在这个面板上，log 倍数权重与绝对秒数大体同序，但仍把一部分权重放在几秒级的题上；更关键的是它只学“谁最好”，"
          "不区分偏离 D 的收益和把 D 可解题送到超时的损失（最多 600 − t_D 秒）。v4 的成本树直接最小化模拟成本，所以“成本敏感”在 v4 中并非完全没做；"
          "两种读出器共同缺少的是“证据不足时保留 D”的门。", ""]

    # ---- labels: margin distribution and timing repeat
    L += ["## D. 标签与计时检查", ""]
    mg = collections.defaultdict(list)
    for r in rows:
        if r["group"].endswith("-adv"):
            mg[r["group"]].append(fnum(r["margin"]))
    L += ["| 优势组 | n | margin 1.5–2 | 2–10 | ≥10 | 其中 exclusive（只有赢家解出） | 赢家 < 1 s |", "|---|---:|---:|---:|---:|---:|---:|"]
    for g in ("D-adv", "Fp-adv", "Fm-adv"):
        sel = [r for r in rows if r["group"] == g]
        ms = [fnum(r["margin"]) for r in sel]
        a_ = g.split("-")[0]
        L.append(f"| {GLBL[g]} | {len(sel)} | {sum(1.5 <= m < 2 for m in ms)} | {sum(2 <= m < 10 for m in ms)} | {sum(m >= 10 for m in ms)} | "
                 f"{sum(r['subtype'] == 'exclusive' for r in sel)} | {sum(fnum(r['cost_' + a_]) < 1 for r in sel)} |")
    L.append("")
    # timing: v4 test wrapper formal solves vs the fixed run of the same action (same binary/flags/seed)
    tr = [r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "test_results.csv")))]
    ratios = []
    for r in tr:
        for m in ("static", "probe"):
            if r[f"decision_{m}"] != "formal":
                continue
            a_ = r[f"choice_{m}"]
            fc, xc, xs = fnum(r[f"formal_cpu_{m}"]), fnum(r[f"cost_{a_}"]), r[f"status_{a_}"]
            if xs == "solved" and r[f"status_{m}"] == "solved" and fc and xc and xc >= 1:
                ratios.append(fc / xc)
    ratios = np.array(ratios)
    if len(ratios):
        L += [f"计时重复：v4 test 上 wrapper 的正式求解与同一动作固定运行（同二进制、同参数、同 seed）都解出且 ≥ 1 s 的 {len(ratios)} 对，"
              f"CPU 比值中位数 {np.median(ratios):.3f}，5%–95% 分位 {np.quantile(ratios, 0.05):.3f}–{np.quantile(ratios, 0.95):.3f}，"
              f"最大偏差 {np.max(np.abs(ratios - 1)):.3f}。这些是确定性搜索的重复，只反映计时噪声，不反映 seed 敏感性。", ""]
    # historical test decomposition
    L += ["## E. 旧 test99 上两个冻结选择器的逐题分解（历史/已曝光，仅解释，不再用于选择）", ""]
    for m in ("static", "probe"):
        dc = np.array([fnum(r["cost_D"]) for r in tr])
        sc = np.array([fnum(r[f"cost_{m}"]) for r in tr])
        ch = [r[f"choice_{m}"] for r in tr]
        diff = sc - dc
        dev_ = [i for i in range(len(tr)) if ch[i] != "D" and r_dec(tr[i], m)]
        right = sum(diff[i] for i in dev_ if diff[i] < 0)
        wrong = sum(diff[i] for i in dev_ if diff[i] > 0)
        kept = sum(diff[i] for i in range(len(tr)) if ch[i] == "D" or not r_dec(tr[i], m))
        s2t = sum(1 for i in range(len(tr)) if tr[i]["status_D"] == "solved" and tr[i][f"status_{m}"] != "solved")
        t2s = sum(1 for i in range(len(tr)) if tr[i]["status_D"] != "solved" and tr[i][f"status_{m}"] == "solved")
        L.append(f"- {m}：偏离 D {len(dev_)} 题，正确偏离 {sum(diff[i] < 0 for i in dev_)} 题（{right / len(tr):+.2f} 秒/题），"
                 f"错误偏离 {sum(diff[i] > 0 for i in dev_)} 题（{wrong / len(tr):+.2f}）；保留 D 或试跑解出的开销 {kept / len(tr):+.2f}；"
                 f"D 解出→超时 {s2t} 题，D 超时→解出 {t2s} 题。")
    L.append("")
    open(os.path.join(REP, "V0_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


def r_dec(r, m):
    return r[f"decision_{m}"] == "formal"


if __name__ == "__main__":
    main()
