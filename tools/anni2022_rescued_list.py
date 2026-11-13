"""Benchmark list for the professor: instances where D (default) times out at 600 CPU s but F+ or F- solves.

Reads the collected baseline snapshot (cluster_v3) and the GBD metadata database; writes one CSV per sheet and an
Excel workbook with the instance table, a family summary and the definitions.

  PY tools/anni2022_rescued_list.py --snapshot SNAPSHOT_DIR --gbd-meta META_DB --out OUT_DIR
"""
import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ACTIONS = ("D", "Fplus", "Fminus")
LABEL = {"D": "D", "Fplus": "F+", "Fminus": "F-"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", required=True); p.add_argument("--gbd-meta", required=True); p.add_argument("--out", required=True)
    a = p.parse_args()
    snap, out = Path(a.snapshot), Path(a.out); out.mkdir(parents=True, exist_ok=True)
    matrix = list(csv.DictReader((snap / "matrix.csv").open()))
    summary = json.loads((snap / "summary.json").read_text())
    # run_id -> shard root (evidence paths are "shard-XXX/runs/<run_id>/result.json")
    shard_of = {Path(e["path"]).parts[-2]: Path(e["path"]).parts[0] for e in summary["evidence"]}
    run_id = {(r["instance_key"], r["action"]): r["run_id"] for r in csv.DictReader((snap / "runs.csv").open())}
    root = summary["shard_roots"][0].rsplit("/", 1)[0]
    db = sqlite3.connect(f"file:{a.gbd_meta}?mode=ro", uri=True)
    name, path = {}, {}
    for h, v in db.execute("select hash, value from filename"): name.setdefault(h, v)
    for h, v in db.execute("select hash, value from local"): path.setdefault(h, v.replace("/raid/gbd/cnf-3/", ""))
    family = {h: f for h, f in db.execute("select hash, family from features")}
    author = {h: x for h, x in db.execute("select hash, author from features")}
    solved = lambda r, x: r[x + "_status"] in ("SAT", "UNSAT")
    family_total = Counter(family.get(r["instance_key"], "unknown") for r in matrix)
    rows = []
    for r in matrix:
        k = r["instance_key"]
        if r["D_status"] != "CPU_TIMEOUT" or not (solved(r, "Fplus") or solved(r, "Fminus")):
            continue
        ok = [LABEL[x] for x in ("Fplus", "Fminus") if solved(r, x)]
        answer = next(r[x + "_status"] for x in ("Fplus", "Fminus") if solved(r, x))
        row = {"instance": name.get(k), "family": family.get(k, "unknown"), "answer": answer, "successful_modes": " & ".join(ok)}
        for x in ACTIONS:
            row[f"{LABEL[x]}_status"] = "solved" if solved(r, x) else "timeout"
            row[f"{LABEL[x]}_cpu_s"] = round(float(r[x + "_cpu_s"]), 2)
        best = min((float(r[x + "_cpu_s"]), LABEL[x]) for x in ("Fplus", "Fminus") if solved(r, x))
        row.update({"best_mode": best[1], "best_cpu_s": round(best[0], 2), "gbd_hash": k, "author": author.get(k),
                    "download_url": f"https://benchmark-database.de/file/{k}", "original_path_in_gbd": path.get(k),
                    "run_records": f"{root}/{shard_of[run_id[(k, 'D')]]}/runs/"})
        rows.append(row)
    rows.sort(key=lambda r: (r["family"], r["instance"] or ""))
    fams = defaultdict(Counter)
    for r in rows:
        f = fams[r["family"]]; f["rescued"] += 1; f[r["successful_modes"]] += 1; f[r["answer"]] += 1
    fam_rows = [{"family": f, "instances_in_cohort": family_total[f], "rescued_by_F+_or_F-": c["rescued"],
                 "share_of_family_pct": round(100 * c["rescued"] / family_total[f], 1),
                 "F+_only": c["F+"], "F-_only": c["F-"], "both_F+_and_F-": c["F+ & F-"], "SAT": c["SAT"], "UNSAT": c["UNSAT"]}
                for f, c in sorted(fams.items(), key=lambda kv: (-kv[1]["rescued"], kv[0]))]
    total = {"family": "TOTAL", "instances_in_cohort": len(matrix), "rescued_by_F+_or_F-": len(rows),
             "share_of_family_pct": round(100 * len(rows) / len(matrix), 1),
             **{k: sum(x[k] for x in fam_rows) for k in ("F+_only", "F-_only", "both_F+_and_F-", "SAT", "UNSAT")}}
    fam_rows.append(total)
    info = [
        ("population", "SAT Competition 2022 Anniversary track, 4719 of 5355 instances (636 excluded because no official solver solved them on any track)"),
        ("solver", "CaDiCaL 3.0.1 (commit c607304), seed 0, 600 s solver CPU per run, binary LRAT"),
        ("modes", "D = --phase=1 --forcephase=0 (default); F+ = --phase=1 --forcephase=1; F- = --phase=0 --forcephase=1"),
        ("selection", "D timed out at 600 CPU s and at least one of F+ / F- solved; every listed solve is verified (SAT model check / UNSAT lrat-trim)"),
        ("times", "solver process CPU seconds; a timeout shows the CPU at which the run was stopped (about 600 s)"),
        ("family", "GBD 'family' attribute (benchmark-database.de); 'unknown' is GBD's own label"),
        ("source runs", f"{root} (24 shards), branch anni2022-cluster-run 0d82f6e; matrix SHA {__import__('hashlib').sha256((snap / 'matrix.csv').read_bytes()).hexdigest()}"),
        ("counts", f"{len(rows)} instances in {len(fam_rows) - 1} families: F+ only {total['F+_only']}, F- only {total['F-_only']}, both {total['both_F+_and_F-']}"),
    ]
    for fname, data in (("rescued_by_forced_phase.csv", rows), ("rescued_family_summary.csv", fam_rows)):
        with (out / fname).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
    try:
        import openpyxl
        from openpyxl.styles import Font
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "instances"
        for title, data in (("instances", rows), ("families", fam_rows)):
            ws = wb[title] if title in wb.sheetnames else wb.create_sheet(title)
            ws.append(list(data[0]))
            for r in data: ws.append([r[c] for c in data[0]])
            for c in ws[1]: c.font = Font(bold=True)
            ws.freeze_panes = "B2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(c.value or "")) for c in col) + 2))
        ws = wb.create_sheet("definitions")
        for k, v in info: ws.append([k, v])
        ws.column_dimensions["A"].width = 14; ws.column_dimensions["B"].width = 140
        wb.save(out / "rescued_by_forced_phase.xlsx")
    except ImportError:
        print("openpyxl missing: CSV only")
    print(json.dumps({"rescued": len(rows), "families": len(fam_rows) - 1, **{k: total[k] for k in ("F+_only", "F-_only", "both_F+_and_F-", "SAT", "UNSAT")}}))


if __name__ == "__main__":
    main()
