#!/usr/bin/env bash
# Build the 'anni' CaDiCaL variant: pinned upstream c607304 + solver_patches/cadical-anni.patch, ./configure -static.
# The patch adds two options and changes no search decision:
#   --flargest=1    force each variable to its majority literal sign in the original CNF (ties positive)
#   --anniprobe=MS  print a 'c anni tick ...' telemetry line every MS ms of process time (checked every 32
#                   conflicts) and a 'c anni final ...' line whenever statistics are printed
# Run inside the gs-srun container.  Usage: tools/build_cadical_anni.sh CADICAL_GIT_DIR OUT_DIR
set -euo pipefail
SRC_GIT="$1"; OUT="$2"; PIN=c60730422e758ef1cebe7aeddf2dda31c996bf04
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; PATCH="$HERE/solver_patches/cadical-anni.patch"
rm -rf "$OUT/src"; mkdir -p "$OUT/src"
git -C "$SRC_GIT" archive "$PIN" | tar -x -C "$OUT/src"
(cd "$OUT/src" && patch -p1 --quiet --forward < "$PATCH")
(cd "$OUT/src" && ./configure -static > "$OUT/configure.log" 2>&1 && make -j"${JOBS:-8}" > "$OUT/make.log" 2>&1) || { tail -30 "$OUT/make.log"; exit 1; }
cp "$OUT/src/build/cadical" "$OUT/cadical"
{ echo "variant=anni"; echo "cadical_sha=$PIN"; echo "patch_sha256=$(sha256sum "$PATCH" | cut -d' ' -f1)";
  echo "configure=-static"; echo "cxx=$(g++ --version | head -1)"; echo "host=$(hostname)";
  echo "binary_sha256=$(sha256sum "$OUT/cadical" | cut -d' ' -f1)"; echo "built_at=$(date -u +%FT%TZ)"; } > "$OUT/BUILDINFO"
cat "$OUT/BUILDINFO"
