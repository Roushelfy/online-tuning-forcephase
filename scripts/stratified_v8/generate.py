#!/usr/bin/env python3
"""v8 instance generator (docs/STRATIFIED_PROTOCOL_V8.md section 2).

  generate.py --plan configs/stratified_v8/<plan>.json --out-manifest <path.json>

Run inside the gs-srun container with the pinned generator venv
(configs/stratified_v8/gen-requirements.txt):
  /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python scripts/stratified_v8/generate.py ...

Three problem types, one size parameter each (the other parameters are fixed
in configs/stratified_v8/generators.json):
  rand3  : CNFgen `randkcnf 3 n m`, m = round(ratio * n), uniform literal signs
  col3   : uniform random graph G(n, m), m = round(edges_per_vertex * n), sampled here with
           random.Random(seed) and saved as a DIMACS graph; CNFgen `kcolor 3 dimacs <graph>`
  assign : coupled task assignment: T tasks, R resources, each task allowed on
           a random list of L resources, exactly one resource per task, a
           capacity (at most cap tasks) per resource, and a random conflict
           graph (two conflicting tasks never share a resource); cardinality
           constraints with PySAT CardEnc, sequential counter (fixed encoding).
Every CNF is written comment-free to $FP_DATA/stratified_v8/cnf/<id>.cnf; the
manifest records the exact command / parameters / seed, generator versions,
SHA-256 of the file, a canonical clause-set hash (duplicate check), sizes and
the generation CPU. An instance that already exists is re-generated and must
reproduce the same SHA-256.
"""

import argparse
import hashlib
import json
import math
import os
import random
import resource
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("FP_DATA", "/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase")
CNF_DIR = os.path.join(DATA, "stratified_v8", "cnf")
GEN = json.load(open(os.path.join(ROOT, "configs", "stratified_v8", "generators.json")))
VENV_BIN = os.path.dirname(sys.executable)


