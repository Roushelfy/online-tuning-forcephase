#!/usr/bin/env python3
"""v9 R4 diagnostic sample (protocol section 8): in each of the 9 main development cells, the first 3 SAT
and first 3 UNSAT instances by split-hash order (answers from the complete S1 D runs; diagnosis only),
filled with the other answer when one is short. Writes results/online_selection_v9/mechanism_instances.json.
"""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "configs", "online_selection_v9")
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
split = json.load(open(os.path.join(CFG, "split.json")))
ans = {}
for p in glob.glob(os.path.join(DATA, "runs", "online_selection_v9", "s1_dev", "*.json")):
    if p.endswith(("progress.json", "effective_plan.json")):
        continue
    r = json.load(open(p))
    if r["method"] == "D" and r["status"] == "solved":
        ans[r["instance"]] = {10: "SAT", 20: "UNSAT"}[r["exit_code"]]
chosen, detail = [], {}
for t in ("rand3", "col3", "assign2"):
    for s in ("S", "M", "L"):
        cell = sorted([i for i, v in split.items() if v["split"] == "dev" and v["role"] == "main" and v["type"] == t
                       and v["scale"] == s], key=lambda i: split[i]["split_hash"])
        missing = [i for i in cell if i not in ans]
        if missing:
            raise SystemExit(f"S1 D incomplete in {t}-{s}: {missing}")
        sat = [i for i in cell if ans[i] == "SAT"]
        uns = [i for i in cell if ans[i] == "UNSAT"]
        pick = sat[:3] + uns[:3]
        rest = [i for i in cell if i not in pick]
        pick += rest[:6 - len(pick)]
        chosen += pick
        detail[f"{t}-{s}"] = {"SAT_available": len(sat), "UNSAT_available": len(uns),
                              "picked": {i: ans[i] for i in pick}}
json.dump({"instances": chosen, "cells": detail}, open(os.path.join(ROOT, "results", "online_selection_v9",
                                                                  "mechanism_instances.json"), "w"), indent=1)
print(len(chosen), {k: (v["SAT_available"], v["UNSAT_available"]) for k, v in detail.items()})
