#!/usr/bin/env python3
"""Goal v11 public instances (docs/BROAD_SCOPE_PROTOCOL_V11.md section 5; rule configs/broad_scope_v11/public_rule.json).

  python3 scripts/broad_scope_v11/public.py audit            -> results/broad_scope_v11/public_pools.json
  python3 scripts/broad_scope_v11/public.py pilot            -> results/broad_scope_v11/public_pilot.json
  python3 scripts/broad_scope_v11/public.py select [--pilot-stage STAGE]
                                                            -> results/broad_scope_v11/public_selection.json
  python3 scripts/broad_scope_v11/public.py fetch --which pilot|formal   (download, decompress, hash checks)

Metadata: the GBD snapshot $FP_DATA/benchmarks/gbd/{meta,base}.db (tracks, family, isohash, bytes). Exposure: every
GBD hash run in v1-v10 (the local download directory, benchmarks/checksums.csv, the three-way selection, v5 confirm,
old 55) and every hash sharing a GBD isohash with one of them. Selection is by source, size tercile and a fixed hash
order; nothing about D / F+ / F- outcomes is used. Standard library only (fetch calls xz).
"""
import argparse
import collections
import csv
import glob
import hashlib
import json
import lzma
import os
import re
import sqlite3
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
BENCH = os.path.join(DATA, "benchmarks")
EXT = os.path.join(DATA, "broad_scope_v11", "public")
CFG = os.path.join(ROOT, "configs", "broad_scope_v11")
RES = os.path.join(ROOT, "results", "broad_scope_v11")
RULE = json.load(open(os.path.join(CFG, "public_rule.json")))


def key(h):
    return hashlib.sha256((RULE["order_salt"] + h).encode()).hexdigest()


def load_meta():
    m = sqlite3.connect(os.path.join(BENCH, "gbd", "meta.db"))
    b = sqlite3.connect(os.path.join(BENCH, "gbd", "base.db"))
    tracks = collections.defaultdict(set)
    for h, v in m.execute("select hash, value from track"):
        tracks[h].add(v)
    feat = {h: {"family": f, "isohash": iso, "result": res, "author": au}
            for h, f, iso, res, au in m.execute("select hash, family, isohash, result, author from features")}
    size = {}
    for h, by, c, v in b.execute("select hash, bytes, clauses, variables from features"):
        try:
            size[h] = (int(float(by)), int(float(c)), int(float(v)))
        except (TypeError, ValueError):
            pass
    return tracks, feat, size


def exposed(feat):
    run = {os.path.basename(p)[:-7] for p in glob.glob(os.path.join(BENCH, "cnf", "*.cnf.xz"))}
    files = set()
    for r in csv.DictReader(open(os.path.join(ROOT, "benchmarks", "checksums.csv"))):
        files.add(r["hash"])
    for r in csv.DictReader(open(os.path.join(ROOT, "results", "three_way", "manifest.csv"))):
        if r.get("selected") == "1":
            files.add(r["hash"])
    for f in ("configs/observations_v5/confirm_hashes.txt", "configs/stable_selection_v6/validate_hashes.txt",
              "configs/completion_v7/panel.txt"):
        files |= set(open(os.path.join(ROOT, f)).read().split())
    hashes = run | files
    iso = {feat[h]["isohash"] for h in hashes if h in feat and feat[h]["isohash"]}
    return hashes, iso, {"local_downloads": len(run), "listed": len(files), "union": len(hashes), "isohashes": len(iso)}


def year_of(t):
    m = re.search(r"_(\d{4})$", t)
    return int(m.group(1)) if m else None


def related(family):
    fam = (family or "").lower()
    for gen, words in RULE["related_families"].items():
        if any(w in fam for w in words):
            return gen
    return None


