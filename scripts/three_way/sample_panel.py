#!/usr/bin/env python3
"""Five-year representative panel (SAT Competition main tracks 2022-2026).

  scripts/three_way/sample_panel.py --gbd $FP_DATA/benchmarks/gbd \
      --official $FP_DATA/benchmarks/official --out results/three_way

Implements docs/FIVE_YEAR_SAMPLE_PLAN.md with the parameters frozen in
docs/THREE_WAY_PROTOCOL.md section 2. Uses metadata only (GBD meta/base
databases, the official yearly lists, the round-1 manifest for prior
exposure); no solver result of any configuration is read.

Steps
  1. pool: union of main_2022..main_2026 (GBD track tags), each year checked
     against the official list (must be identical, else abort);
  2. problems: hashes with the same GBD isohash are one problem; its
     representative is the member that round 1 ran (if any), else the member
     of the earliest year (ties: smallest hash); quota year = earliest year;
  3. family group: round-1 alias map + 'unknown' by author, then union-find
     over isohash classes (as scripts/build_manifest.py, now over 2022-2026);
  4. eligibility: GBD 'bytes' (uncompressed sanitized CNF) <= MAX_BYTES;
  5. size stratum per quota year: tertiles of log10(clauses) over that
     year's eligible problems (small / mid / large);
  6. quotas per year: one per family group, the rest by sqrt(group size)
     (largest remainder, seeded tie-break), at most CAP per group and never
     more than the group has; if a year has more groups than its quota,
     groups are covered in seeded random order;
  7. inside a group: one per present stratum (strata in seeded order), then
     the remaining candidates in seeded rank order; all unselected
     candidates keep their rank as pre-ordered replacements;
  8. split: family groups -> test first (prefer groups whose panel instances
     round 1 never ran), then train/val (60/20) by seeded largest deficit.
Outputs: candidates.csv (every problem), manifest.csv (panel), hashes per
split (configs/three_way/*.txt), sampling_summary.json; prints SHA-256.
"""

import argparse
import collections
import csv
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from build_manifest import ALIASES, UF  # noqa: E402  (round-1 alias map, unchanged)

YEARS = (2022, 2023, 2024, 2025, 2026)
QUOTA = 100           # problems per quota year
CAP = 10              # at most 10% of a year's quota per family group
MAX_BYTES = 1e9       # resource rule (protocol section 2.3)
SEED = 20261022
FRACTIONS = {"train": 0.6, "val": 0.2, "test": 0.2}
OLD_RUN_SPLITS = {"train", "val", "test", "t2026"}  # round-1 splits that were run
STRATA = ("small", "mid", "large")


def rkey(*parts):
    """Deterministic pseudo-random key (independent of iteration order)."""
    return hashlib.sha256(":".join(map(str, (SEED,) + parts)).encode()).hexdigest()


