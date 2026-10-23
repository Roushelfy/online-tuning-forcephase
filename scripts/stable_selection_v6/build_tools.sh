#!/usr/bin/env bash
# Build the goal-v6 tools (run inside the gs-srun container):
#   build/tools/obsprofile6   (tools/obsprofile6.c)
#   $FP_DATA/v6_tools/satzilla/src/features   (official SATzilla 2024 extractor,
#       commit 6209d485108381ecb403c5af8aa7134645bae7fb, rebuilt from source)
# Writes build/tools/BUILDINFO_v6.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FP_DATA="${FP_DATA:-/mnt/data/zhaofeng/projects/workspace/online-tuning-forcephase}"
OUT="$ROOT/build/tools"
SZ="$FP_DATA/v6_tools/satzilla"
mkdir -p "$OUT"
CC="${CC:-gcc}"
$CC -O2 -Wall -static -o "$OUT/obsprofile6" "$ROOT/tools/obsprofile6.c" -lm
if [ "${BUILD_SATZILLA:-0}" = 1 ]; then
  (cd "$SZ/src" && (make clean-all > /dev/null 2>&1 || true) && rm -f features && make feature > "$FP_DATA/v6_tools/satzilla_build.log" 2>&1)
fi
{
  echo "cc=$($CC --version | head -1)"
  echo "obsprofile6_sha256=$(sha256sum "$OUT/obsprofile6" | cut -d' ' -f1)"
  echo "obsprofile6_source_sha256=$(sha256sum "$ROOT/tools/obsprofile6.c" | cut -d' ' -f1)"
  echo "satzilla_commit=$(git -C "$SZ" rev-parse HEAD)"
  echo "satzilla_features_sha256=$(sha256sum "$SZ/src/features" | cut -d' ' -f1)"
  echo "satzilla_build=make clean-all; make feature (src/), $(grep -c '' "$FP_DATA/v6_tools/satzilla_build.log") log lines"
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT/BUILDINFO_v6"
cat "$OUT/BUILDINFO_v6"
