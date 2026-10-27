#!/usr/bin/env python3
"""Goal v11 instance generation (docs/BROAD_SCOPE_PROTOCOL_V11.md section 3). Run inside the gs-srun container
with the pinned generator venv (configs/stratified_v8/gen-requirements.txt):

  $GENPY scripts/broad_scope_v11/gen.py generate --plan P.json --out-manifest M.json
  $GENPY scripts/broad_scope_v11/gen.py variants --plan V.json --out-manifest M.json
  $GENPY scripts/broad_scope_v11/gen.py semcheck --manifest M.json --runs STAGE[,STAGE..]

Plan rows {id, family, size, seed, [enc], [params], level, role}. Families: rand3 / col3 / assign2 (the v9
generators unchanged, scripts/online_selection_v9/generate.py; assign2 structure F) and vcover / jssp / bwplan /
factor / qcp (scripts/broad_scope_v11/families.py) with secondary parameters from
configs/broad_scope_v11/generators.json (a row's `params` overrides them -- exploration only). CNFs are written
comment-free to $FP_DATA/broad_scope_v11/cnf/<id>.cnf; the manifest records command, parameters, generator
versions, SHA-256, the order-independent and renaming-invariant hashes, sizes, generation CPU and the compact
problem description (semantic) used for the independent model check.
variants: rows {id, base, op, seed} with op 'flipall' / 'perm' (build/tools/cnfscramble) or 'enc:<name>' (the
same base problem re-encoded: col3 -> log, vcover -> totalizer, jssp -> time, qcp -> extended).
semcheck: decodes every verified SAT answer of the given run stages and checks it against the problem itself.
"""
import argparse
import glob
import gzip
import hashlib
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "online_selection_v9"))
import generate as G  # noqa: E402
import families as FAM  # noqa: E402
import semantic as SEM  # noqa: E402

DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
G.CNF_DIR = os.path.join(DATA, "broad_scope_v11", "cnf")
G.GRAPH_DIR = os.path.join(DATA, "broad_scope_v11", "graphs")
CNF_DIR = G.CNF_DIR
CFG = os.path.join(ROOT, "configs", "broad_scope_v11")
GEN11 = json.load(open(os.path.join(CFG, "generators.json")))
ALT = {"col3": "log", "vcover": "totalizer", "jssp": "time", "qcp": "extended"}
PRIMARY = {"col3": "direct", "vcover": "seqcounter", "jssp": "order", "qcp": "minimal", "bwplan": "seq",
           "factor": "array", "rand3": "cnfgen", "assign2": "seqcounter"}


def params_of(row):
    p = dict(GEN11.get(row["family"], {}).get("params", {}))
    p.update(row.get("params") or {})
    return p


def build(row, enc=None):
    """(cmd, (nv, clauses), params, semantic) of a plan row in encoding enc (default: the family's primary)."""
    fam, size, seed = row["family"], row["size"], row["seed"]
    enc = enc or row.get("enc") or PRIMARY[fam]
    if fam == "rand3":
        cmd, cnf, prm = G.gen_rand3(size, seed)
        return cmd, cnf, prm, {}
    if fam == "assign2":
        cmd, cnf, prm = G.gen_assign2(size, seed, GEN11["assign2"]["structure"])
        return cmd, cnf, prm, {}
    if fam == "col3":
        m = round(G.GEN["col3"]["edges_per_vertex"] * size)
        edges = G.sample_gnm(size, m, random.Random(seed))  # the graph G.gen_col3 samples (same rng, same calls)
        sem = {"n": size, "edges": edges}
        if enc == "direct":
            cmd, cnf, prm = G.gen_col3(size, seed)
            return cmd, cnf, prm, sem
        cnf = FAM.col3_log(size, edges)
        return ["families.py:col3_log", f"n={size}", f"seed={seed}"], cnf, {"n": size, "m": m, "enc": "log"}, sem
    return FAM.FAMILIES[fam](size, seed, params_of(row), enc)


