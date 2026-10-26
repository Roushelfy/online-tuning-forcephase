#!/usr/bin/env python3
"""Goal v10 instance generation and external conversion (docs/CROSS_SCALE_PROTOCOL_V10.md section 3).
Run inside the gs-srun container with the pinned generator venv (configs/stratified_v8/gen-requirements.txt):

  .../online-tuning-forcephase-v8gen/bin/python scripts/cross_scale_v10/gen.py generate --plan P.json --out-manifest M.json
  .../online-tuning-forcephase-v8gen/bin/python scripts/cross_scale_v10/gen.py external
  .../online-tuning-forcephase-v8gen/bin/python scripts/cross_scale_v10/gen.py variants --plan V.json

generate: the v9 generators unchanged (scripts/online_selection_v9/generate.py with
configs/online_selection_v9/generators.json; rand3, col3, assign2 structure F), writing to
$FP_DATA/cross_scale_v10/cnf. Rows {id, type, param, seed, structure, level, role}.
external: the pre-registered SATLIB selection (configs/cross_scale_v10/external_rule.json), comment-free
re-write ('%' ends a formula), duplicate / exposure audit; writes results/cross_scale_v10/external_manifest.json.
variants: renaming variants (build/tools/cnfscramble perm <seed>) for the robustness diagnostic.
"""
import argparse
import glob
import hashlib
import json
import lzma
import os
import re
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "online_selection_v9"))
import generate as G  # noqa: E402

DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
G.CNF_DIR = os.path.join(DATA, "cross_scale_v10", "cnf")
G.GRAPH_DIR = os.path.join(DATA, "cross_scale_v10", "graphs")
VAR_DIR = os.path.join(DATA, "cross_scale_v10", "cnf_variants")
EXT = os.path.join(DATA, "cross_scale_v10", "external")
CFG = os.path.join(ROOT, "configs", "cross_scale_v10")
RES = os.path.join(ROOT, "results", "cross_scale_v10")


def generate(plan_path, man_path):
    plan = json.load(open(plan_path))
    rows = []
    for inst in plan["instances"]:
        row = G.make(inst)
        rows.append(row)
    seen = {}
    for r in rows:
        for k in ("sha256", "canonical_sha256", "invariant_sha256"):
            if r[k] in seen.setdefault(k, {}):
                raise SystemExit(f"duplicate {k}: {r['id']} and {seen[k][r[k]]}")
            seen[k][r[k]] = r["id"]
    out = {"generator_versions": G.versions(), "generators": G.GEN,
           "generators_file_sha256": hashlib.sha256(open(os.path.join(ROOT, "configs", "online_selection_v9",
                                                                     "generators.json"), "rb").read()).hexdigest(),
           "instances": rows, "gen_cpu_total": sum(r["gen_cpu"] for r in rows)}
    os.makedirs(os.path.dirname(os.path.abspath(man_path)), exist_ok=True)
    with open(man_path, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"instances": len(rows), "gen_cpu_total": round(out["gen_cpu_total"], 3)}))


def nat(p):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", os.path.basename(p))]


def header_size(p):
    with open(p, "rb") as f:
        for raw in f:
            if raw.startswith(b"p"):
                t = raw.split()
                return int(t[2]), int(t[3])
    return 0, 0


def exposed_hashes():
    """canonical / invariant hashes of every instance used in v8, v9 and v10 (core) and of the competition CNFs
    whose GBD file names match the external families."""
    seen = {}
    mans = (glob.glob(os.path.join(ROOT, "results", "online_selection_v9", "*manifest.json"))
            + glob.glob(os.path.join(ROOT, "results", "stratified_v8", "*manifest.json"))
            + [p for p in glob.glob(os.path.join(RES, "*manifest.json")) if not p.endswith("external_manifest.json")])
    for mp in mans:
        for r in json.load(open(mp))["instances"]:
            for k in ("canonical_sha256", "invariant_sha256"):
                if r.get(k):
                    seen[(k, r[k])] = os.path.basename(mp) + ":" + r["id"]
    return seen


