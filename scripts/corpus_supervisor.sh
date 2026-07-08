#!/usr/bin/env bash
# Unattended overnight supervisor for the Nemotron bulk pass.
#
# Runs run_corpus over the remaining House reports (congresses 114-116), and:
#   - restarts if the run dies or the Nemotron server flaps,
#   - detects stalls (log not advancing for STALL_SECS) and auto-quarantines the
#     offending report (these hangs are reliably reproducible — e.g. large THUD
#     reports wedge the server ~page 400), then restarts skipping it,
#   - waits and retries if the server is unreachable,
#   - terminates cleanly when nothing extractable remains.
#
# Launch detached so it survives a disconnect:
#   caffeinate -i nohup bash scripts/corpus_supervisor.sh \
#       >> data/output/logs/supervisor.log 2>&1 & disown

set -u
cd "$(dirname "$0")/.."
LOG=data/output/logs/corpus_bulk.log
QUAR=data/output/logs/quarantine.txt
STALL_SECS=900   # 15 min with no log write => stalled
POLL=60
touch "$QUAR"

log() { echo "[supervisor $(date '+%H:%M:%S')] $*"; }

remaining() {
  uv run python - <<'PY'
import sys; sys.path.insert(0,'src')
from pathlib import Path
from approps.discovery.report_catalog import load_catalog
from approps.config import EXTRACTED_DIR
QUAR=set(open('data/output/logs/quarantine.txt').read().split())
ids=[r.package_id for r in load_catalog()
     if getattr(r.chamber,'value',r.chamber)=='house' and r.package_id.startswith('CRPT')
     and r.congress in (114,115,116) and r.package_id not in QUAR
     and not (EXTRACTED_DIR/str(r.congress)/'house'/f'{r.package_id}_nemotron.json').exists()]
print(" ".join(ids))
PY
}

NEMOTRON_BASE_URL="${NEMOTRON_BASE_URL:-http://localhost:8000/v1}"
NEMOTRON_HEALTH="${NEMOTRON_BASE_URL%/v1}/health"
server_up() { curl -s --max-time 8 -o /dev/null -w "%{http_code}" "$NEMOTRON_HEALTH" 2>/dev/null | grep -q 200; }

while true; do
  ids=$(remaining); n=$(echo $ids | wc -w | tr -d ' ')
  if [ "$n" -eq 0 ]; then log "nothing remaining — DONE"; echo "===== SUPERVISOR DONE ($(date)) =====" >> "$LOG"; break; fi

  if ! server_up; then log "server down, sleeping 300s"; sleep 300; continue; fi

  log "starting run over $n reports"
  uv run python scripts/run_corpus.py $ids --nemotron-only --skip-existing >> "$LOG" 2>&1 &
  pid=$!
  killed=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep "$POLL"
    mt=$(stat -f %m "$LOG" 2>/dev/null || echo 0); age=$(( $(date +%s) - mt ))
    if [ "$age" -gt "$STALL_SECS" ]; then
      cur=$(grep -oE 'CRPT-[0-9a-z]+' "$LOG" | tail -1)
      log "STALL ($age s) on $cur — auto-quarantining + restarting"
      [ -n "$cur" ] && echo "$cur" >> "$QUAR"
      kill "$pid" 2>/dev/null; pkill -P "$pid" 2>/dev/null
      killed=1; break
    fi
  done
  wait "$pid" 2>/dev/null
  [ "$killed" -eq 1 ] && continue

  # Clean exit: if no progress was made, the rest are unprocessable — quarantine + stop.
  ids2=$(remaining); n2=$(echo $ids2 | wc -w | tr -d ' ')
  if [ "$n2" -ge "$n" ]; then
    log "clean exit but no progress ($n2 left) — quarantining unprocessable + stopping"
    for x in $ids2; do echo "$x" >> "$QUAR"; done
    echo "===== SUPERVISOR DONE / $n2 UNPROCESSABLE ($(date)) =====" >> "$LOG"
    break
  fi
  log "progress made ($n -> $n2), continuing"
done
log "exiting"
