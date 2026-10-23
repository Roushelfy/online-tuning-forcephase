"""Data assembly for the goal-v5 analyses (dev only unless stated).

Loads the v4 per-instance table (fixed-action costs, groups, v4 features),
the v5 obsprofile and arm records, the wrapper overhead measurements, and
builds per package: the feature table and the simulated wrapper cost
matrix of protocol section 5.
"""

import collections
import csv
import glob
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
import obsrun  # noqa: E402
import twlib  # noqa: E402
import v5lib  # noqa: E402

ROOT = v5lib.ROOT
T, PAR2, RESERVE = v5lib.T, v5lib.PAR2, v5lib.RESERVE
ACTS = ("D", "Fp", "Fm")
LBL = {"D": "D", "Fp": "F+", "Fm": "F−"}
KAPPA_V4 = 0.08
PKGS = ["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10", "R11"]


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def load_records(kind, hashes_file, variants="orig", **kw):
    a = Args(cmd=kind, hashes=hashes_file, variants=variants, tags=kw.get("tags", "e02,e05,ec,fD"),
             actions=kw.get("actions", "D,Fp,Fm"), strategy=kw.get("strategy"), observe_only=kw.get("observe_only", False),
             conflicts=kw.get("conflicts", 20000))
    out = {}
    for k, key, rid in obsrun.plan(a):
        p = obsrun.rec_path(k, rid)
        out[(key["instance"], key["variant"], key.get("tag"), key.get("action"), key.get("strategy"))] = \
            json.load(open(p)) if os.path.exists(p) else None
    return out


def dev_rows():
    return [r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "winner_profiles.csv")))]


def folds():
    return {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "configs", "observations_v5", "folds.csv")))}


def kappas(eng_file=None):
    """kappa_P = median over the engineering panel of (wrapper tree CPU -
    obsprofile CPU - arm CPU) for observe-only wrapper runs (protocol s. 5)."""
    eng_file = eng_file or os.path.join(ROOT, "configs", "observations_v5", "eng_panel.txt")
    strat = ",".join(os.path.join(ROOT, "configs", "observations_v5", "kappa", f"{p}.json") for p in PKGS)
    recs = load_records("wrap", eng_file, strategy=strat, observe_only=True)
    by = collections.defaultdict(list)
    for (h, v, t, a, s), r in recs.items():
        if r and r.get("result"):
            res = r["result"]
            comp = res["obsprofile"]["cpu"] + sum(x["cpu"] for x in res.get("arms", []))
            by[res["package"]].append(r["total_cpu"] - comp)
    return {p: float(np.median(v)) for p, v in by.items() if v}, {p: v for p, v in by.items()}


