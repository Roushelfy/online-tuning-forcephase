#!/usr/bin/env bash
# Build the week tools inside the gs-srun container (static binaries):
#   libarchive 3.7.7 (static, xz/gzip/bzip2 only) -> native_linear42 (8 s) and native_linear42_cpu16 (16 s retry)
#   cnf_unit_unique
# Usage: tools/build_week_tools.sh OUT_DIR
set -euo pipefail
OUT="$1"; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; mkdir -p "$OUT"; cd "$OUT"
LA=libarchive-3.7.7
if [ ! -f "$OUT/la/lib/libarchive.a" ]; then
  curl -fsSL -o $LA.tar.xz https://github.com/libarchive/libarchive/releases/download/v3.7.7/$LA.tar.xz
  sha256sum $LA.tar.xz > $LA.tar.xz.sha256; rm -rf $LA; tar -xf $LA.tar.xz
  (cd $LA && ./configure --prefix="$OUT/la" --disable-shared --enable-static --disable-bsdtar --disable-bsdcpio \
     --disable-bsdcat --disable-bsdunzip --disable-acl --disable-xattr --without-openssl --without-xml2 --without-expat \
     --without-libb2 --without-lz4 --without-zstd --without-nettle --without-mbedtls --without-iconv --with-lzma \
     --with-zlib --with-bz2lib > "$OUT/libarchive.configure.log" 2>&1 && make -j8 > "$OUT/libarchive.make.log" 2>&1 && make install >> "$OUT/libarchive.make.log" 2>&1)
fi
V="$HERE/third_party_mu/vendor_gbdc_base_9f3a418"
build42 () {  # $1 output name, $2 sed expression applied to a temporary copy (empty = unchanged source)
  cp "$HERE/third_party_mu/native_linear42.cpp" "$OUT/$1.cpp"; [ -n "$2" ] && sed -i "$2" "$OUT/$1.cpp"
  g++ -O2 -std=c++17 -static -I"$V" -I"$OUT/la/include" "$OUT/$1.cpp" "$V/src/util/CaptureDistribution.cc" \
      -L"$OUT/la/lib" -larchive -llzma -lbz2 -lz -o "$OUT/$1"
}
build42 native_linear42 ""
build42 native_linear42_cpu16 's/cpu{8,8}/cpu{16,16}/; s/alarm(12)/alarm(24)/'
grep -c 'cpu{16,16}' "$OUT/native_linear42_cpu16.cpp" | grep -q 1
gcc -O2 -static -o "$OUT/cnf_unit_unique" "$HERE/tools/cnf_unit_unique.c"
{ echo "host=$(hostname)"; echo "cxx=$(g++ --version | head -1)"; cat $LA.tar.xz.sha256 2>/dev/null;
  for b in native_linear42 native_linear42_cpu16 cnf_unit_unique; do echo "$b=$(sha256sum "$OUT/$b" | cut -d' ' -f1)"; done
  echo "native_source_sha256=$(sha256sum "$HERE/third_party_mu/native_linear42.cpp" | cut -d' ' -f1)"; } > "$OUT/BUILDINFO"
cat "$OUT/BUILDINFO"