def official_hashes(official_dir, year):
    name = "track_main_2026.uri" if year == 2026 else f"gbd_getinstances_main_{year}.txt"
    path = os.path.join(official_dir, name)
    return set(re.findall(r"file/([0-9a-f]{32})", open(path).read())), path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def allocate(groups, quota, cap):
    """groups: {g: n_candidates}. Returns ({g: q}, uncovered_groups)."""
    order = sorted(groups, key=lambda g: rkey("famorder", g))
    if len(order) > quota:
        q = {g: 1 for g in order[:quota]}
        return q, order[quota:]
    q = {g: 1 for g in order}
    rest = quota - len(order)
    while rest > 0:
        open_ = [g for g in order if q[g] < min(cap, groups[g])]
        if not open_:
            break
        w = {g: math.sqrt(groups[g]) for g in open_}
        tot = sum(w.values())
        share = {g: rest * w[g] / tot for g in open_}
        add = {g: min(int(share[g]), min(cap, groups[g]) - q[g]) for g in open_}
        given = sum(add.values())
        if given == 0:  # hand out single units by largest remainder
            for g in sorted(open_, key=lambda g: (-(share[g] - int(share[g])), rkey("tie", g))):
                if rest == 0:
                    break
                q[g] += 1
                rest -= 1
            continue
        for g in open_:
            q[g] += add[g]
        rest -= given
    return q, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbd", required=True)
    ap.add_argument("--official", required=True)
    ap.add_argument("--old-manifest", default=os.path.join(ROOT, "benchmarks", "manifest.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "three_way"))
    ap.add_argument("--lists", default=os.path.join(ROOT, "configs", "three_way"))
    a = ap.parse_args()
    meta = sqlite3.connect(os.path.join(a.gbd, "meta.db"))
    base = sqlite3.connect(os.path.join(a.gbd, "base.db"))

    # 1. pool and official-list check
    years = collections.defaultdict(set)
    official = {}
    for y in YEARS:
        snap = {h for (h,) in meta.execute("select hash from track where value=?", (f"main_{y}",))}
        off, path = official_hashes(a.official, y)
        if off != snap:
            raise SystemExit(f"main_{y}: GBD snapshot differs from official list {path}")
        official[y] = {"file": os.path.basename(path), "sha256": sha256_file(path), "n": len(off)}
        for h in snap:
            years[h].add(y)
    info = {r[0]: r for r in meta.execute("select hash, filename, isohash, family, author, result from features")}
    size = {r[0]: r[1:] for r in base.execute("select hash, variables, clauses, bytes from features")}
    old = {r["hash"]: r for r in csv.DictReader(open(a.old_manifest))}
    old_ran = {h for h, r in old.items() if r["split"] in OLD_RUN_SPLITS}

    # 2. problems = isohash classes
    by_iso = collections.defaultdict(list)
    for h in years:
        by_iso[info[h][2]].append(h)
    problems = []
    for iso, hs in by_iso.items():
        ran = sorted(h for h in hs if h in old_ran)
        rep = ran[0] if ran else min(hs, key=lambda h: (min(years[h]), h))
        problems.append({"rep": rep, "members": sorted(hs), "isohash": iso,
                         "years": sorted(set().union(*(years[h] for h in hs)))})

    # 3. family groups (alias map, unknown by author, union over isohash)
    uf = UF()
    raw = {}
    for h in years:
        fam = info[h][3]
        g = f"unknown-author-{info[h][4]}" if fam == "unknown" else ALIASES.get(fam, fam)
        raw[h] = g
        uf.find(g)
    for p in problems:
        for h in p["members"][1:]:
            uf.union(raw[p["members"][0]], raw[h])
    for p in problems:
        p["group"] = uf.find(raw[p["rep"]])
        p["family"] = info[p["rep"]][3]

    # prior exposure (instance: any member ran in round 1; group: any ran member)
    group_exposed = collections.defaultdict(bool)
    for p in problems:
        ran = [h for h in p["members"] if h in old_ran]
        p["prior_exposure"] = "+".join(sorted({old[h]["split"] for h in ran})) if ran else "none"
        if ran:
            group_exposed[p["group"]] = True
    for p in problems:
        p["family_prior_exposure"] = "exposed" if group_exposed[p["group"]] else "none"

    # 4./5. eligibility and strata per quota year
    for p in problems:
        v, c, b = size[p["rep"]]
        p.update(variables=v, clauses=c, bytes=b, quota_year=p["years"][0])
        bb = num(b)
        p["eligible"] = bb is not None and bb <= MAX_BYTES
        p["exclusion"] = "" if p["eligible"] else ("bytes>1e9" if bb is not None else "bytes unknown")
    bounds = {}
    for y in YEARS:
        xs = sorted(math.log10(1 + num(p["clauses"])) for p in problems if p["quota_year"] == y and p["eligible"])
        q1 = xs[int(len(xs) / 3)]
        q2 = xs[int(2 * len(xs) / 3)]
        bounds[y] = (q1, q2)
        for p in problems:
            if p["quota_year"] == y:
                x = math.log10(1 + num(p["clauses"]))
                p["log10_clauses"] = round(x, 4)
                p["stratum"] = "small" if x < q1 else ("mid" if x < q2 else "large")

    # 6./7. quotas and within-group selection
    summary = {"seed": SEED, "quota": QUOTA, "cap": CAP, "max_bytes": MAX_BYTES, "official_lists": official,
               "strata_bounds_log10_clauses": {y: bounds[y] for y in YEARS}, "years": {}}
    for p in problems:
        p.update(selected=False, rank=None, replacement_rank=None)
    for y in YEARS:
        cand = [p for p in problems if p["quota_year"] == y and p["eligible"]]
        groups = collections.Counter(p["group"] for p in cand)
        q, uncovered = allocate(groups, QUOTA, CAP)
        for g, k in q.items():
            mem = [p for p in cand if p["group"] == g]
            for p in mem:
                p["rank"] = rkey("inst", p["rep"])
            mem.sort(key=lambda p: p["rank"])
            present = sorted({p["stratum"] for p in mem}, key=lambda s: rkey("stratum", y, g, s))
            picked = []
            for s in present:
                if len(picked) < k:
                    picked.append(next(p for p in mem if p["stratum"] == s))
            for p in mem:
                if len(picked) >= k:
                    break
                if p not in picked:
                    picked.append(p)
            for p in picked:
                p["selected"] = True
            # replacement order: remaining members by rank (same stratum first at use time)
            for i, p in enumerate(x for x in mem if not x["selected"]):
                p["replacement_rank"] = i + 1
        summary["years"][y] = {
            "problems": sum(p["quota_year"] == y for p in problems),
            "eligible": len(cand), "excluded_bytes": sum(p["quota_year"] == y and not p["eligible"] for p in problems),
            "groups": len(groups), "selected": sum(q.values()), "uncovered_groups": uncovered,
            "groups_at_cap": sorted(g for g in q if q[g] == CAP),
            "unused_quota": QUOTA - sum(q.values())}

    # 8. split by family group
    panel = [p for p in problems if p["selected"]]
    n_g = collections.Counter(p["group"] for p in panel)
    u_g = collections.Counter(p["group"] for p in panel if p["prior_exposure"] == "none")
    total = len(panel)
    target = {s: FRACTIONS[s] * total for s in FRACTIONS}
    split_of = {}
    # test: groups ordered by unexposed share (family-unexposed first), seeded tie-break;
    # add while the test split stays within its target
    order = sorted(n_g, key=lambda g: (group_exposed[g], -u_g[g] / n_g[g], rkey("split", g)))
    have = 0
    for g in order:
        if u_g[g] == 0:
            break  # never put a group with no unexposed panel instance into test
        if have + n_g[g] <= target["test"]:
            split_of[g] = "test"
            have += n_g[g]
    summary["test_target"] = target["test"]
    rest = [g for g in n_g if g not in split_of]
    rest.sort(key=lambda g: (-n_g[g], rkey("dev", g)))
    tv = {"train": 0, "val": 0}
    tv_target = {"train": 0.75 * (total - have), "val": 0.25 * (total - have)}
    for g in rest:
        s = max(tv, key=lambda s: (tv_target[s] - tv[s]) / tv_target[s])
        split_of[g] = s
        tv[s] += n_g[g]
    for p in problems:
        p["split"] = split_of.get(p["group"], "") if p["selected"] else ""

    # outputs
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.lists, exist_ok=True)
    fields = ["hash", "isohash", "members", "years", "quota_year", "family", "family_group", "variables",
              "clauses", "bytes", "log10_clauses", "stratum", "eligible", "exclusion", "prior_exposure",
              "family_prior_exposure", "selected", "replacement_rank", "split", "gbd_result", "url"]

    def row(p):
        return {"hash": p["rep"], "isohash": p["isohash"], "members": "+".join(p["members"]),
                "years": "+".join(map(str, p["years"])), "quota_year": p["quota_year"], "family": p["family"],
                "family_group": p["group"], "variables": p["variables"], "clauses": p["clauses"],
                "bytes": p["bytes"], "log10_clauses": p["log10_clauses"], "stratum": p["stratum"],
                "eligible": int(p["eligible"]), "exclusion": p["exclusion"], "prior_exposure": p["prior_exposure"],
                "family_prior_exposure": p["family_prior_exposure"], "selected": int(p["selected"]),
                "replacement_rank": p["replacement_rank"] or "", "split": p["split"],
                "gbd_result": info[p["rep"]][5], "url": f"https://benchmark-database.de/file/{p['rep']}"}

    problems.sort(key=lambda p: (p["quota_year"], p["group"], p["rep"]))
    with open(os.path.join(a.out, "candidates.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(row(p) for p in problems)
    with open(os.path.join(a.out, "manifest.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(row(p) for p in problems if p["selected"])
    for s, members in (("train", {"train"}), ("val", {"val"}), ("test", {"test"}), ("dev", {"train", "val"})):
        with open(os.path.join(a.lists, f"{s}_hashes.txt"), "w") as f:
            f.write(f"# three-way panel, split {s} (generated by scripts/three_way/sample_panel.py)\n")
            for p in sorted(panel, key=lambda p: p["rep"]):
                if p["split"] in members:
                    f.write(p["rep"] + "\n")
    cnt = collections.Counter(p["split"] for p in panel)
    summary.update({
        "problems": len(problems), "panel": total, "split_instances": dict(cnt),
        "split_groups": dict(collections.Counter(split_of.values())),
        "split_unexposed_instances": dict(collections.Counter(p["split"] for p in panel if p["prior_exposure"] == "none")),
        "gbd": {n: sha256_file(os.path.join(a.gbd, n)) for n in ("meta.db", "base.db")},
        "manifest_sha256": sha256_file(os.path.join(a.out, "manifest.csv")),
        "candidates_sha256": sha256_file(os.path.join(a.out, "candidates.csv"))})
    json.dump(summary, open(os.path.join(a.out, "sampling_summary.json"), "w"), indent=1, default=str)
    print(json.dumps({k: summary[k] for k in ("problems", "panel", "split_instances", "split_groups",
                                              "split_unexposed_instances", "manifest_sha256")}, indent=1))
    for y in YEARS:
        print(y, summary["years"][y])


if __name__ == "__main__":
    main()
