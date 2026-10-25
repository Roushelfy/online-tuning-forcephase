#!/usr/bin/env bash
# Run one v8 stage on a non-exclusive cpu-low allocation (72 logical CPUs = 36 physical cores, 700 GB) inside
# the gs-srun container. Optionally generate instances first (generator venv).
#   scripts/stratified_v8/slurm_run.sh <stage> <unlimited-placeholder; legacy number ignored> [plan.json] [gen-plan.json gen-manifest.json] [--quiet-outcomes]
# Logs: $FP_DATA/logs/slurm/v8-<stage>-<jobid>_0.{out,err}
# No aggregate CPU-hour limit (the legacy positional budget is ignored); every run is capped at 3600 CPU s
# by the controller (configs/run_timeout_policy.json).
# Slurm walltime is a scheduling constraint, not a scientific score or project quota.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$1"; BUDGET="${2:-unlimited}"; PLAN="${3:-}"; GENPLAN="${4:-}"; GENMAN="${5:-}"; QUIET="${6:-}"
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
# --array=0-0: gs-srun inside sbatch runs in the allocation only for array jobs
sbatch --parsable --job-name="v8-$STAGE" --partition=cpu-low --nodes=1 --ntasks=1 --cpus-per-task=72 --mem=700G \
  --time=12:00:00 --array=0-0 \
  --output="$FP_DATA/logs/slurm/v8-$STAGE-%A_%a.out" --error="$FP_DATA/logs/slurm/v8-$STAGE-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",V8_ROOT="$ROOT",V8_PLAN="$PLAN",V8_STAGE="$STAGE",V8_BUDGET="$BUDGET",V8_GENPLAN="$GENPLAN",V8_GENMAN="$GENMAN",V8_QUIET="$QUIET" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "v8 $V8_STAGE on $(hostname) at $(date -u)"
gs-srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-$SLURM_CPUS_ON_NODE}" bash -c "
  set -e; cd '$V8_ROOT'; export FP_DATA='$FP_DATA'
  if [ -n '$V8_GENPLAN' ]; then
    /mnt/data/zhaofeng/venvs/online-tuning-forcephase-v8gen/bin/python scripts/stratified_v8/generate.py --plan '$V8_GENPLAN' --out-manifest '$V8_GENMAN'
  fi
  if [ -n '$V8_PLAN' ]; then
    python3 scripts/stratified_v8/runner.py --plan '$V8_PLAN' --stage '$V8_STAGE' $V8_QUIET
  fi"
echo "finished at $(date -u)"
EOS
