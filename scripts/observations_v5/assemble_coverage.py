#!/usr/bin/env python3
"""Assemble reports/observations_v5/COVERAGE_AND_ERRORS.md from the written
analysis (COVERAGE_AND_ERRORS_head.md), the V1 seed-repeat section
(V1_REPEAT.md, if present) and the generated V0 tables (V0_TABLES.md)."""
import os
REP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports", "observations_v5")
parts = [open(os.path.join(REP, "COVERAGE_AND_ERRORS_head.md")).read().rstrip() + "\n"]
rep = os.path.join(REP, "V1_REPEAT.md")
parts.append(open(rep).read().rstrip() + "\n" if os.path.exists(rep) else
             "## 6. seed 重复（V1）\n\n尚未运行：将在 V1 中于工程面板上补充（协议第 8 节第 5 项）。\n")
tab = open(os.path.join(REP, "V0_TABLES.md")).read().split("\n", 2)[2]
import re
parts.append("## 附：生成的表格（`scripts/observations_v5/v0_coverage.py`）\n\n" + re.sub(r"^## ", "### ", tab.lstrip(), flags=re.M))
open(os.path.join(REP, "COVERAGE_AND_ERRORS.md"), "w").write("\n".join(parts))
print("written")
