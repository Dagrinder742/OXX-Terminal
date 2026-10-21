#!/usr/bin/env bash
# Runs the agent N times on prompt_v4.txt and judges each result with verify_skill.py.
# Usage:  bash run10.sh [N]          (default 10)
# Appends all run outputs and notes to a single master log file.
set -u

# ---- UNIVERSAL PATH RESOLUTION ----
KIT="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$KIT/.." && pwd)"

TOOLS="${TOOLS:-$REPO_ROOT/app/src/main/Python/tools}"
if [ ! -d "$TOOLS" ]; then
  if [ -d "$KIT/tools" ]; then
    TOOLS="$KIT/tools"
  elif [ -d "$REPO_ROOT/tools" ]; then
    TOOLS="$REPO_ROOT/tools"
  fi
fi

if command -v python3 &>/dev/null; then
  DEFAULT_PY="python3"
else
  DEFAULT_PY="python"
fi
PY="${PY:-$DEFAULT_PY}"
N="${1:-10}"

# ---- SINGLE STATIC LOG DIRECTORY & MASTER FILE ----
LOGS="$KIT/logs"
MASTER_LOG="$LOGS/master_run_history.txt"
SUMMARY="$LOGS/summary.txt"
export SANDBOX_DIR="$TOOLS"

# ---- PREFLIGHT CHECKS ----
find_file() {
  for d in "$KIT" "$TOOLS"; do [ -f "$d/$1" ] && { echo "$d/$1"; return 0; }; done
  return 1
}

PROMPT_FILE="$(find_file prompt_v4.txt)"   || { echo "STOP: prompt_v4.txt not found. Nothing was run."; exit 2; }
VERIFY_FILE="$(find_file verify_skill.py)" || { echo "STOP: verify_skill.py not found. Nothing was run."; exit 2; }
[ -f "$TOOLS/sandbox_tool.py" ]            || { echo "STOP: sandbox_tool.py not found at $TOOLS."; exit 2; }

PROMPT="$(cat "$PROMPT_FILE")"
[ -n "$PROMPT" ]                           || { echo "STOP: $PROMPT_FILE is empty."; exit 2; }

mkdir -p "$LOGS"

# Timestamp for this specific batch execution
BATCH_TIME="$(date '+%Y-%m-%d %H:%M:%S')"

echo "================================================================================" >> "$MASTER_LOG"
echo "                       NEW BATCH RUN: $BATCH_TIME (N=$N)" >> "$MASTER_LOG"
echo "================================================================================" >> "$MASTER_LOG"

echo "prompt:   $PROMPT_FILE ($(printf %s "$PROMPT" | wc -c) chars)"
echo "verifier: $VERIFY_FILE"
echo "sandbox:  $TOOLS"
echo "master log: $MASTER_LOG"

# Reset summary for this specific run batch view
printf '%-4s %-8s %-7s %-10s %-9s %s\n' run verify steps run_python said_done note > "$SUMMARY"

pass=0; liar=0
for i in $(seq 1 "$N"); do
  rm -f "$TOOLS/skill.py"
  
  # Temporary local execution logs for processing
  RUN_LOG="$LOGS/temp_run_$i.log"
  VERIFY_LOG="$LOGS/temp_verify_$i.log"
  
  ( cd "$TOOLS" && "$PY" sandbox_tool.py --agent "$PROMPT" ) > "$RUN_LOG" 2>&1
  ( cd "$TOOLS" && "$PY" "$VERIFY_FILE" skill.py ) > "$VERIFY_LOG" 2>&1
  
  # Save a copy of the generated skill file for reference
  SKILL_COPY="$LOGS/last_skill_$i.py"
  cp "$TOOLS/skill.py" "$SKILL_COPY" 2>/dev/null
  
  if tail -n 1 "$VERIFY_LOG" | grep -q "VERIFY: PASS"; then v=PASS; pass=$((pass+1)); else v=FAIL; fi
  steps=$(grep -c '^model>' "$RUN_LOG")
  rp=$(grep -c 'CMD: run_python' "$RUN_LOG")
  
  if grep -q '^final>' "$RUN_LOG"; then said=no
  elif grep -q 'DONE:' "$RUN_LOG"; then said=yes; else said=no; fi
  
  note=""
  if [ ! -f "$SKILL_COPY" ]; then
    note="no skill.py was written"
  elif [ "$v" = FAIL ] && [ "$said" = yes ]; then
    note="CLAIMED DONE BUT FAILED"; liar=$((liar+1))
  fi
  grep -q '^final>' "$RUN_LOG" && note="$note stopped: $(grep '^final>' "$RUN_LOG" | head -1 | cut -c8-60)"
  
  # Print to terminal summary
  printf '%-4s %-8s %-7s %-10s %-9s %s\n' "$i" "$v" "$steps" "$rp" "$said" "$note" | tee -a "$SUMMARY"

  # ---- APPEND THIS RUN DIRECTLY TO THE SINGLE MASTER LOG FILE ----
  {
    echo ""
    echo "--------------------------------------------------------------------------------"
    echo " RUN $i / $N  [Result: $v]  -  Batch: $BATCH_TIME"
    echo "--------------------------------------------------------------------------------"
    echo "--- [ VERIFICATION OUTPUT ] ---"
    cat "$VERIFY_LOG" 2>/dev/null
    echo ""
    echo "--- [ GENERATED CODE (skill.py) ] ---"
    if [ -f "$SKILL_COPY" ]; then
      cat "$SKILL_COPY"
    else
      echo "(No skill.py was generated)"
    fi
    echo ""
    echo "--- [ RUN LOG / INTERACTION HISTORY ] ---"
    cat "$RUN_LOG" 2>/dev/null
    echo ""
    echo "--- [ HUMAN AUDIT / NOTES ] ---"
    echo "Notes: "
    echo ""
  } >> "$MASTER_LOG"

  # Clean up temporary run-specific files to keep directory pristine
  rm -f "$RUN_LOG" "$VERIFY_LOG"
done

echo "--------------------------------------------------------------------------------" >> "$MASTER_LOG"
echo "SUMMARY -> verified PASS: $pass / $N     claimed DONE but verify FAILED: $liar" >> "$MASTER_LOG"
echo "================================================================================" >> "$MASTER_LOG"
echo "" >> "$MASTER_LOG"

echo "---"
echo "verified PASS: $pass / $N     claimed DONE but verify FAILED: $liar"
echo "All results successfully appended to: $MASTER_LOG"

