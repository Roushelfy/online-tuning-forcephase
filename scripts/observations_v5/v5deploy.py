#!/usr/bin/env python3
"""V3 of goal v5: real wrapper runs on dev (fold models) and on the
confirmation set (final models + fixed D / F+ / F-), protocol section 9.

  $FP_PY scripts/observations_v5/v5deploy.py [--confirm]

Real cost = whole wrapper process tree CPU (wait4) if the answer is verified
within T, else PAR2 600. Compares each dev instance's real cost and decision
with the offline simulation of v5select (same fold model).
Writes results/observations_v5/deploy_dev.csv (and deploy_confirm.csv) and
reports/observations_v5/DEPLOY_TABLES.md.
"""

import argparse
import collections
import csv
import json
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "three_way"))
import twdata as TD  # noqa: E402
import v5data as VD  # noqa: E402
import v5select as VS  # noqa: E402

ROOT = VD.ROOT
PAR2, T = VD.PAR2, VD.T
GL = {"D-adv": "D 优势", "Fp-adv": "F+ 优势", "Fm-adv": "F− 优势", "close": "接近", "all-timeout": "全部超时"}


def real_cost(rec):
    if rec is None:
        return None
    return rec["total_cpu"] if rec["status"] == "solved" else PAR2


def wrap_summary(rec):
    res = rec.get("result") or {}
    obs = (res.get("obsprofile") or {}).get("cpu", 0.0) + sum(a["cpu"] for a in res.get("arms", []))
    formal = (res.get("formal") or {}).get("cpu")
    return {"status": rec["status"], "total_cpu": rec["total_cpu"], "action": res.get("action"), "path": res.get("path"),
            "decision": res.get("decision"), "obs_component_cpu": obs, "formal_cpu": formal,
            "overhead_cpu": res.get("overhead_cpu"), "wrapper_extra": rec["total_cpu"] - obs - (formal or 0.0),
            "verified": (rec.get("verification") or {}).get("ok"), "result": rec.get("result_label")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    st = pickle.load(open(os.path.join(VS.RES, "selection_state.pkl"), "rb"))
    strategies = json.load(open(os.path.join(VS.RES, "strategies.json")))
    D = VD.Dev(kappa=st["meta"]["kappa"])
    boot = VS.Boot(D.fam)
    c0 = D.c0[:, 0]
    smap = os.path.join(ROOT, "configs", "observations_v5", "frozen", "strategy_map_dev.json")
    recs = VD.load_records("wrap", os.path.join(ROOT, "configs", "three_way", "dev_hashes.txt"), strategy_map=smap,
                           version="deploy_dev")
    L = ["# 部署表（由 `scripts/observations_v5/v5deploy.py` 生成）", ""]
    rows = []
    L += ["## 1. dev 401 真实运行（每题用其家族被留出那一折的模型）", "",
          "| 策略 | 完成 | 解出 | 真实 PAR2 | 真实净收益（相对始终 D） | 离线模拟 PAR2 | 动作与离线一致 | 真实成本 − 模拟成本：中位 / 最大绝对差 | 平均观察 CPU（真实） | wrapper 额外 CPU 中位 |",
          "|---|---:|---:|---:|---|---:|---:|---|---:|---:|"]
    for sname, cname in strategies.items():
        sim_res = st["oof"][cname][0]
        real = np.full(D.n, np.nan)
        agree = done = 0
        diffs, obs, extra = [], [], []
        for i, h in enumerate(D.h):
            key = [k for k in recs if k[0] == h and k[4] and os.path.basename(k[4]).startswith(sname + "_")]
            rec = recs[key[0]] if key else None
            if rec is None:
                continue
            done += 1
            s = wrap_summary(rec)
            real[i] = real_cost(rec)
            sim_act = VD.ACTS[sim_res["choice"][i]]
            real_act = s["action"] if s["decision"] != "probe" else sim_act
            agree += (real_act == sim_act) or (s["decision"] == "probe")
            diffs.append(real[i] - sim_res["cost"][i])
            obs.append(s["obs_component_cpu"])
            extra.append(s["wrapper_extra"])
            rows.append({"strategy": sname, "comparison": cname, "hash": h, "family_group": D.fam[i], "group": D.group[i],
                         "sim_choice": sim_act, "sim_cost": round(float(sim_res["cost"][i]), 4), "real_cost": round(float(real[i]), 4),
                         "cost_D_noobs": c0[i], **s})
        ok = ~np.isnan(real)
        if ok.sum() == 0:
            continue
        g, lo, hi = boot.mean_ci(np.where(ok, c0 - np.nan_to_num(real), 0.0)) if ok.all() else (float("nan"),) * 3
        dd = np.array(diffs)
        L.append(f"| {sname} = `{cname}` | {done}/{D.n} | {int((real[ok] < PAR2).sum())} | {np.nanmean(real):.2f} | "
                 f"{100 * g / c0.mean():+.2f}% [{100 * lo / c0.mean():+.2f}, {100 * hi / c0.mean():+.2f}] | {sim_res['cost'][ok].mean():.2f} | "
                 f"{agree}/{done} | {np.median(dd):+.3f} / {np.max(np.abs(dd)):.1f} | {np.mean(obs):.3f} | {np.median(extra):.3f} |")
    L += ["", f"始终 D（固定运行，不观察）PAR2 = {c0.mean():.2f}。真实成本含观察、决策、正式求解和 wrapper 自身的全部 CPU。", ""]
    if rows:
        big = sorted(rows, key=lambda r: -abs(r["real_cost"] - r["sim_cost"]))[:8]
        L += ["真实与模拟成本差最大的实例：", "", "| 策略 | 实例 | 组 | 模拟动作 | 真实动作/路径 | 模拟成本 | 真实成本 | 状态 |", "|---|---|---|---|---|---:|---:|---|"]
        for r in big:
            L.append(f"| {r['strategy']} | {r['hash'][:12]} | {GL.get(r['group'], r['group'])} | {r['sim_choice']} | {r['action']}/{r['path']} | "
                     f"{r['sim_cost']:.1f} | {r['real_cost']:.1f} | {r['status']} |")
        L.append("")
        with open(os.path.join(VS.RES, "deploy_dev.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    if a.confirm:
        cf = os.path.join(ROOT, "configs", "observations_v5", "confirm_hashes.txt")
        hs = [l.split()[0] for l in open(cf) if l.strip() and not l.startswith("#")]
        fam = {l.split()[0]: l.split()[3] for l in open(cf) if l.strip() and not l.startswith("#")}
        fx = TD.fixed_records(os.path.join(ROOT, "configs", "observations_v5", "v5_confirm_fixed.json"))
        fr = os.path.join(ROOT, "configs", "observations_v5", "frozen")
        wr = VD.load_records("wrap", cf, strategy=",".join(os.path.join(fr, f"{s}_final.json") for s in strategies),
                             version="confirm")
        crow = []
        C = {a_: [] for a_ in ("D", "Fp", "Fm")}
        W = {s: [] for s in strategies}
        missing = 0
        for h in hs:
            r = {"hash": h, "family_group": fam[h]}
            for a_ in ("D", "Fp", "Fm"):
                rec = fx.get(h, {}).get(a_)
                if rec is None or rec.get("status") == "missing":
                    missing += 1
                    c = np.nan
                else:
                    c = TD.cost(rec)
                r[f"status_{a_}"] = rec.get("status") if rec else "missing"
                r[f"cost_{a_}"] = c
                C[a_].append(c)
            for s in strategies:
                key = [k for k in wr if k[0] == h and k[4] and os.path.basename(k[4]).startswith(s + "_")]
                rec = wr[key[0]] if key else None
                c = real_cost(rec) if rec else np.nan
                if rec is None:
                    missing += 1
                else:
                    sm = wrap_summary(rec)
                    r[f"{s}_action"], r[f"{s}_path"], r[f"{s}_status"] = sm["action"], sm["path"], sm["status"]
                    r[f"{s}_obs_cpu"] = sm["obs_component_cpu"]
                r[f"cost_{s}"] = c
                W[s].append(c)
            r["oracle"] = np.nanmin([r["cost_D"], r["cost_Fp"], r["cost_Fm"]])
            crow.append(r)
        cb = VS.Boot([r["family_group"] for r in crow])
        cD = np.array(C["D"])
        L += [f"## 2. 确认集（{len(hs)} 题，{len(set(fam.values()))} 个家族组；冻结后运行）", "",
              f"缺失运行：{missing}。", "",
              "| 策略 | 解出 | PAR2 | 相对 D 的净收益 [95% 家族 cluster 区间] | 偏离 F+/F− | 试跑答出 |", "|---|---:|---:|---|---|---:|"]
        for name, arr, extra in ([("D", C["D"], None), ("F+", C["Fp"], None), ("F−", C["Fm"], None)] +
                                 [(f"{s} = `{strategies[s]}`", W[s], s) for s in strategies] +
                                 [("事后最优（不可部署）", [r["oracle"] for r in crow], None)]):
            x = np.array(arr, float)
            if np.isnan(x).any():
                L.append(f"| {name} | — | — | 运行未完成 | | |")
                continue
            g, lo, hi = cb.mean_ci(cD - x)
            devs = probe = ""
            if extra:
                devs = f"{sum(r.get(f'{extra}_action') == 'Fp' and r.get(f'{extra}_path') != 'probe_answer' for r in crow)}/" \
                       f"{sum(r.get(f'{extra}_action') == 'Fm' and r.get(f'{extra}_path') != 'probe_answer' for r in crow)}"
                probe = str(sum(r.get(f"{extra}_path") == "probe_answer" for r in crow))
            L.append(f"| {name} | {int((x < PAR2).sum())} | {x.mean():.2f} | {100 * g / cD.mean():+.1f}% [{100 * lo / cD.mean():+.1f}, {100 * hi / cD.mean():+.1f}] | {devs} | {probe} |")
        L.append("")
        with open(os.path.join(VS.RES, "deploy_confirm.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in crow for k in r)))
            w.writeheader()
            w.writerows(crow)
    open(os.path.join(VS.REP, "DEPLOY_TABLES.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
