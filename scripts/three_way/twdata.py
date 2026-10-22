"""Data access for the three-way analyses (dev or test panel).

Loads the fixed-action fprun records (by run id, so only the requested
panel's records are touched), the static profiles and the D probes
written by twrun.py, and the panel manifest.
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import fprun  # noqa: E402
import twlib  # noqa: E402
import twrun  # noqa: E402

ROOT = twlib.ROOT
T = 300.0
PAR2 = 2 * T
ACTS = twlib.ACTION_ORDER  # D, Fp, Fm
LABEL = {"D": "D", "Fp": "F+", "Fm": "F−"}
BUDGETS = (0.1, 0.5, 2.0)


def manifest():
    return {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "manifest.csv")))}


def split_hashes(split):
    path = os.path.join(ROOT, "configs", "three_way", f"{split}_hashes.txt")
    return [l.split()[0] for l in open(path) if l.strip() and not l.startswith("#")]


def fixed_records(exp_path):
    """{hash: {action: record}} for a fixed-action experiment (missing -> absent)."""
    exp = fprun.load_experiment(exp_path)
    name2act = {v[0]: k for k, v in twlib.ACTIONS.items()}
    out = {}
    for r in fprun.plan(exp):
        p = fprun.result_path(r["run_id"])
        rec = json.load(open(p)) if os.path.exists(p) else {"status": "missing", "run_id": r["run_id"]}
        rec["_action"] = name2act[r["config"]]
        rec["_reused_from"] = rec.get("exp") if rec.get("exp") != exp["name"] else None
        out.setdefault(r["key"]["instance"], {})[name2act[r["config"]]] = rec
    return out


def cost(rec):
    return rec["cpu"] if rec.get("status") == "solved" else PAR2


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def twrun_records(kind, hashes_file, budgets=None, model=None):
    a = Args(cmd=kind, hashes=hashes_file, budgets=",".join(map(str, budgets or BUDGETS)), model=model)
    out = {}
    for k, key, rid in twrun.plan(a):
        p = twrun.rec_path(k, rid)
        rec = json.load(open(p)) if os.path.exists(p) else None
        if kind == "probe":
            out[(key["instance"], key["budget"])] = rec
        else:
            out[key["instance"]] = rec
    return out


def hashes_file(split):
    return os.path.join(ROOT, "configs", "three_way", f"{split}_hashes.txt")