def pools():
    tracks, feat, size = load_meta()
    exp_h, exp_iso, exp_info = exposed(feat)
    first = {h: min([y for y in map(year_of, ts) if y] or [9999]) for h, ts in tracks.items()}
    out, taken = {}, set()
    for src in RULE["sources"]:
        pat = re.compile(src["tracks"])
        cand = sorted(h for h, ts in tracks.items() if any(pat.match(t) for t in ts))
        if src.get("first_year"):
            cand = [h for h in cand if first[h] == src["first_year"]]
        if src.get("exclude_tracks"):
            ex = re.compile(src["exclude_tracks"])
            cand = [h for h in cand if not any(ex.match(t) for t in tracks[h])]
        stats = collections.Counter(candidates=len(cand))
        keep = []
        for h in cand:
            f = feat.get(h, {})
            if h in exp_h:
                stats["exposed_hash"] += 1
            elif f.get("isohash") in exp_iso:
                stats["exposed_isohash"] += 1
            elif h in taken:
                stats["in_earlier_source"] += 1
            elif h not in size or size[h][0] > RULE["max_bytes"]:
                stats["too_large_or_no_size"] += 1
            else:
                keep.append(h)
        taken |= set(keep)
        rows = [{"hash": h, "family": feat.get(h, {}).get("family"), "isohash": feat.get(h, {}).get("isohash"),
                 "bytes": size[h][0], "clauses": size[h][1], "variables": size[h][2],
                 "gbd_result": feat.get(h, {}).get("result"), "tracks": sorted(tracks[h]), "key": key(h),
                 "related_v11_family": related(feat.get(h, {}).get("family"))} for h in keep]
        stats["pool"] = len(rows)
        out[src["name"]] = {"source": src, "stats": dict(stats), "rows": rows,
                            "families": dict(collections.Counter(r["family"] for r in rows))}
    return out, exp_info


def audit():
    P, exp_info = pools()
    os.makedirs(RES, exist_ok=True)
    summ = {name: {"stats": p["stats"], "families": p["families"]} for name, p in P.items()}
    json.dump({"rule_sha256": hashlib.sha256(open(os.path.join(CFG, "public_rule.json"), "rb").read()).hexdigest(),
               "exposure": exp_info, "pools": summ}, open(os.path.join(RES, "public_pools.json"), "w"), indent=1)
    for name, p in P.items():
        print(name, p["stats"], len(p["families"]))


def pilot_rows(P):
    rows = []
    for name, p in P.items():
        for r in sorted(p["rows"], key=lambda r: r["key"])[:RULE["pilot_per_source"]]:
            rows.append(dict(r, source=name))
    return rows


def pilot():
    P, _ = pools()
    rows = pilot_rows(P)
    json.dump({"rule": "first pilot_per_source rows of each source pool in fixed hash order", "instances": rows},
              open(os.path.join(RES, "public_pilot.json"), "w"), indent=1)
    print(len(rows), "pilot instances")


def pilot_outcomes(stage):
    """D outcome per pilot hash: ('timeout' | 'fast' | 'mid')."""
    out = {}
    for p in glob.glob(os.path.join(DATA, "runs", "broad_scope_v11", stage, "*.json")):
        if p.endswith(("progress.json", "effective_plan.json")):
            continue
        r = json.load(open(p))
        h = r["instance"].split("-")[-1]
        solved = r.get("exit_code") in (10, 20) and (r.get("verification") or {}).get("ok") and r["cpu"] <= 3600
        out[h] = "timeout" if not solved else ("fast" if r["cpu"] < 1.0 else "mid")
    return out


