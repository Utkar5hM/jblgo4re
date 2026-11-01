#!/usr/bin/env bash
# Instant lookups over captures/index (built by tools/build_index.sh). Searches both images.
#   q.sh fn 0x8e128          decompiled C of the function containing/at addr (main+stage0 hits)
#   q.sh asm 0x8e128         disassembly of that function
#   q.sh callers 0x4fdc4     call sites of a function
#   q.sh callees 0x4fdc4
#   q.sh val 0x20000538      every instruction using that value (immediate or literal pool)
#   q.sh str 'HMDev'         strings (Ghidra-defined + raw) matching regex
#   q.sh grep 'regex'        grep all decompiled C, print function:line
set -uo pipefail
IDX="$(cd "$(dirname "$0")/.." && pwd)/captures/index"
op="${1:?op}"; arg="${2:?arg}"
norm() { printf '0x%08x' "$(( $1 ))"; }
containing() { # print "<img> <entry>" for functions whose range covers addr
  python3 - "$IDX" "$1" <<'PY'
import sys, csv
idx, a = sys.argv[1], int(sys.argv[2], 0)
for img in ("main", "stage0"):
    for r in csv.DictReader(open(f"{idx}/{img}/functions.tsv"), delimiter="\t"):
        e = int(r["entry"], 16)
        if e <= a < e + int(r["size"]): print(img, r["entry"])
PY
}
case "$op" in
  fn|asm)
    ext=$([ "$op" = fn ] && echo c || echo s); dir=$([ "$op" = fn ] && echo decomp || echo asm)
    containing "$arg" | while read -r img e; do echo "=== [$img] $e"; cat "$IDX/$img/$dir/$e.$ext"; done ;;
  callers) a=$(norm "$arg"); for img in main stage0; do awk -F'\t' -v a="$a" -v i="$img" '$3==a{print "["i"] "$1" @ "$2}' "$IDX/$img/calls.tsv"; done ;;
  callees) a=$(norm "$arg"); for img in main stage0; do awk -F'\t' -v a="$a" -v i="$img" '$1==a{print "["i"] "$2" -> "$3}' "$IDX/$img/calls.tsv"; done ;;
  val) v=$(printf '0x%x' "$(( arg ))"); for img in main stage0; do awk -F'\t' -v v="$v" -v i="$img" '$3==v{print "["i"] func "$1" insn "$2" "$4}' "$IDX/$img/consts.tsv"; done ;;
  str) for img in main stage0; do grep -E -- "$arg" "$IDX/$img/strings.tsv" | sed "s/^/[$img] /"; grep -E -- "$arg" "$IDX/$img/raw_strings.txt" | sed "s/^/[$img raw] /"; done | sort -u ;;
  grep) for img in main stage0; do grep -rnE -- "$arg" "$IDX/$img/decomp" | sed "s#$IDX/$img/decomp/#[$img] #"; done ;;
  *) echo "unknown op $op" >&2; exit 2 ;;
esac
