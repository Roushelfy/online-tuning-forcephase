#!/usr/bin/env python3
"""v9 instance generator (docs/ONLINE_SELECTION_PROTOCOL_V9.md section 2).

  generate.py --plan <plan.json> --out-manifest <manifest.json>

Run inside the gs-srun container with the pinned generator venv
(configs/stratified_v8/gen-requirements.txt):
  /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python scripts/online_selection_v9/generate.py ...

Plan rows: {id, type, param, seed[, structure]}; types rand3 / col3 (as v8),
assign2 (v9 coupled assignment, structure A/B/C from generators.json) and
assign0 (the v8 assignment structure, fast control). CNFs are written
comment-free to $FP_DATA/online_selection_v9/cnf/<id>.cnf. The manifest
records command / parameters / seed, generator versions, SHA-256, an
order-independent clause-set hash and a renaming-invariant hash (duplicate /
isomorphism screen; equal invariants are necessary for isomorphism), sizes
and generation CPU. Re-generation must reproduce the stored SHA-256.
"""

import argparse
import collections
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
CNF_DIR = os.path.join(DATA, "online_selection_v9", "cnf")
GRAPH_DIR = os.path.join(DATA, "online_selection_v9", "graphs")
GEN = json.load(open(os.path.join(ROOT, "configs", "online_selection_v9", "generators.json")))
VENV_BIN = os.path.dirname(sys.executable)


def cpu_now():
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def parse_dimacs(text):
    nv, clauses, cur = 0, [], []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("%"):
            break  # SATLIB end-of-formula marker; a following lone '0' is not an empty clause (deviation 3)
        if not line or line[0] == "c":
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
    h = hashlib.sha256()
    for c in sorted(tuple(sorted(c)) for c in clauses):
        h.update((" ".join(map(str, c)) + "\n").encode())
    return h.hexdigest()


def invariant_hash(nv, clauses):
    """Invariant under variable renaming and clause/literal order (not under sign flips): each literal is
    replaced by its variable's (positive, negative) occurrence counts oriented by the literal's sign."""
    pos, neg = collections.Counter(), collections.Counter()
    for c in clauses:
        for l in c:
            (pos if l > 0 else neg)[abs(l)] += 1
    sig = lambda l: (pos[l], neg[l]) if l > 0 else (neg[-l], pos[-l])  # noqa: E731
    cl = sorted(tuple(sorted(sig(l) for l in c)) for c in clauses)
    h = hashlib.sha256(f"{nv} {len(clauses)}\n".encode())
    for c in cl:
        h.update((repr(c) + "\n").encode())
    return h.hexdigest()


def cnfgen(args, seed):
    cmd = [os.path.join(VENV_BIN, "cnfgen"), "-q", "--seed", str(seed)] + [str(a) for a in args]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return ["cnfgen"] + cmd[1:], parse_dimacs(out)


def sample_gnm(n, m, rng):
    edges = set()
    while len(edges) < m:
        u, v = rng.sample(range(n), 2)
        edges.add((min(u, v), max(u, v)))
    return sorted(edges)


def gen_rand3(n, seed, _s=None):
    g = GEN["rand3"]
    m = round(g["ratio"] * n)
    cmd, cnf = cnfgen(["randkcnf", g["k"], n, m], seed)
    return cmd, cnf, {"n": n, "m": m}


def gen_col3(n, seed, _s=None):
    g = GEN["col3"]
    m = round(g["edges_per_vertex"] * n)
    edges = sample_gnm(n, m, random.Random(seed))
    os.makedirs(GRAPH_DIR, exist_ok=True)
    gpath = os.path.join(GRAPH_DIR, f"col3_n{n}_m{m}_s{seed}.dimacs")
    text = f"p edge {n} {m}\n" + "".join(f"e {u + 1} {v + 1}\n" for u, v in edges)
    tmp = f"{gpath}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, gpath)
    cmd, cnf = cnfgen(["kcolor", g["colors"], "dimacs", gpath], seed)
    return cmd, cnf, {"n": n, "m": m, "graph_file": os.path.relpath(gpath, DATA),
                      "graph_sha256": hashlib.sha256(text.encode()).hexdigest()}