def compact(fam, sem):
    """Problem description kept in the manifest (variable maps are rebuilt by re-generation)."""
    drop = {"var", "mv"}
    return {k: v for k, v in sem.items() if k not in drop}


def write_cnf(path, text):
    sha = hashlib.sha256(text.encode()).hexdigest()
    if os.path.exists(path):
        old = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if old != sha:
            raise SystemExit(f"{path}: regenerated CNF differs from the stored one ({old} vs {sha})")
    else:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.rename(tmp, path)
    return sha


def make(row, enc=None, out_id=None):
    os.makedirs(CNF_DIR, exist_ok=True)
    c0 = G.cpu_now()
    cmd, (nv, clauses), prm, sem = build(row, enc)
    text = G.dimacs(nv, clauses)
    cpu = G.cpu_now() - c0
    rid = out_id or row["id"]
    path = os.path.join(CNF_DIR, rid + ".cnf")
    sha = write_cnf(path, text)
    lens = [len(c) for c in clauses]
    out = dict(row, id=rid)
    out.update(enc=enc or row.get("enc") or PRIMARY[row["family"]], cmd=cmd, gen_params=prm, sha256=sha,
               canonical_sha256=G.canonical_hash(clauses), invariant_sha256=G.invariant_hash(nv, clauses), vars=nv,
               clauses=len(clauses), literals=sum(lens), units=sum(1 for x in lens if x == 1),
               binaries=sum(1 for x in lens if x == 2), gen_cpu=cpu, path=os.path.relpath(path, DATA),
               semantic=compact(row["family"], sem))
    return out


def versions():
    v = G.versions()
    v["families_py_sha256"] = hashlib.sha256(open(os.path.join(HERE, "families.py"), "rb").read()).hexdigest()
    v["generators_json_sha256"] = hashlib.sha256(open(os.path.join(CFG, "generators.json"), "rb").read()).hexdigest()
    return v


def dedupe(rows):
    seen = {}
    for r in rows:
        for k in ("sha256", "canonical_sha256", "invariant_sha256"):
            if r[k] in seen.setdefault(k, {}):
                raise SystemExit(f"duplicate {k}: {r['id']} and {seen[k][r[k]]}")
            seen[k][r[k]] = r["id"]


def generate(plan_path, man_path):
    plan = json.load(open(plan_path))
    rows = [make(i) for i in plan["instances"]]
    dedupe(rows)
    out = {"generator_versions": versions(), "generators_v9": {k: G.GEN[k] for k in ("rand3", "col3", "assign2")},
           "generators_v11": GEN11, "plan": os.path.relpath(os.path.abspath(plan_path), ROOT), "instances": rows,
           "gen_cpu_total": sum(r["gen_cpu"] for r in rows)}
    os.makedirs(os.path.dirname(os.path.abspath(man_path)), exist_ok=True)
    json.dump(out, open(man_path, "w"), indent=1)
    print(json.dumps({"instances": len(rows), "gen_cpu_total": round(out["gen_cpu_total"], 3)}))


