#!/usr/bin/env bash
# Rebuild captures/index/{main,stage0} from the analyzed Ghidra projects (~minutes, run once).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for t in "${@:-main stage0}"; do for x in $t; do
  rm -rf "$ROOT/captures/index/$x"; mkdir -p "$ROOT/captures/index/$x"
  "$ROOT/tools/gh.sh" "$x" ExportIndex.java "$ROOT/captures/index/$x" > "$ROOT/captures/index/$x.log" 2>&1 &
done; done
wait
strings -a -t x -n 4 "$ROOT/captures/firmware0640/main_00000.bin" > "$ROOT/captures/index/main/raw_strings.txt"
strings -a -t x -n 4 "$ROOT/captures/firmware0640/stage0_40000.bin" | python3 "$ROOT/tools/rebase_strings.py" 0x40000 > "$ROOT/captures/index/stage0/raw_strings.txt"
tail -n 3 "$ROOT"/captures/index/*.log