def assignment(T, seed, st):
    """Coupled assignment with structure st (dict); returns (nv, clauses), params."""
    from pysat.card import CardEnc, EncType
    R, L = st["resources"], st["list_size"]
    rng = random.Random(seed)
    lists = [sorted(rng.sample(range(R), L)) for _ in range(T)]
    edges = sample_gnm(T, round(st["conflicts_per_task"] * T), rng)
    cap = math.ceil(st["capacity_slack"] * T / R)
    low = None if st.get("lower_gap") is None else max(0, T // R - st["lower_gap"])
    var, nv = {}, 0
    for t in range(T):
        for r in lists[t]:
            nv += 1
            var[(t, r)] = nv
    clauses = []
    enc = getattr(EncType, GEN["assign2"]["encoding"])
    for t in range(T):
        c = CardEnc.equals([var[(t, r)] for r in lists[t]], bound=1, top_id=nv, encoding=enc)
        nv = max(nv, c.nv)
        clauses += c.clauses
    for r in range(R):
        lits = [var[(t, r)] for t in range(T) if (t, r) in var]
        if len(lits) > cap:
            c = CardEnc.atmost(lits, bound=cap, top_id=nv, encoding=enc)
            nv = max(nv, c.nv)
            clauses += c.clauses
        if low:
            if len(lits) < low:
                clauses.append([])  # cannot be met: unsatisfiable by construction (recorded, never filtered)
            else:
                c = CardEnc.atleast(lits, bound=low, top_id=nv, encoding=enc)
                nv = max(nv, c.nv)
                clauses += c.clauses
    for u, v in edges:
        for r in sorted(set(lists[u]) & set(lists[v])):
            clauses.append([-var[(u, r)], -var[(v, r)]])
    return (nv, clauses), {"T": T, "R": R, "L": L, "conflict_edges": len(edges), "capacity": cap, "lower": low}


def gen_assign2(T, seed, structure):
    st = GEN["assign2"]["structures"][structure]
    cnf, prm = assignment(T, seed, st)
    prm["structure"] = structure
    cmd = ["generate.py:assign2", f"T={T}", f"seed={seed}", f"structure={structure}"] + [f"{k}={st[k]}" for k in sorted(st)]
    return cmd, cnf, prm


def gen_assign0(T, seed, _s=None):
    st = {k: GEN["assign0"][k] for k in ("resources", "list_size", "conflicts_per_task", "capacity_slack", "lower_gap")}
    cnf, prm = assignment(T, seed, st)
    cmd = ["generate.py:assign0", f"T={T}", f"seed={seed}"] + [f"{k}={st[k]}" for k in sorted(st)]
    return cmd, cnf, prm


GENERATORS = {"rand3": gen_rand3, "col3": gen_col3, "assign2": gen_assign2, "assign0": gen_assign0}


def versions():
    from importlib.metadata import version
    out = {"python": sys.version.split()[0]}
    for name in ("cnfgen", "python-sat", "networkx"):
        try:
            out[name] = version(name)
        except Exception:  # noqa: BLE001
            out[name] = None
    return out


def make(inst):
    os.makedirs(CNF_DIR, exist_ok=True)
    c0 = cpu_now()
    cmd, (nv, clauses), params = GENERATORS[inst["type"]](inst["param"], inst["seed"], inst.get("structure"))
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
    row.update(cmd=cmd, params=params, sha256=sha, canonical_sha256=canonical_hash(clauses),
               invariant_sha256=invariant_hash(nv, clauses), vars=nv, clauses=len(clauses), literals=sum(lens),
               units=sum(1 for x in lens if x == 1), binaries=sum(1 for x in lens if x == 2), gen_cpu=cpu,
               path=os.path.relpath(path, DATA))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out-manifest", required=True)
    a = ap.parse_args()
    plan = json.load(open(a.plan))
    rows = [make(i) for i in plan["instances"]]
    seen = {}
    for r in rows:
        for k in ("sha256", "canonical_sha256", "invariant_sha256"):
            if r[k] in seen.setdefault(k, {}):
                raise SystemExit(f"duplicate {k}: {r['id']} and {seen[k][r[k]]}")
            seen[k][r[k]] = r["id"]
    out = {"generator_versions": versions(), "generators": GEN, "instances": rows,
           "gen_cpu_total": sum(r["gen_cpu"] for r in rows)}
    os.makedirs(os.path.dirname(os.path.abspath(a.out_manifest)), exist_ok=True)
    with open(a.out_manifest, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"instances": len(rows), "gen_cpu_total": round(out["gen_cpu_total"], 3)}))


if __name__ == "__main__":
    main()
