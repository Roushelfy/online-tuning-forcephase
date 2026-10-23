#!/usr/bin/env python3
"""R0 of goal v6: fixed panels and the validation list (docs/STABLE_SELECTION_PROTOCOL_V6.md).

  python3 scripts/stable_selection_v6/make_panels.py

All panels use seed 20261023 and sha256-keyed orders, so the result does not
depend on iteration order. Inputs:
  diag30   v4 dev advantage labels (results/three_way/winner_profiles.csv,
           already exposed): 10 instances each of D-adv / F+-adv / F--adv,
           families spread (first one per family group, at most 3 per group),
           size strata and years covered where possible
  eng12    dev instances from the manifest only (year x stratum spread)
  check30  dev instances from the manifest only, for the real-wrapper check
  validate new-instance validation list (<= 60, ~12 per year): candidate pool
           minus the v4 panel, the v5 confirmation set and round-1 runs (hash,
           member hashes and isohash); per year 4 per size stratum (shortfalls
           moved to the other strata); inside a stratum family groups not used
           in dev first, then dev groups; <= 3 per family group
Writes configs/stable_selection_v6/{diag30.txt, eng12.txt, check30.txt,
validate_hashes.txt} and results/stable_selection_v6/validate_manifest.csv,
panels_summary.json.
"""

import collections
import csv
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "configs", "stable_selection_v6")
RES = os.path.join(ROOT, "results", "stable_selection_v6")
SEED = 20261023
YEARS = ["2022", "2023", "2024", "2025", "2026"]


def rkey(*parts):
    return hashlib.sha256(":".join(map(str, (SEED,) + parts)).encode()).hexdigest()


def spread_pick(cands, k, tag, per_family=3):
    """Rank order; first pass one per family group cycling over size strata,
    second pass fill by rank with at most per_family per group."""
    cands = sorted(cands, key=lambda r: rkey(tag, r["hash"]))
    chosen, fams = [], collections.Counter()
    strata = ["small", "mid", "large"]
    s = 0
    progress = True
    while len(chosen) < k and progress:
        progress = False
        for _ in range(3):
            st = strata[s % 3]
            s += 1
            for r in cands:
                if r in chosen or fams[r["family_group"]] or r["stratum"] != st:
                    continue
                chosen.append(r)
                fams[r["family_group"]] += 1
                progress = True
                break
            if len(chosen) >= k:
                break
    for r in cands:
        if len(chosen) >= k:
            break
        if r not in chosen and fams[r["family_group"]] < per_family:
            chosen.append(r)
            fams[r["family_group"]] += 1
    return chosen


def write_list(path, rows, header, cols):
    with open(path, "w") as f:
        f.write(header)
        for r in sorted(rows, key=lambda r: r["hash"]):
            f.write(" ".join(str(r[c]) for c in cols) + "\n")


