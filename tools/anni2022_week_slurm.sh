#!/usr/bin/env bash
# Submit N shard jobs of tools/anni2022_week_runner.py (cpu-mid, 20 logical CPUs = 10 cores, 8 solver tokens, --no-requeue).
#   tools/anni2022_week_slurm.sh NAME TASKS.jsonl OUT_ROOT N [MEM=200G] [TIME=2-00:00:00] [INDICES...]
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="$1"; TASKS="$2"; OUT="$3"; N="$4"; MEM="${5:-200G}"; TIME="${6:-2-00:00:00}"; shift 6 2>/dev/null || shift $#
DATA=/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase/anni2022_baseline
mkdir -p "$OUT/logs"
IDX=("$@"); [ ${#IDX[@]} -eq 0 ] && IDX=($(seq 0 $((N-1))))
for i in "${IDX[@]}"; do
  sbatch --parsable --no-requeue --job-name="$NAME-$(printf %03d "$i")" --partition=cpu-mid --nodes=1 --ntasks=1 \
    --cpus-per-task=20 --mem="$MEM" --time="$TIME" --array=0-0 \
    --output="$OUT/logs/shard-$(printf %03d "$i")-%A_%a.out" --error="$OUT/logs/shard-$(printf %03d "$i")-%A_%a.err" \
    --export=ALL,ANNI_CMD="cd '$SRC' && python3 tools/anni2022_week_runner.py --tasks '$TASKS' --out '$OUT' --cnf-dir '$DATA/cnf_xz' --receipts '$DATA/cluster_v3' --shard $i/$N" <<'EOS'
#!/usr/bin/env bash
source /mnt/data/shared/config/env.sh
export GENESIS_IMAGE_VER="${GENESIS_IMAGE_VER:-1_26}"
echo "start $(hostname) $(date -u)"
gs-srun --ntasks=1 --cpus-per-task="$SLURM_CPUS_PER_TASK" bash -c "$ANNI_CMD"
echo "finished $(date -u) exit $?"
EOS
done
