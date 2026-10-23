#!/usr/bin/env bash
# Run one v7 long-run stage on one exclusive cpu-low node (gs-srun container).
#   scripts/completion_v7/slurm_longrun.sh <plan.json> <stage> <budget-cpu-hours> [time=24:00:00]
# Logs: $FP_DATA/logs/slurm/v7-<stage>-<jobid>.{out,err}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLAN="$1"; STAGE="$2"; BUDGET="$3"; TIME="${4:-24:00:00}"
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
mkdir -p "$FP_DATA/logs/slurm"
sbatch --parsable --job-name="v7-$STAGE" --partition=cpu-low --nodes=1 --ntasks=1 --exclusive --mem=0 --time="$TIME" \
  --output="$FP_DATA/logs/slurm/v7-$STAGE-%j.out" --error="$FP_DATA/logs/slurm/v7-$STAGE-%j.err" \
  --export=ALL,FP_DATA="$FP_DATA",V7_ROOT="$ROOT",V7_PLAN="$PLAN",V7_STAGE="$STAGE",V7_BUDGET="$BUDGET" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "v7 $V7_STAGE on $(hostname) at $(date -u)"
gs-srun --ntasks=1 --cpus-per-task="$SLURM_CPUS_ON_NODE" \
  bash -c "cd '$V7_ROOT' && FP_DATA='$FP_DATA' FP_LOCAL=/tmp/fp_local_\$USER python3 scripts/completion_v7/longrun.py --plan '$V7_PLAN' --stage '$V7_STAGE' --budget-cpu-hours '$V7_BUDGET'"
echo "finished at $(date -u)"
EOS