def main():
    os.makedirs(CFG, exist_ok=True)
    os.makedirs(RES, exist_ok=True)
    man = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "manifest.csv")))}
    wp = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "winner_profiles.csv")))}
    dev = [dict(man[h], group=wp[h]["group"]) for h in wp]
    summ = {}
    # ---- diag30 (labels are v4 results, already exposed)
    diag = []
    for g in ("D-adv", "Fp-adv", "Fm-adv"):
        pick = spread_pick([r for r in dev if r["group"] == g], 10, f"diag:{g}")
        diag += pick
        summ[f"diag_{g}"] = {"n": len(pick), "families": len({r['family_group'] for r in pick}),
                             "strata": collections.Counter(r["stratum"] for r in pick),
                             "years": collections.Counter(r["quota_year"] for r in pick)}
    write_list(os.path.join(CFG, "diag30.txt"), diag,
               f"# goal v6 R1 diagnostic panel: 10 per v4 advantage group (D/F+/F-), seed {SEED}; uses the exposed v4 dev labels\n"
               "# columns: hash v4-group year stratum family_group\n", ["hash", "group", "quota_year", "stratum", "family_group"])
    # ---- eng12 and check30: manifest only (no solver result), disjoint from each other
    def by_cells(rows, k, tag, exclude=()):
        rows = [r for r in rows if r["hash"] not in exclude]
        cells = collections.defaultdict(list)
        for r in rows:
            cells[(r["quota_year"], r["stratum"])].append(r)
        order = sorted(cells, key=lambda c: rkey(tag, "cell", *c))
        for c in cells:
            cells[c].sort(key=lambda r: rkey(tag, r["hash"]))
        out, i = [], 0
        while len(out) < k:
            c = order[i % len(order)]
            idx = i // len(order)
            if idx < len(cells[c]) and all(r["family_group"] != cells[c][idx]["family_group"] for r in out):
                out.append(cells[c][idx])
            i += 1
            if i > 100000:
                break
        return out
    eng = by_cells(dev, 12, "eng12")
    chk = by_cells(dev, 30, "check30", exclude={r["hash"] for r in eng})
    write_list(os.path.join(CFG, "eng12.txt"), eng, f"# goal v6 engineering panel (12 dev, manifest only, seed {SEED})\n# hash year stratum family_group\n",
               ["hash", "quota_year", "stratum", "family_group"])
    write_list(os.path.join(CFG, "check30.txt"), chk, f"# goal v6 real-wrapper check panel (30 dev, manifest only, seed {SEED})\n# hash year stratum family_group\n",
               ["hash", "quota_year", "stratum", "family_group"])
    summ["eng12"] = {"strata": collections.Counter(r["stratum"] for r in eng), "years": collections.Counter(r["quota_year"] for r in eng)}
    summ["check30"] = {"strata": collections.Counter(r["stratum"] for r in chk), "years": collections.Counter(r["quota_year"] for r in chk)}
    # ---- validation list (metadata only)
    cand = list(csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "candidates.csv"))))
    conf = {l.split()[0] for l in open(os.path.join(ROOT, "configs", "observations_v5", "confirm_hashes.txt"))
            if l.strip() and not l.startswith("#")}
    r1 = {r["hash"]: r for r in csv.DictReader(open(os.path.join(ROOT, "benchmarks", "manifest.csv")))
          if r["split"] in ("train", "val", "test", "t2026")}
    dev_groups = {r["family_group"] for r in dev}
    used = set(man) | set(r1) | conf
    for r in list(man.values()) + [c for c in cand if c["hash"] in conf]:
        used |= set(filter(None, r["members"].split("+")))
    used_iso = {r["isohash"] for r in man.values()} | {r["isohash"] for r in r1.values() if r.get("isohash")} | \
        {c["isohash"] for c in cand if c["hash"] in conf}
    pool = [r for r in cand if r["hash"] not in used and r["prior_exposure"] == "none" and r["eligible"] == "1"
            and not (set(filter(None, r["members"].split("+"))) & used) and r["isohash"] not in used_iso]
    val = []
    for y in YEARS:
        py = [r for r in pool if r["quota_year"] == y]
        # size strata first (4 each; a stratum's shortfall goes to the others), inside a stratum
        # family groups not used in dev first (one per group), then dev groups (one per group),
        # then by rank with <= 3 per group
        avail = {st: [r for r in py if r["stratum"] == st] for st in ("small", "mid", "large")}
        quota = {st: 4 for st in avail}
        short = sum(max(0, 4 - len(v)) for v in avail.values())
        for st in sorted(avail, key=lambda st: -len(avail[st])):
            extra = min(short, max(0, len(avail[st]) - quota[st]))
            quota[st] += extra
            short -= extra
        chosen, fams = [], collections.Counter()
        for st in ("small", "mid", "large"):
            ranked = sorted(avail[st], key=lambda r: rkey("val", y, st, r["hash"]))
            got = 0
            for passno in range(3):
                for r in ranked:
                    if got >= quota[st] or r in chosen:
                        continue
                    nd = r["family_group"] not in dev_groups
                    if passno == 0 and not (nd and fams[r["family_group"]] == 0):
                        continue
                    if passno == 1 and fams[r["family_group"]] > 0:
                        continue
                    if passno == 2 and fams[r["family_group"]] >= 3:
                        continue
                    chosen.append(r)
                    fams[r["family_group"]] += 1
                    got += 1
        val += chosen
        nd = sum(r["family_group"] not in dev_groups for r in chosen)
        summ[f"validate_{y}"] = {"n": len(chosen), "non_dev_family": nd, "dev_family": len(chosen) - nd,
                                 "strata": collections.Counter(r["stratum"] for r in chosen),
                                 "pool_non_dev": sum(r["family_group"] not in dev_groups for r in py),
                                 "pool_dev": sum(r["family_group"] in dev_groups for r in py)}
    for r in val:
        r["family_in_dev"] = int(r["family_group"] in dev_groups)
    write_list(os.path.join(CFG, "validate_hashes.txt"), val,
               f"# goal v6 R4 validation list ({len(val)} problems, metadata only, seed {SEED}); never run before; "
               "family_in_dev = 1 marks family groups used in v6 development\n# hash year stratum family_group family_in_dev\n",
               ["hash", "quota_year", "stratum", "family_group", "family_in_dev"])
    fields = list(man[next(iter(man))].keys())
    with open(os.path.join(RES, "validate_manifest.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields + ["family_in_dev"])
        w.writeheader()
        for r in sorted(val, key=lambda r: r["hash"]):
            row = {k: r.get(k, "") for k in fields}
            row["split"], row["selected"], row["family_in_dev"] = "validate", "1", r["family_in_dev"]
            w.writerow(row)
    summ["validate"] = {"n": len(val), "groups": len({r["family_group"] for r in val}),
                        "non_dev_family": sum(1 - r["family_in_dev"] for r in val),
                        "strata": collections.Counter(r["stratum"] for r in val), "pool": len(pool),
                        "never_seen_family_groups": sum(r["family_group"] not in dev_groups and r["family_group"] not in
                                                        {m["family_group"] for m in man.values()} for r in val)}
    json.dump(summ, open(os.path.join(RES, "panels_summary.json"), "w"), indent=1, default=dict)
    print(json.dumps(summ, indent=1, default=dict))


if __name__ == "__main__":
    main()
