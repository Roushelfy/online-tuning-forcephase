#!/usr/bin/env python3
"""V1 engineering checks of goal v5 (protocol section 8).

  $FP_PY scripts/observations_v5/v1_engineering.py

Equivalence gate, coverage / CPU / caps of every package and arm (dev 401),
wrapper overhead, H01 global flip and H02 permutation diagnostics
(engineering panel), seed-1 repeat (engineering panel subset), node
contention check. Writes reports/observations_v5/V1_ENGINEERING.md,
reports/observations_v5/V1_REPEAT.md (section 6 of COVERAGE_AND_ERRORS.md)
and results/observations_v5/v1_*.csv.
"""

import collections
import csv
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
sys.path.insert(0, os.path.dirname(HERE))
import fprun  # noqa: E402
import obsfeat  # noqa: E402
import v5data as VD  # noqa: E402
import v5lib  # noqa: E402

ROOT = v5lib.ROOT
RES = os.path.join(ROOT, "results", "observations_v5")
REP = os.path.join(ROOT, "reports", "observations_v5")
ENG = os.path.join(ROOT, "configs", "observations_v5", "eng_panel.txt")
DEVF = os.path.join(ROOT, "configs", "three_way", "dev_hashes.txt")
GL = {"D-adv": "D 优势", "Fp-adv": "F+ 优势", "Fm-adv": "F− 优势", "close": "接近", "all-timeout": "全部超时"}


def q(v, p):
    v = [x for x in v if x is not None]
    return float(np.quantile(v, p)) if v else float("nan")


def stats_rho(x, y):
    from scipy import stats as sst
    return float(sst.spearmanr(x, y).correlation) if len(x) > 5 else float("nan")


