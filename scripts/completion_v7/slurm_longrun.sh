#!/usr/bin/env bash
# Run one v7 long-run stage on one exclusive cpu-low node (gs-srun container).
#   scripts/completion_v7/slurm_longrun.sh <plan.json> <stage> [legacy-budget-ignored=unlimited] [time=24:00:00] [cpus=exclusive|N]
# cpus=N requests a non-exclusive allocation of N logical CPUs (N/2 physical cores) and 700 GB.
# Logs: $FP_DATA/logs/slurm/v7-<stage>-<jobid>.{out,err}
# CPU-hour limits were withdrawn by the user; the legacy positional budget is ignored.
# Slurm walltime is a scheduling constraint, not a scientific score or project quota.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLAN="$1"; STAGE="$2"; BUDGET="${3:-unlimited}"; TIME="${4:-24:00:00}"; CPUS="${5:-exclusive}"
if [ "$CPUS" = exclusive ]; then RES=(--exclusive --mem=0); else RES=(--cpus-per-task="$CPUS" --mem=700G); fi
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
# --array=0-0: gs-srun inside sbatch runs in the allocation only for array jobs (otherwise it submits a new
# job in the default partition)
sbatch --parsable --job-name="v7-$STAGE" --partition=cpu-low --nodes=1 --ntasks=1 "${RES[@]}" --time="$TIME" --array=0-0 \
  --output="$FP_DATA/logs/slurm/v7-$STAGE-%A_%a.out" --error="$FP_DATA/logs/slurm/v7-$STAGE-%A_%a.err" \
  --export=ALL,FP_DATA="$FP_DATA",V7_ROOT="$ROOT",V7_PLAN="$PLAN",V7_STAGE="$STAGE",V7_BUDGET="$BUDGET" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "v7 $V7_STAGE on $(hostname) at $(date -u)"
gs-srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-$SLURM_CPUS_ON_NODE}" \
  bash -c "cd '$V7_ROOT' && FP_DATA='$FP_DATA' FP_LOCAL=/tmp/fp_local_\$USER python3 scripts/completion_v7/longrun.py --plan '$V7_PLAN' --stage '$V7_STAGE'"
echo "finished at $(date -u)"
EOS
