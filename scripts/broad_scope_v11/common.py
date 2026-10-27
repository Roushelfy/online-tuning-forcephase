"""Goal v11 shared definitions (docs/BROAD_SCOPE_PROTOCOL_V11.md section 7). Actions, registered features and probe
parsing are the v10 ones unchanged (scripts/cross_scale_v10/common.py, loaded and re-exported here); v11 adds one
rule in front of the v10 decision:

  out-of-range check: a strategy may carry {"ood": {"lo": {f: v}, "hi": {f: v}, "action": a}}; if any listed
  feature is missing or outside [lo, hi] (bounds fixed from the training fold), the action is the strategy's
  ood action (path 'ood') -- before any reader is consulted. Strategies without "ood" decide exactly as in v10.

A 'tree' reader's leaves hold actions directly, so static trees and the type router (classifier compiled into
family -> training-best action, low-confidence leaves -> fallback) both use the v10 tree code.
Standard library only.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location("common_v10", os.path.join(ROOT, "scripts", "cross_scale_v10", "common.py"))
v10 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v10)

for _k in dir(v10):
    if not _k.startswith("__") and _k != "decide":
        globals()[_k] = getattr(v10, _k)


def out_of_range(strategy, x):
    o = strategy.get("ood")
    if not o:
        return False
    for f, lo in o["lo"].items():
        v = x.get(f)
        if not v10._num(v) or v < lo or v > o["hi"][f]:
            return True
    return False


def decide(strategy, x, arms_started):
    if strategy.get("ood") and out_of_range(strategy, x):
        return strategy["ood"]["action"], "ood"
    return v10.decide(strategy, x, arms_started)
