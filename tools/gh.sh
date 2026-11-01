#!/usr/bin/env bash
# Headless Ghidra wrapper. Read-only against the analyzed 0.6.4.0 projects.
#   tools/gh.sh main   DumpFunctions.java 0x8e128 0x8deb4
#   tools/gh.sh stage0 ReportXrefs.java 0x4fdc4
# Prefer grepping captures/index/ first; use this only for things the index lacks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "${1:?main|stage0}" in
  main)   PROJ=go4_main_0640;   BIN=main_00000.bin ;;
  stage0) PROJ=go4_stage0_0640; BIN=stage0_40000.bin ;;
  *) echo "unknown target $1" >&2; exit 2 ;;
esac
shift
SCRIPT="${1:?script name}"; shift
export JAVA_HOME="$ROOT/.toolchain/jdk" PATH="$ROOT/.toolchain/jdk/bin:$PATH"
export MAXMEM="${MAXMEM:-3G}"
exec "$ROOT/.toolchain/ghidra_12.2_PUBLIC/support/analyzeHeadless" \
  "$ROOT/captures/ghidra" "$PROJ" -process "$BIN" -noanalysis -readOnly \
  -scriptPath "$ROOT/tools/ghidra" -postScript "$SCRIPT" "$@" 2>&1 \
  | grep -v -E '^(INFO|WARN) .*(Ghidra|Headless|Opening|Using|Searching|REPORT|class|Loading|Packed|Starting|Analyz|script|Updating)' 
