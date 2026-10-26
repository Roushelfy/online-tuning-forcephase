#!/usr/bin/env bash
# Panel freeze steps (protocol 3.4-3.5), run inside the gs-srun container after scales.json is fixed:
# formal generation, dedupe audit + split + development plans, renaming variants, robustness plan, external selection.
set -euo pipefail
cd "$(dirname "$0")/../.."
export FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
GENPY=/mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python
python3 scripts/cross_scale_v10/plans.py formal-gen
$GENPY scripts/cross_scale_v10/gen.py generate --plan configs/cross_scale_v10/formal_gen.json --out-manifest results/cross_scale_v10/formal_manifest.json
python3 scripts/cross_scale_v10/plans.py formal-plans
$GENPY scripts/cross_scale_v10/gen.py variants --plan configs/cross_scale_v10/robust_variants.json
python3 scripts/cross_scale_v10/plans.py robust-plan
$GENPY scripts/cross_scale_v10/gen.py external