class Dev:
    """Dev panel with fixed-action costs, obs/arm records and per-package
    feature tables and cost matrices."""

    def __init__(self, kappa=None):
        self.rows = dev_rows()
        self.n = len(self.rows)
        self.h = [r["hash"] for r in self.rows]
        self.fam = [r["family_group"] for r in self.rows]
        f = folds()
        self.outer = np.array([int(f[h]["outer"]) for h in self.h])
        self.inner = {k: np.array([-1 if f[h][f"inner_{k}"] == "" else int(f[h][f"inner_{k}"]) for h in self.h])
                      for k in range(5)}
        self.c0 = np.array([[fnum(r[f"cost_{a}"]) for a in ACTS] for r in self.rows])  # fixed runs, no observation
        self.solved = np.array([[r[f"status_{a}"] == "solved" for a in ACTS] for r in self.rows])
        self.group = [r["group"] for r in self.rows]
        dev_file = os.path.join(ROOT, "configs", "three_way", "dev_hashes.txt")
        obs = load_records("obs", dev_file)
        self.obs = [obs.get((h, "orig", None, None, None)) for h in self.h]
        arms = load_records("arm", dev_file, tags="e02,e05,ec")
        arms.update(load_records("arm", dev_file, tags="fD", actions="D"))
        self.arms = [{(t, a): r for (h2, v, t, a, s), r in arms.items() if h2 == h and r is not None} for h in self.h]
        self.missing_obs = sum(o is None for o in self.obs)
        self.missing_arms = sum(r is None for r in arms.values())
        self.kappa = kappa if kappa is not None else kappas()[0]

    # ------------------------------------------------------------ costs
    def formal_costs(self, o):
        """Cost matrix when the observation used o CPU seconds (no answer)."""
        C = np.full((self.n, 3), PAR2)
        for j in range(3):
            ok = self.solved[:, j] & (o + self.c0[:, j] <= T - RESERVE)
            C[ok, j] = o[ok] + self.c0[ok, j]
        return C

    def arm_cost(self, i, spec_arms):
        """(CPU of the arms actually run, answered?) in the fixed order;
        stops at the first verified answer. Missing record -> None."""
        cpu = 0.0
        for tag, acts in spec_arms:
            for a in acts:
                r = self.arms[i].get((tag, a))
                if r is None:
                    return None, False
                cpu += r["cpu"]
                if r.get("answered"):
                    if r.get("solved"):
                        return cpu, True
                    raise RuntimeError(f"unverified/wrong probe answer {self.h[i]} {tag} {a}")
        return cpu, False

    def package(self, pkg, stage=None):
        """Feature table, cost matrix and flags for a package.
        Returns dict(names, X, C, o, consulted, answered, forced)."""
        spec = v5lib.PACKAGES[pkg]
        static = spec["static"]
        use_arms = spec["arms"] if (pkg != "R11" or stage == 2) else []
        kap = self.kappa.get(pkg, self.kappa.get("R10") if pkg == "R11" else None)
        if pkg == "R11" and stage == 1:
            kap = self.kappa.get("R01")  # static-only wrapper overhead (R11 stage 1 alone)
        feats, o, answered, forced = [], np.zeros(self.n), np.zeros(self.n, bool), np.zeros(self.n, bool)
        for i in range(self.n):
            ob = self.obs[i]
            if ob is None:
                raise RuntimeError(f"missing obs record {self.h[i]}")
            sc = v5lib.static_cost(ob, static)
            ok = v5lib.static_ok(ob, static) and sc <= spec["scap"]
            o_i = min(sc, spec["scap"]) + kap
            if not ok:
                forced[i] = True
                feats.append({})
            else:
                acpu, ans = self.arm_cost(i, use_arms) if use_arms else (0.0, False)
                if acpu is None:
                    raise RuntimeError(f"missing arm record {self.h[i]}")
                o_i += acpu
                answered[i] = ans
                feats.append(obsfeat.package_features(pkg, ob, self.arms[i], stage=stage))
            o[i] = o_i
        names = sorted({k for f in feats for k in f})
        X = np.array([[fnum(f.get(k)) if f.get(k) is not None else np.nan for k in names] for f in feats], dtype=float)
        C = self.formal_costs(o)
        C[answered, :] = o[answered, None]
        consulted = ~(forced | answered)
        return {"pkg": pkg, "names": names, "X": X, "C": C, "o": o, "consulted": consulted,
                "answered": answered, "forced": forced}

    def s28_package(self):
        """Control: S28 only (obsprofile parse + s28), static-only overhead."""
        names = list(obsfeat.S28)
        X = np.array([[fnum(obsfeat.s28(ob).get(k)) if obsfeat.s28(ob).get(k) is not None else np.nan for k in names]
                      for ob in self.obs], dtype=float)
        o = np.array([v5lib.static_cost(ob, []) for ob in self.obs]) + self.kappa.get("R01", KAPPA_V4)
        C = self.formal_costs(o)
        z = np.zeros(self.n, bool)
        return {"pkg": "S28", "names": names, "X": X, "C": C, "o": o, "consulted": ~z, "answered": z, "forced": z}

    def v4_package(self, budget):
        """R00 / v4 static: v4 inputs and v4 costs (twselect.Data.sim_costs)."""
        import twselect as TS
        D = TS.Data(self.rows, KAPPA_V4)
        names, X = D.features(budget)
        C, o, ps = D.sim_costs(budget)
        z = np.zeros(self.n, bool)
        return {"pkg": "R00" if budget else "v4static", "names": names, "X": X, "C": C, "o": o,
                "consulted": ~ps, "answered": ps, "forced": z}
