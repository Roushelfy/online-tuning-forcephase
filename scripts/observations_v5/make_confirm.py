#!/usr/bin/env python3
"""V3 confirmation set of goal v5 (protocol section 2, rule fixed before V2).

  python3 scripts/observations_v5/make_confirm.py

Pool (results/three_way/candidates.csv, 2022-2026 main track, one
representative per isohash): family group among the 31 groups of the v4
test split (so disjoint from dev), not in the v4 500-panel, never run in
round 1 (prior_exposure = none), eligible (<= 1 GB). At most 4 per family
group: first one per (quota year, size stratum) cell in seeded order, then
by rank sha256(20261023:conf:hash). Checks hash / isohash / member hashes
against the v4 panel and the round-1 runs (benchmarks/manifest.csv, run splits) and family
disjointness from dev. Uses metadata only (no solver result).

Writes configs/observations_v5/confirm_hashes.txt,
results/observations_v5/confirm_manifest.csv (fetch_benchmarks.py format,
split = confirm) and results/observations_v5/confirm_summary.json.
"""

import collections
import csv
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = 20261023
PER_GROUP = 4


def rkey(*parts):
    return hashlib.sha256(":".join(map(str, (SEED,) + parts)).encode()).hexdigest()


def main():
    cand = list(csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "candidates.csv"))))
    man = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "manifest.csv")))}
    # round 1: only instances that were actually run (the 'excluded' rows were listed but never run),
    # the same definition as scripts/three_way/sample_panel.py (OLD_RUN_SPLITS)
    r1 = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "benchmarks", "manifest.csv")))
          if r["split"] in ("train", "val", "test", "t2026")}
    dev_groups = {r["family_group"] for r in man.values() if r["split"] in ("train", "val")}
    test_groups = {r["family_group"] for r in man.values() if r["split"] == "test"}
    used_hashes = set(man) | set(r1)
    for r in man.values():
        used_hashes |= set(filter(None, r["members"].split("+")))
    used_iso = {r["isohash"] for r in man.values()} | {r["isohash"] for r in r1.values() if r.get("isohash")}
    pool = [r for r in cand if r["hash"] not in man and r["family_group"] in test_groups
            and r["prior_exposure"] == "none" and r["eligible"] == "1"]
    by = collections.defaultdict(list)
    for r in pool:
        by[r["family_group"]].append(r)
    chosen = []
    for g in sorted(by):
        members = sorted(by[g], key=lambda r: rkey("conf", r["hash"]))
        cells = sorted({(r["quota_year"], r["stratum"]) for r in members}, key=lambda c: rkey("cell", g, *c))
        first, seen = [], set()
        for c in cells:
            for r in members:
                if (r["quota_year"], r["stratum"]) == c and r["hash"] not in seen:
                    first.append(r)
                    seen.add(r["hash"])
                    break
        rest = [r for r in members if r["hash"] not in seen]
        chosen += (first + rest)[:PER_GROUP]
    # checks
    problems = []
    for r in chosen:
        mem = set(filter(None, r["members"].split("+"))) | {r["hash"]}
        if mem & used_hashes:
            problems.append((r["hash"], "hash/member already used"))
        if r["isohash"] in used_iso:
            problems.append((r["hash"], "isohash already used"))
        if r["family_group"] in dev_groups:
            problems.append((r["hash"], "family group in dev"))
    assert not problems, problems
    chosen.sort(key=lambda r: r["hash"])
    os.makedirs(os.path.join(ROOT, "configs", "observations_v5"), exist_ok=True)
    with open(os.path.join(ROOT, "configs", "observations_v5", "confirm_hashes.txt"), "w") as f:
        f.write(f"# goal v5 confirmation set ({len(chosen)} problems): v4-test family groups, not in the v4 panel, never run in round 1,\n"
                f"# <= {PER_GROUP} per family group, seed {SEED}; metadata only (scripts/observations_v5/make_confirm.py)\n")
        for r in chosen:
            f.write(f"{r['hash']} {r['quota_year']} {r['stratum']} {r['family_group']}\n")
    fields = list(man[next(iter(man))].keys())
    with open(os.path.join(ROOT, "results", "observations_v5", "confirm_manifest.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in chosen:
            row = {k: r.get(k, "") for k in fields}
            row["split"] = "confirm"
            row["selected"] = "1"
            w.writerow(row)
    summ = {"n": len(chosen), "pool": len(pool), "pool_groups": len(by), "groups": len({r["family_group"] for r in chosen}),
            "by_year": collections.Counter(r["quota_year"] for r in chosen), "by_stratum": collections.Counter(r["stratum"] for r in chosen),
            "by_group": collections.Counter(r["family_group"] for r in chosen),
            "bytes_over_1e8": sum(float(r["bytes"]) > 1e8 for r in chosen),
            "never_seen_family_groups": 0,
            "note": "all 2022-2026 main-track family groups occur in the v4 panel; these groups were in the v4 test split "
                    "(their other instances' v4 test results have been seen) and are disjoint from dev"}
    json.dump(summ, open(os.path.join(ROOT, "results", "observations_v5", "confirm_summary.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