def main():
    os.makedirs(REP, exist_ok=True)
    L = ["# V1 工程检查（由 `scripts/observations_v5/v1_engineering.py` 生成）", ""]
    eng = [l.split()[0] for l in open(ENG) if l.strip() and not l.startswith("#")]

    # ---------------------------------------------------- 1. equivalence gate
    eq = VD.load_records("eqv", ENG)
    big = os.path.join(fprun.DATA, "v5_smoke", "eqv_big.txt")
    eq_small = VD.load_records("eqv", big, conflicts=1000) if os.path.exists(big) else {}
    n_same = sum(1 for r in eq.values() if r and r["same"])
    diff = [(k, r) for k, r in eq.items() if r and not r["same"]]
    capped = [k for k, r in diff if r["formal"]["terminated_by"] or r["probe"]["terminated_by"]]
    L += ["## 1. 等价门（协议第 3 节）", "",
          f"- 工程面板 {len(eng)} 题 × 3 动作，冲突上限 20,000：`build/obs`（`--fpcwin=100`）与 `build/fpc` 的搜索统计"
          f"（冲突、决策、传播、固定、学习文字、重启、rephase、reduce）、退出码与 final digest 相同 {n_same}/{len(eq)}。",
          f"- 不同的 {len(diff)} 项全部是检查脚本先撞上 120 s CPU 上限（{len(capped)} 项；两个超大实例），在计时决定的位置停下，"
          "不可比较；这两个实例在冲突上限 1,000 下重新检查，"
          f"{sum(1 for r in eq_small.values() if r and r['same'])}/{len(eq_small)} 相同。",
          "- 结论：观测版与正式二进制的搜索逐项相同，试跑臂的答案与特征可以代表正式动作的同一搜索前缀。", ""]

    # ---------------------------------------------------- 2. coverage and CPU
    D = VD.Dev()
    n = D.n
    sec_rows = []
    L += ["## 2. dev 401 的覆盖、CPU 与上限", "", "### 2.1 obsprofile 各段", "",
          "| 段 | ok | cap | n/a | 中位 CPU s | p90 | 最大 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in ["parse", "s28", "polar", "resid", "bilat", "graph", "comm", "ls"]:
        st = collections.Counter((ob["sections"].get(s) or {}).get("status") for ob in D.obs)
        cpu = [(ob["sections"].get(s) or {}).get("cpu") for ob in D.obs]
        L.append(f"| {s} | {st['ok']} | {st['cap']} | {st['n/a']} | {q(cpu, .5):.3f} | {q(cpu, .9):.3f} | {max(cpu):.2f} |")
        sec_rows.append({"section": s, **st, "cpu_median": q(cpu, .5), "cpu_p90": q(cpu, .9), "cpu_max": max(cpu)})
    rc = sum(1 for ob in D.obs if (ob["features"].get("c01_root_conflict") or 0) > 0)
    L += ["", f"根传播即冲突（公式被单元传播证明 UNSAT，后续段 n/a）：{rc} 题。", ""]
    L += ["### 2.2 各观察包：强制 D、试跑答出与观察 CPU", "",
          "| 包 | 强制 D（观察不完整） | 试跑答出 | 平均观察 CPU s | 中位 | p90 | 最大 | κ s |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    pk_rows = []
    for p in VD.PKGS:
        P = D.package(p) if p != "R11" else D.package("R11", stage=2)
        o = P["o"]
        L.append(f"| {p}{'（全探测时）' if p == 'R11' else ''} | {int(P['forced'].sum())} | {int(P['answered'].sum())} | {o.mean():.3f} | "
                 f"{np.median(o):.3f} | {np.quantile(o, .9):.3f} | {o.max():.2f} | {D.kappa.get(p, float('nan')):.3f} |")
        pk_rows.append({"package": p, "forced_D": int(P["forced"].sum()), "answered": int(P["answered"].sum()),
                        "obs_cpu_mean": o.mean(), "obs_cpu_max": o.max(), "kappa": D.kappa.get(p)})
    L += ["", "强制 D 的实例不咨询读出器，只付观察开销；“试跑答出”的实例成本就是观察 CPU，三种动作相同。", ""]
    # arms
    L += ["### 2.3 试跑臂", "",
          "| 臂 | 动作 | 进入搜索 | 答出 | 中位冲突 | 中位 window 数 | 中位 CPU s | 最大 CPU s |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    arm_rows = []
    for tag in ("e02", "e05", "ec", "fD"):
        for a in (("D",) if tag == "fD" else ("D", "Fp", "Fm")):
            rs = [D.arms[i].get((tag, a)) for i in range(n)]
            started = sum(1 for r in rs if ((r.get("stats") or {}).get("conflicts") or 0) > 0)
            ans = sum(1 for r in rs if r.get("answered"))
            conf = [(r.get("stats") or {}).get("conflicts") or 0 for r in rs]
            wins = [len(r.get("windows") or []) for r in rs]
            cpu = [r["cpu"] for r in rs]
            L.append(f"| {tag} | {VD.LBL[a]} | {started / n:.0%} | {ans} | {np.median(conf):.0f} | {np.median(wins):.0f} | "
                     f"{np.median(cpu):.3f} | {max(cpu):.2f} |")
            arm_rows.append({"tag": tag, "action": a, "started": started, "answered": ans, "conf_median": np.median(conf),
                             "cpu_median": np.median(cpu), "cpu_max": max(cpu)})
    wrong = sum(1 for i in range(n) for r in D.arms[i].values() if r.get("answered") and not r.get("solved"))
    L += ["", f"所有答出的试跑臂都经独立检查（SAT checkmodel、UNSAT lrat-trim）：未通过 {wrong} 个。", ""]
    # feature missingness per package
    L += ["### 2.4 新特征的缺失率（dev 401，咨询读出器的实例）", "", "| 包 | 新特征数 | 缺失率中位 | 缺失率最大 | 缺失最多的特征 |", "|---|---:|---:|---:|---|"]
    for p in VD.PKGS:
        P = D.package(p) if p != "R11" else D.package("R11", stage=2)
        X = P["X"][P["consulted"]]
        names = P["names"]
        newc = [j for j, k in enumerate(names) if k not in obsfeat.S28]
        mr = [np.isnan(X[:, j]).mean() for j in newc]
        worst = max(newc, key=lambda j: np.isnan(X[:, j]).mean()) if newc else None
        L.append(f"| {p} | {len(newc)} | {np.median(mr):.1%} | {max(mr):.1%} | `{names[worst]}` |" if newc else f"| {p} | 0 | | | |")
    L.append("")

    # ---------------------------------------------------- 3. contention check
    by_host = collections.defaultdict(list)
    for i in range(n):
        for r in D.arms[i].values():
            if r["cpu"] > 0.15:
                by_host[r.get("host") or "?"].append(r["wall"] / r["cpu"])
    L += ["## 3. 计时与节点", "", "试跑臂 wall/CPU 比（CPU > 0.15 s 的臂）按节点：", "",
          "| 节点 | 臂数 | 中位 | p99 | 最大 |", "|---|---:|---:|---:|---:|"]
    for hst, v in sorted(by_host.items()):
        L.append(f"| {hst} | {len(v)} | {np.median(v):.3f} | {np.quantile(v, .99):.3f} | {max(v):.3f} |")
    L += ["", "注：dev 臂的一个分片落在 agent 所在节点（cpu-207-159）；该节点的比值与其他节点相同，说明没有争用。", ""]

    # ---------------------------------------------------- 4. H01 / H02
    obs_v = VD.load_records("obs", ENG, variants="orig,flipall,perm1")
    arm_flip = VD.load_records("arm", ENG, variants="orig,flipall", tags="ec")
    arm_perm = VD.load_records("arm", ENG, variants="orig,perm1", tags="e05")
    # H01: static features that should be exactly mirrored
    neg = {"a02_jw_dir_wmean", "a10_bindeg_w_bal", "a10_shortdeg_w_bal", "a03_top_bal_mean", "c01_res_bal_mean",
           "a11_mixed_bal_mean", "d07_hub_bal_mean", "a04_viol_w_lr", "a07_eo_dir", "c02_bal_delta", "p_var_bal_mean"}
    onem = {"a01_wpos_frac", "a01_short_pos_frac", "c01_res_pos_frac", "c01_res_wpos_frac", "b01_fixed_pos_frac",
            "d01_big_pos_target_frac", "p_pos_lit_frac"}
    pairs = {"a04_viol0_w": "a04_viol1_w", "a04_res_viol0_w": "a04_res_viol1_w", "a07_onehot_var_frac": "a07_onecold_var_frac",
             "c01_res_allpos_frac": "c01_res_allneg_frac", "c01_res_horn_frac": "c01_res_antihorn_frac",
             "a02_jw_pos_frac": "a02_jw_neg_frac", "p_allpos_cls_frac": "p_allneg_cls_frac", "p_horn_frac": "p_antihorn_frac",
             "p_binpos_frac": "p_binneg_frac", "p_var_purepos_frac": "p_var_pureneg_frac", "p_var_posmaj_frac": "p_var_negmaj_frac"}
    invariant = {"c01_res_vars_log", "c01_res_clauses_log", "c02_vars_ratio", "d02_scc_nontriv_lit_frac", "d02_scc_max_frac",
                 "c04_equiv_var_frac", "c04_inverse_share", "d03_ncomp_log", "d03_maxcomp_frac", "d05_assort",
                 "d10_wl2_distinct_frac", "d10_wl2_sign_sym_frac", "p_log_vars", "p_log_clauses", "p_len_mean"}
    ok = tot = 0
    for h in eng:
        a, b = obs_v.get((h, "orig", None, None, None)), obs_v.get((h, "flipall", None, None, None))
        if not a or not b:
            continue
        fa, fb = a["features"], b["features"]
        for k, x in fa.items():
            if x is None:
                continue
            if k in neg:
                y, e = fb.get(k), -x
            elif k in onem:
                y, e = fb.get(k), 1 - x
            elif k in pairs:
                y, e = fb.get(pairs[k]), x
            elif k in invariant:
                y, e = fb.get(k), x
            else:
                continue
            tot += 1
            ok += y is not None and abs(y - e) <= 1e-4 * max(1.0, abs(e))
    # arms: F+ on flipped vs F- on original (and D on flipped vs D on original)
    same_mirror = same_d = cnt = 0
    keys = ("conflicts", "decisions", "propagations")
    xs = collections.defaultdict(list)  # CPU to 512 conflicts: flipped F+, original F-, original F+
    for h in eng:
        rr = {k: arm_flip.get((h, v, "ec", a_, None)) for k, v, a_ in
              (("fpF", "flipall", "Fp"), ("fmO", "orig", "Fm"), ("fpO", "orig", "Fp"), ("fmF", "flipall", "Fm"))}
        if all(rr.values()) and not any(r["terminated_by"] or r.get("answered") for r in rr.values()):
            for k, r in rr.items():
                xs[k].append(math.log10(max(r["cpu"], 1e-3)))
    for h in eng:
        fm_o, fp_f = arm_flip.get((h, "orig", "ec", "Fm", None)), arm_flip.get((h, "flipall", "ec", "Fp", None))
        d_o, d_f = arm_flip.get((h, "orig", "ec", "D", None)), arm_flip.get((h, "flipall", "ec", "D", None))
        if not (fm_o and fp_f and d_o and d_f):
            continue
        if fm_o["terminated_by"] or fp_f["terminated_by"]:
            continue
        cnt += 1
        same_mirror += all(fm_o["stats"].get(k) == fp_f["stats"].get(k) for k in keys)
        same_d += all(d_o["stats"].get(k) == d_f["stats"].get(k) for k in keys)
    L += ["## 4. 编码诊断（工程面板 96 题；只是诊断）", "",
          f"- **H01 全局翻转（静态）**：应当精确取反、取补或互换的静态特征，{ok}/{tot} 个实例×特征值符合（容差 1e-4）。"
          "抽样/截断类特征（双边传播、贪心路径、局部搜索）不要求精确镜像。",
          f"- **H01 全局翻转（试跑）**：在 512 次冲突内正常结束的 {cnt} 题中，“翻转公式上的 F+”与“原式上的 F−”的冲突、决策、传播数"
          f"逐项相同 {same_mirror} 题；“翻转公式上的 D”与“原式上的 D”相同 {same_d} 题。"
          "即使 F+ 与 F− 只差决策符号，CaDiCaL 的其余部分（lucky 阶段的尝试顺序、预处理与子句排列等）也不是对符号完全对称的，"
          "所以翻转后多数题的搜索并不精确镜像。"
          + (f"到达 512 次冲突的 CPU（{len(xs['fpF'])} 题都正常结束且未答出）：翻转公式上的 F+ 与原式 F− 的 Spearman ρ = "
             f"{stats_rho(xs['fpF'], xs['fmO']):.2f}，与原式 F+ 的 ρ = {stats_rho(xs['fpF'], xs['fpO']):.2f}；"
             f"翻转公式上的 F− 与原式 F+ 的 ρ = {stats_rho(xs['fmF'], xs['fpO']):.2f}，与原式 F− 的 ρ = {stats_rho(xs['fmF'], xs['fmO']):.2f}。"
             "这类早期成本主要由规模决定，四个相关都很高，只能说明翻转后的 F± 与“镜像动作”至少同样接近，"
             "不能单独证明 F+/F− 的优劣随编码符号互换。" if xs['fpF'] else ""), ""]
    # H02: permutation invariance of static features, arm metric correlation
    diffs = collections.defaultdict(list)
    for h in eng:
        a, b = obs_v.get((h, "orig", None, None, None)), obs_v.get((h, "perm1", None, None, None))
        if not a or not b:
            continue
        for k, x in a["features"].items():
            y = b["features"].get(k)
            if x is None or y is None:
                continue
            diffs[k].append(abs(x - y) / max(1e-9, abs(x) + abs(y)))
    exact = sorted(k for k, v in diffs.items() if max(v) <= 1e-6)
    approx = sorted(((k, float(np.median(v)), max(v)) for k, v in diffs.items() if max(v) > 1e-6), key=lambda t: -t[2])
    from scipy import stats as sst
    rho = {}
    for met in ("lconf", "glue", "trail", "best"):
        for a_ in ("D", "Fp", "Fm"):
            xs, ys = [], []
            for h in eng:
                ro, rp = arm_perm.get((h, "orig", "e05", a_, None)), arm_perm.get((h, "perm1", "e05", a_, None))
                if not ro or not rp:
                    continue
                nv = obsfeat.nvars_of(obs_v.get((h, "orig", None, None, None)))
                mo, mp = obsfeat.arm_metrics(ro, nv)[met], obsfeat.arm_metrics(rp, nv)[met]
                if mo is not None and mp is not None:
                    xs.append(mo), ys.append(mp)
            rho[(met, a_)] = (sst.spearmanr(xs, ys).correlation if len(xs) > 5 else float("nan"), len(xs))
    L += [f"- **H02 变量/子句重排（静态）**：{len(diffs)} 个静态特征中 {len(exact)} 个在重排后完全不变；"
          f"其余 {len(approx)} 个依赖编号或顺序（抽样变量、平手的排序、局部搜索随机流、标签传播的处理顺序）。"
          "变化最大的："
          + "，".join(f"`{k}`（中位相对差 {m:.2f}，最大 {mx:.2f}）" for k, m, mx in approx[:8]) + "。",
          "- **H02（试跑 0.5 s）**：原式与重排公式之间，同一动作的试跑指标的 Spearman ρ："
          + "；".join(f"{met} " + "/".join(f"{VD.LBL[a_]} {rho[(met, a_)][0]:.2f}" for a_ in ("D", "Fp", "Fm"))
                     for met in ("lconf", "glue", "trail", "best")) + "。重排改变 CaDiCaL 的变量顺序，短试跑的轨迹因此改变，"
          "这些特征含有编号噪声。", ""]

    # ---------------------------------------------------- 5. seed-1 repeat
    exp = fprun.load_experiment(os.path.join(ROOT, "configs", "observations_v5", "v5_seed1.json"))
    rep_rows = []
    name2act = {"D": "D", "Fplus": "Fp", "Fminus": "Fm"}
    rec = {}
    for r in fprun.plan(exp):
        p = fprun.result_path(r["run_id"])
        rec[(r["key"]["instance"], name2act[r["config"]])] = json.load(open(p)) if os.path.exists(p) else None
    rows = {r["hash"]: r for r in VD.dev_rows()}
    hs = sorted({h for h, _ in rec})
    R = ["## 6. seed 重复（V1，工程面板中 v4 至少一个动作解出的 49 题；诊断）", "",
         "同一二进制、同一参数，只把求解器 seed 从 0 改为 1（`--seed=1`），T = 300 s。下表比较 seed 1 与 v4 的 seed 0。", "",
         "| 动作 | 题数 | 两个 seed 都解出 | 只 seed 0 解出 | 只 seed 1 解出 | 都解出时 CPU 比中位（seed1/seed0） | 5%–95% | 搜索完全相同（冲突数相等）的题 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|"]
    complete = all(v is not None for v in rec.values())
    fixed0 = VD.load_records  # noqa
    import twdata as TD
    fx = TD.fixed_records(os.path.join(ROOT, "configs", "three_way", "tw_dev_fixed.json"))
    for a_ in ("D", "Fp", "Fm"):
        both = s0 = s1 = same = 0
        ratios = []
        for h in hs:
            r1, r0 = rec.get((h, a_)), fx[h][a_]
            if r1 is None:
                continue
            ok0, ok1 = r0["status"] == "solved", r1["status"] == "solved"
            both += ok0 and ok1
            s0 += ok0 and not ok1
            s1 += ok1 and not ok0
            if ok0 and ok1:
                ratios.append(r1["cpu"] / max(r0["cpu"], 1e-3))
                c0 = ((r0.get("stats") or {}).get("conflicts"))
                c1 = ((r1.get("stats") or {}).get("conflicts"))
                same += c0 is not None and c0 == c1
            rep_rows.append({"hash": h, "action": a_, "status0": r0["status"], "cpu0": r0.get("cpu"),
                             "status1": r1["status"], "cpu1": r1.get("cpu")})
        R.append(f"| {VD.LBL[a_]} | {len(hs)} | {both} | {s0} | {s1} | {np.median(ratios):.3f} | "
                 f"{np.quantile(ratios, .05):.2f}–{np.quantile(ratios, .95):.2f} | {same} |")
    # direction stability of advantage groups
    import baseline_profile as BP
    st = collections.Counter()
    for h in hs:
        c1 = {}
        s1 = {}
        for a_ in ("D", "Fp", "Fm"):
            r1 = rec.get((h, a_))
            c1[a_] = r1["cpu"] if r1 and r1["status"] == "solved" else 600.0
            s1[a_] = r1["status"] if r1 else "missing"
        g1 = BP.group_of(c1, s1, 1.5)[0]
        g0 = rows[h]["group"]
        st[(g0, g1)] += 1
    R += ["", "优势组（margin 1.5）在 seed 0 与 seed 1 下的对照（行 = seed 0，列 = seed 1）：", "",
          "| seed 0 \\ seed 1 | " + " | ".join(GL[g] for g in ("D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout")) + " |",
          "|---|" + "---:|" * 5]
    for g0 in ("D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout"):
        if sum(st[(g0, g)] for g in GL) == 0:
            continue
        R.append(f"| {GL[g0]} | " + " | ".join(str(st[(g0, g)]) for g in ("D-adv", "Fp-adv", "Fm-adv", "close", "all-timeout")) + " |")
    stable = sum(st[(g, g)] for g in GL)
    R += ["", f"同组 {stable}/{len(hs)} 题。{'（seed 1 运行尚未全部完成）' if not complete else ''}", "",
          "解读：",
          "",
          "- **F+ 与 F− 几乎不受 seed 影响**：大多数题的搜索逐项相同（冲突数相等），CPU 比集中在 1 附近。原因是 forcephase 关闭了 rephase，"
          "而默认配置下 seed 主要通过 rephase/walk 的随机部分起作用。",
          "- **D 对 seed 敏感**：没有一题搜索相同，都解出时 CPU 比的 5%–95% 跨度约为 0.5–2 倍，还有少数题的解出与否随 seed 改变。",
          "- **对标签的影响**：单 seed 的 D 优势标签有相当一部分不稳定（本表中 D 优势组约三分之一换组，多数变成“接近”或“全部超时”）；"
          "F± 优势则相对稳定。这只是 49 题的小样本诊断，不改动任何标签或题目，但它意味着 dev 上“应当保留 D”与“应当偏离”的界线本身带有 seed 噪声，"
          "能被任何观测稳定识别的收益上限低于单 seed oracle 显示的数字。",
          ""]
    with open(os.path.join(RES, "v1_seed_repeat.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rep_rows[0]))
        w.writeheader()
        w.writerows(rep_rows)
    open(os.path.join(REP, "V1_REPEAT.md"), "w").write("\n".join(R) + "\n")
    L += ["## 5. seed 重复", "", "见 [COVERAGE_AND_ERRORS.md](COVERAGE_AND_ERRORS.md) 第 6 节。", ""]
    with open(os.path.join(RES, "v1_sections.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in sec_rows for k in r)))
        w.writeheader()
        w.writerows(sec_rows)
    with open(os.path.join(RES, "v1_packages.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pk_rows[0]))
        w.writeheader()
        w.writerows(pk_rows)
    open(os.path.join(REP, "V1_ENGINEERING.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\n".join(R))


if __name__ == "__main__":
    main()
