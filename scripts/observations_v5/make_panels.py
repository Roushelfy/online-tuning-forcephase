#!/usr/bin/env python3
"""Goal v5, V0/V1: fixed engineering panel and cross-validation folds on dev.

  python3 scripts/observations_v5/make_panels.py

Uses only the v4 manifest (year, family group, size stratum) -- never a
solver result. Writes
  configs/observations_v5/eng_panel.txt   96 dev instances (seed 20261023)
  configs/observations_v5/folds.csv       outer fold (= v4 S2 folds) and the
                                          inner 3-fold assignment per outer fold
"""

import collections
import csv
import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SEED = 20261023
V4_SEED = 20261022
N_ENG = 96
CFG = os.path.join(ROOT, "configs", "observations_v5")


def rkey(seed, *parts):
    return hashlib.sha256(":".join(map(str, (seed,) + parts)).encode()).hexdigest()


def balanced_folds(groups, k, seed, tag):
    """Family groups -> folds, largest first, ties by seeded key; fold with the
    smallest load (then index) receives the group. With seed 20261022 and
    tag 'fold' this is exactly twselect.folds (v4 S2)."""
    sizes = collections.Counter(groups)
    order = sorted(sizes, key=lambda g: (-sizes[g], rkey(seed, tag, g)))
    load, of = [0] * k, {}
    for g in order:
        j = min(range(k), key=lambda j: (load[j], j))
        of[g] = j
        load[j] += sizes[g]
    return of


def main():
    man = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "manifest.csv")))}
    dev = [l.split()[0] for l in open(os.path.join(ROOT, "configs", "three_way", "dev_hashes.txt"))
           if l.strip() and not l.startswith("#")]
    assert len(dev) == 401 and all(man[h]["split"] in ("train", "val") for h in dev)
    # rows in winner_profiles order (= dev_hashes order) so the outer folds match v4
    fam = [man[h]["family_group"] for h in dev]
    outer = balanced_folds(fam, 5, V4_SEED, "fold")
    rows = []
    for h, g in zip(dev, fam):
        rows.append({"hash": h, "family_group": g, "year": man[h]["quota_year"], "stratum": man[h]["stratum"],
                     "outer": outer[g]})
    for k in range(5):
        tr = [r for r in rows if r["outer"] != k]
        inner = balanced_folds([r["family_group"] for r in tr], 3, SEED, f"inner{k}")
        for r in rows:
            r[f"inner_{k}"] = "" if r["outer"] == k else inner[r["family_group"]]
    os.makedirs(CFG, exist_ok=True)
    with open(os.path.join(CFG, "folds.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # engineering panel: 96 of dev, proportional over (year x stratum) cells by
    # largest remainder; inside a cell one per family group first, then by rank
    cells = collections.defaultdict(list)
    for r in rows:
        cells[(r["year"], r["stratum"])].append(r)
    total = len(rows)
    quota = {c: N_ENG * len(v) / total for c, v in cells.items()}
    alloc = {c: int(q) for c, q in quota.items()}
    rest = N_ENG - sum(alloc.values())
    for c in sorted(quota, key=lambda c: (-(quota[c] - alloc[c]), rkey(SEED, "cell", *c)))[:rest]:
        alloc[c] += 1
    panel = []
    for c in sorted(cells):
        members = sorted(cells[c], key=lambda r: rkey(SEED, "eng", r["hash"]))
        seen, first, second = set(), [], []
        for r in members:
            (second if r["family_group"] in seen else first).append(r)
            seen.add(r["family_group"])
        panel += (first + second)[:alloc[c]]
    assert len(panel) == N_ENG
    with open(os.path.join(CFG, "eng_panel.txt"), "w") as f:
        f.write(f"# goal v5 engineering panel: {N_ENG} dev instances, seed {SEED}, (year x stratum) proportional,\n"
                "# one per family group per cell first; chosen from the manifest only (no solver result)\n")
        for r in sorted(panel, key=lambda r: r["hash"]):
            f.write(f"{r['hash']} {r['year']} {r['stratum']} {r['family_group']}\n")
    print("outer fold sizes", collections.Counter(r["outer"] for r in rows))
    print("eng panel by year", collections.Counter(r["year"] for r in panel), "families", len({r["family_group"] for r in panel}))


if __name__ == "__main__":
    main()