def select(pilot_stage):
    P, _ = pools()
    pil = {r["hash"] for r in pilot_rows(P)}
    outc = pilot_outcomes(pilot_stage) if pilot_stage else {}
    picks, report, iso_seen = [], {}, set()
    for name, p in P.items():
        rows = sorted((r for r in p["rows"] if r["hash"] not in pil), key=lambda r: r["bytes"])
        po = [outc.get(r["hash"]) for r in pilot_rows({name: p})]
        adj = None
        if sum(o == "timeout" for o in po) >= RULE["adjust_if_at_least"]:
            rows, adj = rows[:len(rows) // 2], "lower half by bytes (pilot mostly timeouts)"
        elif sum(o == "fast" for o in po) >= RULE["adjust_if_at_least"]:
            rows, adj = rows[len(rows) // 2:], "upper half by bytes (pilot mostly < 1 s)"
        n = len(rows)
        terc = [rows[:n // 3], rows[n // 3:2 * n // 3], rows[2 * n // 3:]]
        per = RULE["quota_per_source"] // 3
        cap = max(RULE["family_cap_per_source"], -(-RULE["quota_per_source"] // max(1, len(p["families"]))))
        fam_n, got = collections.Counter(), []
        for t, part in enumerate(terc):
            k = 0
            for r in sorted(part, key=lambda r: r["key"]):
                if k >= per:
                    break
                if fam_n[r["family"]] >= cap or r["isohash"] in iso_seen:
                    continue
                fam_n[r["family"]] += 1
                iso_seen.add(r["isohash"])
                got.append(dict(r, source=name, size_tercile=t))
                k += 1
        picks += got
        report[name] = {"pilot_outcomes": po, "adjustment": adj, "family_cap": cap, "pool_after_adjustment": n, "picked": len(got),
                        "short_by": RULE["quota_per_source"] - len(got)}
    for r in picks:
        r["id"] = "v11p-" + r["source"] + "-" + r["hash"]
        r["unseen_in_v11_training"] = r["related_v11_family"] is None
    json.dump({"rule_sha256": hashlib.sha256(open(os.path.join(CFG, "public_rule.json"), "rb").read()).hexdigest(),
               "pilot_stage": pilot_stage, "report": report, "instances": picks},
              open(os.path.join(RES, "public_selection.json"), "w"), indent=1)
    fam = collections.Counter(r["family"] for r in picks)
    print(len(picks), "picked;", {k: v["picked"] for k, v in report.items()}, "families", len(fam),
          "unseen families", len({r["family"] for r in picks if r["unseen_in_v11_training"]}))


def fetch(which):
    src = {"pilot": "public_pilot.json", "formal": "public_selection.json"}[which]
    rows = json.load(open(os.path.join(RES, src)))["instances"]
    os.makedirs(os.path.join(EXT, "xz"), exist_ok=True)
    os.makedirs(os.path.join(EXT, "cnf"), exist_ok=True)
    out = []
    for r in rows:
        h = r["hash"]
        xz = os.path.join(EXT, "xz", h + ".cnf.xz")
        if not os.path.exists(xz):
            for attempt in range(4):
                try:
                    tmp = xz + ".part"
                    with urllib.request.urlopen(RULE["download_url"].format(hash=h), timeout=600) as u, \
                            open(tmp, "wb") as f:
                        while True:
                            b = u.read(1 << 20)
                            if not b:
                                break
                            f.write(b)
                    os.replace(tmp, xz)
                    break
                except Exception as e:  # noqa: BLE001
                    print("retry", h, e, file=sys.stderr)
                    time.sleep(10 * (attempt + 1))
        cnf = os.path.join(EXT, "cnf", h + ".cnf")
        if not os.path.exists(cnf):
            with lzma.open(xz) as fi, open(cnf + ".tmp", "wb") as fo:
                while True:
                    b = fi.read(1 << 22)
                    if not b:
                        break
                    fo.write(b)
            os.replace(cnf + ".tmp", cnf)
        hs = hashlib.sha256()
        with open(cnf, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                hs.update(b)
        out.append({"hash": h, "sha256": hs.hexdigest(), "sha256_xz": hashlib.sha256(open(xz, "rb").read()).hexdigest(),
                    "bytes": os.path.getsize(cnf), "path": os.path.relpath(cnf, DATA)})
    json.dump({"which": which, "files": out}, open(os.path.join(RES, f"public_files_{which}.json"), "w"), indent=1)
    print(len(out), "files")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["audit", "pilot", "select", "fetch"])
    ap.add_argument("--pilot-stage")
    ap.add_argument("--which", default="formal")
    a = ap.parse_args()
    if a.cmd == "audit":
        audit()
    elif a.cmd == "pilot":
        pilot()
    elif a.cmd == "select":
        select(a.pilot_stage)
    else:
        fetch(a.which)


if __name__ == "__main__":
    main()
