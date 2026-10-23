#!/usr/bin/env python3
"""Export the two main strategies of goal v5 (protocol section 9).

  $FP_PY scripts/observations_v5/v5export.py

For S1 / S2 (results/observations_v5/strategies.json):
  configs/observations_v5/frozen/{S1,S2}_fold{k}.json   outer-fold models
      (fit on the other 4 folds with the inner-CV hyperparameters of the CV),
      used for the real deployment on dev (each instance gets the model of the
      fold its family was held out from);
  configs/observations_v5/frozen/{S1,S2}_final.json     fit on all of dev with
      hyperparameters chosen by 3-fold family CV on all of dev, used for the
      confirmation set.
Checks that the exported pure-Python inference (v5lib.decide on the
obsfeat features) reproduces the CV choices of every dev instance.
Writes configs/observations_v5/frozen/strategy_map_dev.json and
results/observations_v5/export_check.json.
"""

import json
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_panels  # noqa: E402
import obsfeat  # noqa: E402
import v5data as VD  # noqa: E402
import v5lib  # noqa: E402
import v5select as VS  # noqa: E402

ROOT = VD.ROOT
FROZEN = VS.FROZEN


def reader_json(r, theta):
    out = VS.strip(r)
    out["theta"] = theta
    return out


def final_folds(D):
    of = make_panels.balanced_folds(D.fam, 3, VS.SEED, "final")
    return np.array([of[f] for f in D.fam])


def main():
    st = pickle.load(open(os.path.join(VS.RES, "selection_state.pkl"), "rb"))
    meta = st["meta"]
    strategies = json.load(open(os.path.join(VS.RES, "strategies.json")))
    D = VD.Dev(kappa=meta["kappa"])
    os.makedirs(FROZEN, exist_ok=True)
    allt = np.ones(D.n, bool)
    ff = final_folds(D)
    check = {}
    smap = {h: [] for h in D.h}
    for sname, cname in strategies.items():
        pkg, rd = cname.split("|")
        kind = {"RG": "ridge", "TG": "tree", "RF": "forest"}[rd]
        folds = meta["folds"][cname]
        oof_choice = st["oof"][cname][0]["choice"]
        mism = 0
        if pkg != "R11":
            P = D.package(pkg)
            for fdesc in folds:
                k, hp, th = fdesc["fold"], fdesc["hp"], fdesc["theta"]
                r = VS.fit_reader(kind, hp, P, (D.outer != k) & P["consulted"])
                obj = {"name": f"{sname}_{pkg}_{rd}_fold{k}", "package": pkg, "reader": reader_json(r, th),
                       "source": f"v5select CV, outer fold {k} held out", "hp": hp}
                path = os.path.join(FROZEN, f"{sname}_fold{k}.json")
                json.dump(obj, open(path, "w"))
                for i in np.nonzero(D.outer == k)[0]:
                    smap[D.h[i]].append(os.path.relpath(path, ROOT))
                    if not P["consulted"][i]:
                        continue
                    f = obsfeat.package_features(pkg, D.obs[i], D.arms[i])
                    act, _ = v5lib.decide(obj["reader"], f)
                    mism += VD.ACTS.index(act) != oof_choice[i]
            hp, th, _ = VS.inner_select(kind, VS.ALPHAS if kind == "ridge" else VS.DEPTHS if kind == "tree" else [None],
                                        P, allt, ff)
            r = VS.fit_reader(kind, hp, P, P["consulted"])
            fin = {"name": f"{sname}_{pkg}_{rd}_final", "package": pkg, "reader": reader_json(r, th),
                   "source": "fit on all dev 401; hyperparameters by 3-fold family CV on dev", "hp": hp}
        else:
            P1, P2 = D.package("R11", stage=1), D.package("R11", stage=2)
            hps = VS.ALPHAS if kind == "ridge" else VS.DEPTHS if kind == "tree" else [None]
            for fdesc in folds:
                k = fdesc["fold"]
                tr = D.outer != k
                r1 = VS.fit_reader(kind, fdesc["hp1"], P1, tr & P1["consulted"])
                r2 = VS.fit_reader(kind, fdesc["hp2"], P2, tr & P2["consulted"])
                obj = {"name": f"{sname}_R11_{rd}_fold{k}", "package": "R11", "stage1": reader_json(r1, fdesc["theta1"]),
                       "stage2": reader_json(r2, fdesc["theta2"]), "theta1": fdesc["theta1"], "theta_ask": fdesc["theta_ask"],
                       "source": f"v5select CV, outer fold {k} held out"}
                path = os.path.join(FROZEN, f"{sname}_fold{k}.json")
                json.dump(obj, open(path, "w"))
                for i in np.nonzero(D.outer == k)[0]:
                    smap[D.h[i]].append(os.path.relpath(path, ROOT))
                    if not P1["consulted"][i]:
                        continue
                    f1 = obsfeat.package_features("R11", D.obs[i], {}, stage=1)
                    a1, g1 = v5lib.decide(obj["stage1"], f1)
                    b1 = max(g1.values())
                    if a1 != "D" and obj["theta1"] is not None and b1 > obj["theta1"]:
                        act = a1
                    elif obj["theta_ask"] is not None and b1 > obj["theta_ask"] and P2["consulted"][i]:
                        act, _ = v5lib.decide(obj["stage2"], obsfeat.package_features("R11", D.obs[i], D.arms[i], stage=2))
                    else:
                        act = "D"
                    mism += VD.ACTS.index(act) != oof_choice[i]
            # final: same two-step procedure as cv_two_stage on all dev with the final folds
            hp1, _, oof1 = VS.inner_select(kind, hps, P1, allt, ff)
            hp2, th2, oof2 = VS.inner_select(kind, hps, P2, allt, ff)
            best = None
            for t1 in VS.THETA1:
                for ta in VS.THETA_ASK:
                    c = VS.two_stage_cost(P1, P2, oof1[hp1], oof2[hp2], t1, ta, th2, allt)
                    key = (round(-c.mean(), 9), VS.theta_key(t1), ta)
                    if best is None or key > best[0]:
                        best = (key, t1, ta)
            _, t1, ta = best
            r1 = VS.fit_reader(kind, hp1, P1, P1["consulted"])
            r2 = VS.fit_reader(kind, hp2, P2, P2["consulted"])
            fin = {"name": f"{sname}_R11_{rd}_final", "package": "R11", "stage1": reader_json(r1, t1),
                   "stage2": reader_json(r2, th2), "theta1": t1, "theta_ask": ta,
                   "source": "fit on all dev 401; hyperparameters by 3-fold family CV on dev", "hp1": hp1, "hp2": hp2}
        json.dump(fin, open(os.path.join(FROZEN, f"{sname}_final.json"), "w"))
        check[sname] = {"comparison": cname, "fold_model_choice_mismatches": int(mism),
                        "final": {k: v for k, v in fin.items() if k in ("hp", "hp1", "hp2", "theta1", "theta_ask")} |
                        ({"theta": fin["reader"]["theta"]} if "reader" in fin else {"theta2": fin["stage2"]["theta"]})}
        print(sname, cname, "mismatches", mism, check[sname]["final"])
    json.dump(smap, open(os.path.join(FROZEN, "strategy_map_dev.json"), "w"), indent=0)
    json.dump(check, open(os.path.join(VS.RES, "export_check.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
