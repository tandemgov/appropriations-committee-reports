#!/usr/bin/env bash
# Unattended Gemini-cleanup supervisor (the final leg).
#
# For every report that has a Nemotron pass but no hybrid canonical output, runs the
# Gemini cleanup (run_corpus --reuse-nemotron, gemini-2.5-pro) which re-extracts only
# the suspect pages. Handles the per-model-per-day Gemini cap: when exhausted, the
# hybrid aborts the report WITHOUT writing a degraded file (PerDayQuotaError), and this
# supervisor sleeps until the quota resets, then resumes. Non-quota failures are
# recorded to cleanup_skip.txt and skipped.
#
# Launch detached:
#   caffeinate -i nohup bash scripts/cleanup_supervisor.sh \
#       >> data/output/logs/cleanup.log 2>&1 & disown

set -u
cd "$(dirname "$0")/.."
LOG=data/output/logs/cleanup.log
SKIP=data/output/logs/cleanup_skip.txt
export VISION_MODEL=gemini-2.5-pro   # 3.x-preview daily-capped; 2.5-pro has its own quota
SLEEP_QUOTA=2400                     # 40 min between retries when the daily cap is hit
touch "$SKIP"

log() { echo "[cleanup $(date '+%m-%d %H:%M:%S')] $*"; }

next_report() {
  uv run python - <<'PY'
import os, glob, json, sys; sys.path.insert(0,'src')
from approps.config import EXTRACTED_DIR
skip=set(open('data/output/logs/cleanup_skip.txt').read().split())
for nemo in sorted(glob.glob(str(EXTRACTED_DIR/'1*/house/*_nemotron.json'))):
    rid=os.path.basename(nemo).replace('_nemotron.json','')
    if rid in skip: continue
    canon=nemo.replace('_nemotron.json','.json')
    if os.path.exists(canon):
        try:
            if 'hybrid' in (json.load(open(canon)).get('vision_model') or ''): continue
        except Exception: pass
    print(rid); break
PY
}

is_hybrid() { python3 -c "import json,sys; print('hybrid' in (json.load(open(sys.argv[1])).get('vision_model') or ''))" "$1" 2>/dev/null | grep -q True; }

total=0
while true; do
  rid=$(next_report)
  [ -z "$rid" ] && { log "no reports need cleanup — ALL DONE ($total cleaned this run)"; break; }

  log "cleaning $rid"
  # Per-report timeout so a hung Gemini call can't block the whole loop overnight.
  tmp=$(mktemp)
  uv run python scripts/run_corpus.py "$rid" --reuse-nemotron > "$tmp" 2>&1 &
  pid=$!; waited=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 30; waited=$((waited+30))
    if [ "$waited" -gt 1800 ]; then  # 30 min cap per report
      log "$rid exceeded 30m — killing + skipping"
      kill "$pid" 2>/dev/null; pkill -P "$pid" 2>/dev/null
      echo "$rid" >> "$SKIP"; break
    fi
  done
  wait "$pid" 2>/dev/null
  out=$(cat "$tmp"); rm -f "$tmp"
  echo "$out" | grep -vE "HTTP Request|httpx|AFC is enabled" >> "$LOG"

  canon=$(find data/extracted -path "*/house/$rid.json" 2>/dev/null | head -1)
  if [ -n "$canon" ] && is_hybrid "$canon"; then
    total=$((total+1)); log "$rid OK ($total done)"
  elif echo "$out" | grep -qiE "per_day|PerDayQuota|requests_per_model_per_day"; then
    log "Gemini DAILY QUOTA exhausted — sleeping ${SLEEP_QUOTA}s, will resume $rid"
    sleep "$SLEEP_QUOTA"
  else
    log "$rid FAILED (non-quota) — adding to skip list"
    echo "$rid" >> "$SKIP"
  fi
done
log "exiting"