def external():
    rule = json.load(open(os.path.join(CFG, "external_rule.json")))
    exposed = exposed_hashes()
    comp = []
    db = sqlite3.connect(os.path.join(DATA, "benchmarks", "gbd", "meta.db"))
    for pat in rule["gbd_name_patterns"]:
        for h, name in db.execute("select hash, value from filename where value like ?", (pat,)).fetchall():
            f = os.path.join(DATA, "benchmarks", "cnf", h + ".cnf.xz")
            if os.path.exists(f) and h not in {c["gbd_hash"] for c in comp}:
                nv, cl = G.parse_dimacs(lzma.open(f).read().decode("latin-1"))
                comp.append({"gbd_hash": h, "name": name, "canonical_sha256": G.canonical_hash(cl),
                             "invariant_sha256": G.invariant_hash(nv, cl)})
                for k in ("canonical_sha256", "invariant_sha256"):
                    exposed[(k, comp[-1][k])] = "gbd:" + h
    os.makedirs(G.CNF_DIR, exist_ok=True)
    rows, skipped, picked_keys = [], [], {}
    for fam in rule["families"]:
        files = sorted(glob.glob(os.path.join(EXT, "extracted", fam["archive"], "**", "*.cnf"), recursive=True), key=nat)
        files = [p for p in files if os.path.basename(p) not in set(fam.get("exclude", []))]
        files.sort(key=lambda p: (header_size(p)[1], nat(p)))  # by clause count, then natural name
        n, q = len(files), fam["quota"]
        order = []  # evenly spaced size-quantile positions first; replacements: the remaining files in size order
        for k in range(min(q, n)):
            order.append(int(round((k + 0.5) * n / q - 0.5)) if q <= n else k)
        order = list(dict.fromkeys(order)) + [i for i in range(n) if i not in order]
        taken = 0
        for idx in order:
            if taken >= q:
                break
            p = files[idx]
            raw = open(p, "rb").read()
            nv, clauses = G.parse_dimacs(raw.decode("latin-1"))
            text = G.dimacs(nv, clauses)
            row = {"id": "v10e-" + fam["archive"] + "-" + os.path.basename(p)[:-4], "family": fam["archive"],
                   "group": fam["group"], "source_file": os.path.relpath(p, EXT),
                   "source_sha256": hashlib.sha256(raw).hexdigest(), "sha256": hashlib.sha256(text.encode()).hexdigest(),
                   "canonical_sha256": G.canonical_hash(clauses), "invariant_sha256": G.invariant_hash(nv, clauses),
                   "vars": nv, "clauses": len(clauses), "size_rank": idx, "family_files": n}
            hit = [exposed.get((k, row[k])) or picked_keys.get((k, row[k])) for k in ("canonical_sha256", "invariant_sha256")]
            hit = [h for h in hit if h]
            if hit:
                skipped.append({"id": row["id"], "duplicate_of": hit})
                continue
            out = os.path.join(G.CNF_DIR, row["id"] + ".cnf")
            if not os.path.exists(out):
                with open(out + ".tmp", "w") as f:
                    f.write(text)
                os.rename(out + ".tmp", out)
            elif hashlib.sha256(open(out, "rb").read()).hexdigest() != row["sha256"]:
                raise SystemExit(f"{out} differs from its source")
            row["path"] = os.path.relpath(out, DATA)
            for k in ("canonical_sha256", "invariant_sha256"):
                picked_keys[(k, row[k])] = row["id"]
            rows.append(row)
            taken += 1
        if taken < q:
            skipped.append({"family": fam["archive"], "short_by": q - taken})
    man = {"source": rule["source"], "rule_file_sha256": hashlib.sha256(open(os.path.join(CFG, "external_rule.json"), "rb").read()).hexdigest(),
           "archives": {os.path.basename(a): hashlib.sha256(open(a, "rb").read()).hexdigest()
                        for a in sorted(glob.glob(os.path.join(EXT, "downloads", "*.tar.gz")))},
           "competition_name_matches_checked": len(comp), "skipped": skipped, "instances": rows}
    os.makedirs(RES, exist_ok=True)
    json.dump(man, open(os.path.join(RES, "external_manifest.json"), "w"), indent=1)
    print(len(rows), "selected; skipped", skipped, "; competition name matches checked", len(comp))


def variants(plan_path):
    plan = json.load(open(plan_path))
    tool = os.path.join(ROOT, "build", "tools", "cnfscramble")
    os.makedirs(VAR_DIR, exist_ok=True)
    rows = []
    for v in plan["variants"]:
        src = os.path.join(G.CNF_DIR, v["base"] + ".cnf")
        out = os.path.join(VAR_DIR, v["id"] + ".cnf")
        subprocess.run([tool, src, out + ".tmp", v["op"], str(v["seed"])], check=True, capture_output=True)
        text = open(out + ".tmp", "rb").read()
        if os.path.exists(out) and open(out, "rb").read() != text:
            raise SystemExit(f"{out}: regenerated variant differs")
        os.rename(out + ".tmp", out)
        rows.append(dict(v, sha256=hashlib.sha256(text).hexdigest(), path=os.path.relpath(out, DATA),
                         cmd=["cnfscramble", os.path.relpath(src, DATA), v["id"] + ".cnf", v["op"], str(v["seed"])]))
    json.dump({"variants": rows}, open(os.path.join(RES, "variants_manifest.json"), "w"), indent=1)
    print(len(rows), "variants")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "external", "variants"])
    ap.add_argument("--plan")
    ap.add_argument("--out-manifest")
    a = ap.parse_args()
    if a.cmd == "generate":
        generate(a.plan, a.out_manifest)
    elif a.cmd == "external":
        external()
    else:
        variants(a.plan)


if __name__ == "__main__":
    main()
