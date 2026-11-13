"""Check cnf_unit_unique against a direct Python reference on random small CNFs (duplicates, units, empty clauses)."""
import json, random, subprocess, sys, tempfile
from collections import Counter

def reference(clauses):
    occ = Counter(l for c in clauses for l in c)
    units = [c for c in clauses if len(c) == 1]
    uniq = [c for c in clauses if c and all(occ[l] == 1 for l in c)]
    vars_ = {abs(l) for l in occ}
    lits = sum(len(c) for c in uniq); pos = sum(l > 0 for c in uniq for l in c)
    maj = Counter("p" if occ[v] > occ[-v] else "n" if occ[-v] > occ[v] else "t" for v in vars_)
    m = len(clauses) or 1; vo = len(vars_) or 1
    return {"unit_count": len(units), "unit_pos": sum(c[0] > 0 for c in units), "uniq_count": len(uniq), "uniq_lits": lits,
            "uniq_pos_lits": pos, "uniq_allpos": sum(all(l > 0 for l in c) for c in uniq),
            "uniq_allneg": sum(all(l < 0 for l in c) for c in uniq), "uniq_units": sum(len(c) == 1 for c in uniq),
            "empty_clauses": sum(not c for c in clauses), "maj_pos_frac": maj["p"] / vo, "maj_tie_frac": maj["t"] / vo,
            "lit_once_frac": sum(v == 1 for v in occ.values()) / (len(occ) or 1)}

def main(binary):
    rng = random.Random(1)
    for trial in range(300):
        n = rng.randint(1, 12); clauses = []
        for _ in range(rng.randint(1, 25)):
            k = rng.choice([0, 1, 1, 2, 3, 4]) if trial % 7 else rng.randint(1, 3)
            clauses.append([rng.choice([-1, 1]) * rng.randint(1, n) for _ in range(k)])
        text = f"c test\np cnf {n} {len(clauses)}\n" + "".join(" ".join(map(str, c + [0])) + "\n" for c in clauses)
        with tempfile.NamedTemporaryFile("w", suffix=".cnf") as f:
            f.write(text); f.flush()
            got = json.loads(subprocess.run([binary, f.name], capture_output=True, text=True, check=True).stdout)
        exp = reference(clauses)
        for k, v in exp.items():
            assert abs(got[k] - v) < 1e-9, (trial, k, got[k], v, clauses)
    print("cnf_unit_unique matches the reference on 300 random formulas")

if __name__ == "__main__":
    main(sys.argv[1])
