#!/usr/bin/env bash
# Panel freeze steps (protocol 3.6, 5, 6), run inside the gs-srun container after configs/broad_scope_v11/scales.json
# is fixed and the public pilot is done: formal generation, dedupe audit, variants, development run plans, public
# selection + download.
set -euo pipefail
cd "$(dirname "$0")/../.."
export FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
GENPY=/mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python
R=results/broad_scope_v11
python3 scripts/broad_scope_v11/plans.py formal-gen
$GENPY scripts/broad_scope_v11/gen.py generate --plan configs/broad_scope_v11/formal_gen.json --out-manifest $R/formal_manifest.json
python3 scripts/broad_scope_v11/plans.py dedupe-audit
python3 scripts/broad_scope_v11/plans.py variants-gen
$GENPY scripts/broad_scope_v11/gen.py variants --plan configs/broad_scope_v11/variants_gen.json --out-manifest $R/variants_manifest.json
python3 scripts/broad_scope_v11/plans.py plan --manifest $R/formal_manifest.json --roles discovery,development --stage disc_dev --methods D,Fp,Fm
python3 scripts/broad_scope_v11/plans.py plan --manifest $R/formal_manifest.json --roles discovery,development --stage measure_pool --measure
python3 scripts/broad_scope_v11/plans.py plan --manifest $R/variants_manifest.json --stage encoding --methods D,Fp,Fm
python3 scripts/broad_scope_v11/plans.py plan --manifest $R/formal_manifest.json --ids-from configs/broad_scope_v11/variants_gen.json --stage seeds --methods D,Fp,Fm --seeds 1,2
python3 scripts/broad_scope_v11/public.py select --pilot-stage public_pilot
python3 scripts/broad_scope_v11/public.py fetch --which formal
python3 scripts/broad_scope_v11/public.py hashaudit --which formal
