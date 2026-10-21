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
export SANDBOX_DIR="$TOOLS"

# ---- preflight: never run the agent on a missing/empty prompt (that produces fake FAILs) ----
find_file() {   # look next to this script first, then in the sandbox folder
  for d in "$KIT" "$TOOLS"; do [ -f "$d/$1" ] && { echo "$d/$1"; return 0; }; done
  return 1
}
PROMPT_FILE="$(find_file prompt_v4.txt)"   || { echo "STOP: prompt_v4.txt not found in $KIT or $TOOLS. Nothing was run."; exit 2; }
VERIFY_FILE="$(find_file verify_skill.py)" || { echo "STOP: verify_skill.py not found in $KIT or $TOOLS. Nothing was run."; exit 2; }
[ -f "$TOOLS/sandbox_tool.py" ]            || { echo "STOP: $TOOLS/sandbox_tool.py not found (set TOOLS=...). Nothing was run."; exit 2; }
PROMPT="$(cat "$PROMPT_FILE")"
[ -n "$PROMPT" ]                           || { echo "STOP: $PROMPT_FILE is empty. Nothing was run."; exit 2; }
echo "prompt:   $PROMPT_FILE ($(printf %s "$PROMPT" | wc -c) chars)"
echo "verifier: $VERIFY_FILE"
echo "sandbox:  $TOOLS"
mkdir -p "$LOGS"
SUMMARY="$LOGS/summary.txt"
printf '%-4s %-8s %-7s %-10s %-9s %s\n' run verify steps run_python said_done note > "$SUMMARY"
pass=0; liar=0
for i in $(seq 1 "$N"); do
  rm -f "$TOOLS/skill.py"
  ( cd "$TOOLS" && "$PY" sandbox_tool.py --agent "$PROMPT" ) > "$LOGS/run_$i.log" 2>&1
  ( cd "$TOOLS" && "$PY" "$VERIFY_FILE" skill.py ) > "$LOGS/verify_$i.log" 2>&1
  cp "$TOOLS/skill.py" "$LOGS/skill_$i.py" 2>/dev/null
  if tail -n 1 "$LOGS/verify_$i.log" | grep -q "VERIFY: PASS"; then v=PASS; pass=$((pass+1)); else v=FAIL; fi
  steps=$(grep -c '^model>' "$LOGS/run_$i.log")
  rp=$(grep -c 'CMD: run_python' "$LOGS/run_$i.log")
  # "said_done" = the run ENDED because the tool accepted a DONE. A DONE the model merely wrote
  # inside a longer reply (invented steps) while the run was later stopped does not count.
  if grep -q '^final>' "$LOGS/run_$i.log"; then said=no
  elif grep -q 'DONE:' "$LOGS/run_$i.log"; then said=yes; else said=no; fi
  note=""
  if [ ! -f "$LOGS/skill_$i.py" ]; then
    note="no skill.py was written"
  elif [ "$v" = FAIL ] && [ "$said" = yes ]; then
    note="CLAIMED DONE BUT FAILED"; liar=$((liar+1))
  fi
  grep -q '^final>' "$LOGS/run_$i.log" && note="$note stopped: $(grep '^final>' "$LOGS/run_$i.log" | head -1 | cut -c8-60)"
  printf '%-4s %-8s %-7s %-10s %-9s %s\n' "$i" "$v" "$steps" "$rp" "$said" "$note" | tee -a "$SUMMARY"
done
echo "---" | tee -a "$SUMMARY"
echo "verified PASS: $pass / $N     claimed DONE but verify FAILED: $liar" | tee -a "$SUMMARY"
echo "logs: $LOGS  (paste summary.txt, and any run_N.log / verify_N.log you want me to read)"