def cpu_now():
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def parse_dimacs(text):
    nv, clauses, cur = 0, [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "c%":
            continue
        if line[0] == "p":
            nv = int(line.split()[2])
            continue
        for tok in line.split():
            v = int(tok)
            if v == 0:
                clauses.append(cur)
                cur = []
            else:
                cur.append(v)
    return nv, clauses


def dimacs(nv, clauses):
    return "p cnf %d %d\n" % (nv, len(clauses)) + "".join(" ".join(map(str, c)) + " 0\n" for c in clauses)


def canonical_hash(clauses):
    """Order-independent clause-set hash (literal order and clause order ignored)."""
    h = hashlib.sha256()
    for c in sorted(tuple(sorted(c)) for c in clauses):
        h.update((" ".join(map(str, c)) + "\n").encode())
    return h.hexdigest()


def cnfgen(args, seed):
    cmd = [os.path.join(VENV_BIN, "cnfgen"), "-q", "--seed", str(seed)] + [str(a) for a in args]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return ["cnfgen"] + cmd[1:], parse_dimacs(out)


def gen_rand3(n, seed):
    g = GEN["rand3"]
    m = round(g["ratio"] * n)
    return cnfgen(["randkcnf", g["k"], n, m], seed) + ({"n": n, "m": m},)


def sample_gnm(n, m, rng):
    """Uniform G(n, m): m distinct edges among n vertices (0-based), sorted."""
    edges = set()
    while len(edges) < m:
        u, v = rng.sample(range(n), 2)
        edges.add((min(u, v), max(u, v)))
    return sorted(edges)


def gen_col3(n, seed):
    """G(n, m) sampled here (CNFgen's `gnm` is built before --seed is applied, so it is not
    reproducible); the graph is saved in DIMACS graph format and encoded by CNFgen `kcolor`."""
    g = GEN["col3"]
    m = round(g["edges_per_vertex"] * n)
    edges = sample_gnm(n, m, random.Random(seed))
    gdir = os.path.join(DATA, "stratified_v8", "graphs")
    os.makedirs(gdir, exist_ok=True)
    gpath = os.path.join(gdir, f"col3_n{n}_m{m}_s{seed}.dimacs")
    text = f"p edge {n} {m}\n" + "".join(f"e {u + 1} {v + 1}\n" for u, v in edges)
    tmp = f"{gpath}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, gpath)
    cmd, cnf = cnfgen(["kcolor", g["colors"], "dimacs", gpath], seed)
    return cmd, cnf, {"n": n, "m": m, "graph_file": os.path.relpath(gpath, DATA),
                      "graph_sha256": hashlib.sha256(text.encode()).hexdigest()}


def gen_assign(T, seed):
    from pysat.card import CardEnc, EncType
    g = GEN["assign"]
    R, L = g["resources"], g["list_size"]
    rng = random.Random(seed)
    lists = [sorted(rng.sample(range(R), L)) for _ in range(T)]
    M = round(g["conflicts_per_task"] * T)
    edges = set()
    while len(edges) < M:
        u, v = rng.sample(range(T), 2)
        edges.add((min(u, v), max(u, v)))
    edges = sorted(edges)
    cap = math.ceil(g["capacity_slack"] * T / R)
    var, nv = {}, 0
    for t in range(T):
        for r in lists[t]:
            nv += 1
            var[(t, r)] = nv
    clauses = []
    enc = getattr(EncType, g["encoding"])
    for t in range(T):  # exactly one allowed resource per task
        c = CardEnc.equals([var[(t, r)] for r in lists[t]], bound=1, top_id=nv, encoding=enc)
        nv = max(nv, c.nv)
        clauses += c.clauses
    for r in range(R):  # capacity
        lits = [var[(t, r)] for t in range(T) if (t, r) in var]
        if len(lits) > cap:
            c = CardEnc.atmost(lits, bound=cap, top_id=nv, encoding=enc)
            nv = max(nv, c.nv)
            clauses += c.clauses
    for u, v in edges:  # conflicts
        for r in sorted(set(lists[u]) & set(lists[v])):
            clauses.append([-var[(u, r)], -var[(v, r)]])
    cmd = ["generate.py:gen_assign", f"T={T}", f"seed={seed}"] + [f"{k}={g[k]}" for k in sorted(g)]
    return cmd, (nv, clauses), {"T": T, "R": R, "L": L, "conflict_edges": M, "capacity": cap}


GENERATORS = {"rand3": gen_rand3, "col3": gen_col3, "assign": gen_assign}


def versions():
    out = {"python": sys.version.split()[0]}
    for mod, name in (("cnfgen", "cnfgen"), ("pysat", "python-sat"), ("networkx", "networkx")):
        try:
            from importlib.metadata import version
            out[name] = version(name)
        except Exception:  # noqa: BLE001
            out[name] = None
    return out


def make(inst):
    """inst: {id, type, param, seed, ...} -> manifest row."""
    os.makedirs(CNF_DIR, exist_ok=True)
    c0 = cpu_now()
    cmd, (nv, clauses), params = GENERATORS[inst["type"]](inst["param"], inst["seed"])
    text = dimacs(nv, clauses)
    cpu = cpu_now() - c0
    sha = hashlib.sha256(text.encode()).hexdigest()
    path = os.path.join(CNF_DIR, inst["id"] + ".cnf")
    if os.path.exists(path):
        old = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if old != sha:
            raise SystemExit(f"{inst['id']}: regenerated CNF differs from the stored one ({old} vs {sha})")
    else:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.rename(tmp, path)
    lens = [len(c) for c in clauses]
    row = dict(inst)
    row.update(cmd=cmd, params=params, sha256=sha, canonical_sha256=canonical_hash(clauses), vars=nv,
               clauses=len(clauses), literals=sum(lens), units=sum(1 for x in lens if x == 1),
               binaries=sum(1 for x in lens if x == 2), gen_cpu=cpu, path=os.path.relpath(path, DATA))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="JSON with 'instances': [{id, type, param, seed, ...}]")
    ap.add_argument("--out-manifest", required=True)
    a = ap.parse_args()
    plan = json.load(open(a.plan))
    rows = [make(i) for i in plan["instances"]]
    dup = {}
    for r in rows:
        for k in ("sha256", "canonical_sha256"):
            if r[k] in dup.setdefault(k, {}):
                raise SystemExit(f"duplicate {k}: {r['id']} and {dup[k][r[k]]}")
            dup[k][r[k]] = r["id"]
    out = {"generator_versions": versions(), "generators": GEN, "instances": rows,
           "gen_cpu_total": sum(r["gen_cpu"] for r in rows)}
    os.makedirs(os.path.dirname(os.path.abspath(a.out_manifest)), exist_ok=True)
    json.dump(out, open(a.out_manifest, "w"), indent=1)
    print(json.dumps({"instances": len(rows), "gen_cpu_total": round(out["gen_cpu_total"], 3),
                      "sizes": {r["id"]: [r["vars"], r["clauses"]] for r in rows}}))


if __name__ == "__main__":
    main()
