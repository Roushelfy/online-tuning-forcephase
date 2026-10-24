#!/usr/bin/env python3
"""v9 external public instances (protocol section 2.4; fixed after the rule freeze, before any external run).

  external.py   (run inside the container with the generator venv, which provides generate.py's helpers)

SATLIB archives downloaded to $FP_DATA/online_selection_v9/external/downloads and extracted per archive.
Selection by file name only (sorted): uf250-1065 first 8, uuf250-1065 first 7, flat200-479 first 15,
sw100-8-lp0-c5 first 15 (the first archive of the sw100-8 family in SATLIB's list), structured: bw_large.a-d,
logistics.a-d, and the first file of each qgN family (qg1..qg7). Files are parsed and
re-written comment-free (SATLIB's trailing '%' / '0' lines dropped); the manifest keeps the original file's
SHA-256. Exposure audit: canonical / renaming-invariant hashes vs every v8 and v9 instance, and vs the
competition CNFs whose GBD file names match these families. Writes results/online_selection_v9/
external_manifest.json, configs/online_selection_v9/panel_external.txt and the run plan external.json.
"""
import glob
import hashlib
import json
import lzma
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import generate as G  # noqa: E402

DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
EXT = os.path.join(DATA, "online_selection_v9", "external")
CFG = os.path.join(ROOT, "configs", "online_selection_v9")
RES = os.path.join(ROOT, "results", "online_selection_v9")


def files(archive):
    return sorted(p for p in glob.glob(os.path.join(EXT, "extracted", archive, "**", "*.cnf"), recursive=True))


def nat(p):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", os.path.basename(p))]


def select():
    sel = []
    for arch, k in (("uf250-1065", 8), ("uuf250-1065", 7), ("flat200-479", 15), ("sw100-8-lp0-c5", 15)):
        sel += [(arch, p) for p in sorted(files(arch), key=nat)[:k]]
    bw = [p for p in files("blocksworld") if re.match(r"bw_large\.[a-d]\.cnf$", os.path.basename(p))]
    lg = [p for p in files("logistics") if re.match(r"logistics\.[a-d]\.cnf$", os.path.basename(p))]
    qg = {}
    for p in sorted(files("QG"), key=nat):
        fam = os.path.basename(p).split("-")[0]
        qg.setdefault(fam, p)
    sel += [("blocksworld", p) for p in sorted(bw, key=nat)] + [("logistics", p) for p in sorted(lg, key=nat)] + \
           [("QG", qg[f]) for f in sorted(qg, key=nat)]
    return sel


def main():
    rows = []
    os.makedirs(G.CNF_DIR, exist_ok=True)
    for arch, p in select():
        raw = open(p, "rb").read()
        nv, clauses = G.parse_dimacs(raw.decode("latin-1"))
        text = G.dimacs(nv, clauses)
        iid = "ext-" + arch + "-" + os.path.basename(p)[:-4]
        out = os.path.join(G.CNF_DIR, iid + ".cnf")
        if not os.path.exists(out):
            with open(out + ".tmp", "w") as f:
                f.write(text)
            os.rename(out + ".tmp", out)
        rows.append({"id": iid, "archive": arch, "source_file": os.path.relpath(p, EXT),
                     "source_sha256": hashlib.sha256(raw).hexdigest(), "sha256": hashlib.sha256(text.encode()).hexdigest(),
                     "canonical_sha256": G.canonical_hash(clauses), "invariant_sha256": G.invariant_hash(nv, clauses),
                     "vars": nv, "clauses": len(clauses)})
    # exposure / duplicate audit
    seen = {}
    for mp in glob.glob(os.path.join(RES, "*manifest.json")) + glob.glob(os.path.join(ROOT, "results", "stratified_v8", "*manifest.json")):
        if mp.endswith("external_manifest.json"):
            continue
        for r in json.load(open(mp))["instances"]:
            for k in ("canonical_sha256", "invariant_sha256"):
                if r.get(k):
                    seen[(k, r[k])] = r["id"]
    comp = []
    db = sqlite3.connect(os.path.join(DATA, "benchmarks", "gbd", "meta.db"))
    names = [h for pat in ("uf250%", "uuf250%", "flat200%", "sw100%", "bw_large%", "logistics%", "qg%")
             for h, _ in db.execute("select hash, value from filename where value like ?", (pat,)).fetchall()]
    for h in set(names):
        f = os.path.join(DATA, "benchmarks", "cnf", h + ".cnf.xz")
        if os.path.exists(f):
            nv, cl = G.parse_dimacs(lzma.open(f).read().decode("latin-1"))
            comp.append({"gbd_hash": h, "canonical_sha256": G.canonical_hash(cl), "invariant_sha256": G.invariant_hash(nv, cl)})
            for k in ("canonical_sha256", "invariant_sha256"):
                seen[(k, comp[-1][k])] = "gbd:" + h
    dups = []
    for r in rows:
        for k in ("canonical_sha256", "invariant_sha256"):
            if (k, r[k]) in seen:
                dups.append((r["id"], k, seen[(k, r[k])]))
            seen[(k, r[k])] = r["id"]
    man = {"source": "SATLIB https://www.cs.ubc.ca/~hoos/SATLIB/benchm.html",
           "archives": {os.path.basename(a): hashlib.sha256(open(a, "rb").read()).hexdigest()
                        for a in sorted(glob.glob(os.path.join(EXT, "downloads", "*.tar.gz")))},
           "notes": ["qg: first file of each qgN family by natural name order"],
           "competition_name_matches_checked": comp, "duplicates": dups, "instances": rows}
    json.dump(man, open(os.path.join(RES, "external_manifest.json"), "w"), indent=1)
    ids = [r["id"] for r in rows if not any(d[0] == r["id"] for d in dups)]
    with open(os.path.join(CFG, "panel_external.txt"), "w") as f:
        f.write(f"# v9 external SATLIB panel ({len(ids)} instances), fixed by scripts/online_selection_v9/external.py\n")
        f.writelines(i + "\n" for i in ids)
    jobs = []
    for r in rows:
        if r["id"] not in ids:
            continue
        b = {"instance": r["id"], "sha256": r["sha256"], "rep": 0}
        jobs += [dict(b, method=m) for m in ("D", "Fp", "Fm")]
        jobs.append(dict(b, method="W", strategy="configs/online_selection_v9/strategies/ref_D2_Fp.json"))
    json.dump({"stage": "external_r2", "jobs": jobs}, open(os.path.join(CFG, "external.json"), "w"), indent=1)
    print(len(rows), "selected;", len(ids), "kept; duplicates", dups, "; competition matches checked", len(comp))


if __name__ == "__main__":
    main()