def variants(plan_path, man_path):
    plan = json.load(open(plan_path))
    base = {}
    for mp in plan["base_manifests"]:
        for r in json.load(open(os.path.join(ROOT, mp)))["instances"]:
            base[r["id"]] = r
    tool = os.path.join(ROOT, "build", "tools", "cnfscramble")
    rows = []
    for v in plan["variants"]:
        b = base[v["base"]]
        if v["op"].startswith("enc:"):
            src = {k: b[k] for k in ("id", "family", "size", "seed", "level", "role") if k in b}
            if b.get("params"):
                src["params"] = b["params"]
            r = make(src, enc=v["op"][4:], out_id=v["id"])
            r.update(base=v["base"], op=v["op"], group=b.get("group", b["id"]))
        else:
            out = os.path.join(CNF_DIR, v["id"] + ".cnf")
            c0 = G.cpu_now()
            subprocess.run([tool, os.path.join(DATA, b["path"]), out + ".tmp", v["op"], str(v["seed"])], check=True,
                           capture_output=True)
            text = open(out + ".tmp", "rb").read()
            if os.path.exists(out) and open(out, "rb").read() != text:
                raise SystemExit(f"{out}: regenerated variant differs")
            os.rename(out + ".tmp", out)
            nv, cl = G.parse_dimacs(text.decode())
            r = {"id": v["id"], "base": v["base"], "op": v["op"], "seed": v["seed"], "family": b["family"],
                 "size": b["size"], "level": b.get("level"), "group": b.get("group", b["id"]), "enc": b["enc"],
                 "sha256": hashlib.sha256(text).hexdigest(), "canonical_sha256": G.canonical_hash(cl),
                 "invariant_sha256": G.invariant_hash(nv, cl), "vars": nv, "clauses": len(cl),
                 "gen_cpu": G.cpu_now() - c0, "path": os.path.relpath(out, DATA),
                 "cmd": ["cnfscramble", b["path"], v["id"] + ".cnf", v["op"], str(v["seed"])]}
        rows.append(r)
    json.dump({"generator_versions": versions(), "plan": os.path.relpath(os.path.abspath(plan_path), ROOT),
               "instances": rows, "gen_cpu_total": sum(r["gen_cpu"] for r in rows)}, open(man_path, "w"), indent=1)
    print(len(rows), "variants")


# ------------------------------------------------------------------ semantic check of SAT answers

def model_from_output(path):
    lits = []
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                lits += [int(t) for t in line[2:].split() if t != "0"]
    return lits


def flip_back(row, true):
    """Map a model of a cnfscramble variant back is not needed: the check decodes the variant's own base
    problem only for re-encodings; flipall / perm variants are checked by checkmodel alone."""
    return true


def semcheck(man_paths, stages):
    rows = {}
    for mp in man_paths:
        for r in json.load(open(mp))["instances"]:
            rows[r["id"]] = r
    out, n_ok, n_bad, n_skip = [], 0, 0, 0
    cache = {}
    for st in stages:
        for p in sorted(glob.glob(os.path.join(DATA, "runs", "broad_scope_v11", st, "*.json"))):
            if p.endswith(("progress.json", "effective_plan.json")):
                continue
            rec = json.load(open(p))
            if rec.get("exit_code") != 10 or not (rec.get("verification") or {}).get("ok"):
                continue
            row = rows.get(rec["instance"])
            if row is None or row.get("op") in ("flipall", "perm") or row["family"] in ("rand3", "assign2"):
                n_skip += 1
                continue
            fam = row["family"]
            key = (row["id"], row["enc"])
            if key not in cache:
                src = {k: row[k] for k in ("id", "family", "size", "seed") if k in row}
                if row.get("params"):
                    src["params"] = row["params"]
                _, (nv, cl), _, sem = build(src, row["enc"])
                if hashlib.sha256(G.dimacs(nv, cl).encode()).hexdigest() != row["sha256"]:
                    raise SystemExit(f"{row['id']}: re-generation does not reproduce the CNF")
                cache[key] = sem
            sem = cache[key]
            outp = os.path.join(DATA, rec["files"]["out"]) if rec.get("files", {}).get("out") else None
            if not outp or not os.path.exists(outp):
                n_skip += 1
                continue
            true = SEM.model_set(model_from_output(outp))
            ck = "col3log" if fam == "col3" and row["enc"] == "log" else fam
            ok = SEM.check(ck, sem, true)
            n_ok += ok
            n_bad += not ok
            out.append({"stage": st, "run": os.path.basename(p)[:-5], "instance": row["id"], "family": fam,
                        "enc": row["enc"], "ok": ok})
    res = {"checked": len(out), "ok": n_ok, "failed": n_bad, "skipped": n_skip, "rows": out}
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "variants", "semcheck"])
    ap.add_argument("--plan")
    ap.add_argument("--out-manifest")
    ap.add_argument("--manifest", action="append")
    ap.add_argument("--runs")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "generate":
        generate(a.plan, a.out_manifest)
    elif a.cmd == "variants":
        variants(a.plan, a.out_manifest)
    else:
        res = semcheck(a.manifest, a.runs.split(","))
        if a.out:
            json.dump(res, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
