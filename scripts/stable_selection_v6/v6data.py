"""Data assembly for the goal-v6 selection (dev 401): seed-0 fixed-run costs,
the v5 family folds, and per package the feature table and simulated
wrapper cost matrix (protocol section 4; the cost model of v5 section 5).
"""

import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v6lib  # noqa: E402
import v6run  # noqa: E402

ROOT = v6lib.ROOT
ACTS = ("D", "Fp", "Fm")
T, PAR2, RESERVE = v6lib.T, v6lib.PAR2, v6lib.RESERVE


def fnum(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load(argv):
    a = v6run.parser().parse_args(argv)
    out = {}
    for k, key, rid in v6run.plan(a):
        p = v6run.rec_path(k, rid)
        out[key["instance"]] = json.load(open(p)) if os.path.exists(p) else None
    return out


class Dev6:
    def __init__(self, hashes_file=None, rows=None):
        self.rows = rows or [r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "winner_profiles.csv")))]
        self.n = len(self.rows)
        self.h = [r["hash"] for r in self.rows]
        self.fam = [r["family_group"] for r in self.rows]
        self.group = [r["group"] for r in self.rows]
        f = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "configs", "observations_v5", "folds.csv")))}
        self.outer = np.array([int(f[h]["outer"]) for h in self.h])
        self.inner = {k: np.array([-1 if f[h][f"inner_{k}"] == "" else int(f[h][f"inner_{k}"]) for h in self.h])
                      for k in range(5)}
        self.c0 = np.array([[fnum(r[f"cost_{a}"]) for a in ACTS] for r in self.rows])
        self.solved = np.array([[r[f"status_{a}"] == "solved" for a in ACTS] for r in self.rows])
        dev = hashes_file or os.path.join(ROOT, "configs", "three_way", "dev_hashes.txt")
        o6 = load(["obs6", "--hashes", dev, "--flips", str(v6lib.LS_FLIPS), "--sections", "s28,resid,bilat,graph,ls"])
        sz = load(["sz", "--hashes", dev, "--groups", ",".join(v6lib.SZ_GROUPS), "--cap", "3"])
        self.obs6 = [o6.get(h) for h in self.h]
        self.sz = [sz.get(h) for h in self.h]
        self.missing = {"obs6": sum(x is None for x in self.obs6), "sz": sum(x is None for x in self.sz)}

    def formal_costs(self, o):
        C = np.full((self.n, 3), PAR2)
        for j in range(3):
            ok = self.solved[:, j] & (o + self.c0[:, j] <= T - RESERVE)
            C[ok, j] = o[ok] + self.c0[ok, j]
        return C

    def package(self, pkg):
        feats, o = [], np.zeros(self.n)
        forced = np.zeros(self.n, bool)
        for i in range(self.n):
            ob, sz = self.obs6[i], self.sz[i]
            if ob is None or (v6lib.PACKAGES[pkg]["sz"] and sz is None):
                raise RuntimeError(f"missing record {self.h[i]} for {pkg}")
            sc = v6lib.static_cpu(pkg, ob, sz)
            ok = v6lib.observation_ok(pkg, ob, sz) and sc <= v6lib.SCAP
            o[i] = min(sc, v6lib.SCAP) + v6lib.KAPPA
            if ok:
                feats.append(v6lib.features(pkg, ob, sz))
            else:
                forced[i] = True
                feats.append({})
        names = sorted({k for f in feats for k in f})
        X = np.array([[f[k] if f.get(k) is not None else np.nan for k in names] for f in feats], dtype=float)
        if not names:
            X = np.zeros((self.n, 0))
        C = self.formal_costs(o)
        answered = np.zeros(self.n, bool)
        return {"pkg": pkg, "names": names, "X": X, "C": C, "o": o, "consulted": ~forced, "answered": answered,
                "forced": forced}
