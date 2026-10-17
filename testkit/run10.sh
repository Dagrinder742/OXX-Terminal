#!/usr/bin/env bash
# Runs the agent N times on prompt_v4.txt and judges each result with verify_skill.py.
# Usage:  bash run10.sh [N]          (default 10)
# Env:    TOOLS=<sandbox folder>     default ~/OKX-Terminal/tools
#         PY=<python command>        default python
# Logs go to ./logs next to this script (outside the sandbox, so the model cannot see them).
set -u
KIT="$(cd "$(dirname "$0")" && pwd)"
TOOLS="${TOOLS:-$HOME/OKX-Terminal/tools}"
PY="${PY:-python}"
N="${1:-10}"
LOGS="$KIT/logs"
mkdir -p "$LOGS"
export SANDBOX_DIR="$TOOLS"
PROMPT="$(cat "$KIT/prompt_v4.txt")"
SUMMARY="$LOGS/summary.txt"
printf '%-4s %-8s %-7s %-10s %-9s %s\n' run verify steps run_python said_done note > "$SUMMARY"
pass=0; liar=0
for i in $(seq 1 "$N"); do
  rm -f "$TOOLS/skill.py"
  ( cd "$TOOLS" && "$PY" sandbox_tool.py --agent "$PROMPT" ) > "$LOGS/run_$i.log" 2>&1
  ( cd "$TOOLS" && "$PY" "$KIT/verify_skill.py" skill.py ) > "$LOGS/verify_$i.log" 2>&1
  cp "$TOOLS/skill.py" "$LOGS/skill_$i.py" 2>/dev/null
  if tail -n 1 "$LOGS/verify_$i.log" | grep -q "VERIFY: PASS"; then v=PASS; pass=$((pass+1)); else v=FAIL; fi
  steps=$(grep -c '^model>' "$LOGS/run_$i.log")
  rp=$(grep -c 'CMD: run_python' "$LOGS/run_$i.log")
  if grep -q 'DONE:' "$LOGS/run_$i.log"; then said=yes; else said=no; fi
  note=""
  [ "$v" = FAIL ] && [ "$said" = yes ] && { note="CLAIMED DONE BUT FAILED"; liar=$((liar+1)); }
  grep -q '^final>' "$LOGS/run_$i.log" && note="$note stopped: $(grep '^final>' "$LOGS/run_$i.log" | head -1 | cut -c8-60)"
  printf '%-4s %-8s %-7s %-10s %-9s %s\n' "$i" "$v" "$steps" "$rp" "$said" "$note" | tee -a "$SUMMARY"
done
echo "---" | tee -a "$SUMMARY"
echo "verified PASS: $pass / $N     claimed DONE but verify FAILED: $liar" | tee -a "$SUMMARY"
echo "logs: $LOGS  (paste summary.txt, and any run_N.log / verify_N.log you want me to read)"
