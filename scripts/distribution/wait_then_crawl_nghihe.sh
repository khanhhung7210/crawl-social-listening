#!/usr/bin/env bash
# Wait for Quý Tử Vượt Giàu crawls to finish, then run Nghỉ Hè Sợ Nghỉ Hưu (all platforms).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
export PYTHONPATH=src
export SOCIAL_CONFIG_SOURCE=db
export CHROMEDRIVER_PATH="$ROOT/runtime/bin/chromedriver"
LOG="$ROOT/runtime/logs/dis-crawl-next-nghihe.log"
PARALLEL_DIR="$ROOT/runtime/logs/dis-mxh-parallel"
mkdir -p "$PARALLEL_DIR" "$(dirname "$LOG")"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

quy_running() {
  pgrep -fl "run_distribution_pipeline.py.*quy_tu_vuot_giau" >/dev/null 2>&1 && return 0
  pgrep -fl "run_full_pipeline.py" >/dev/null 2>&1 && return 0
  return 1
}

log "Waiting for Quý Tử Vượt Giàu crawls to finish..."
while quy_running; do
  sleep 60
  log "  still running: $(pgrep -fl 'quy_tu_vuot_giau' 2>/dev/null | wc -l | tr -d ' ') process(es)"
done
log "Quý Tử Vượt Giàu done — import + metrics"
"$PY" -u scripts/distribution/import_film_mentions.py --film quy_tu_vuot_giau >>"$LOG" 2>&1 || true
"$PY" -u scripts/distribution/classify/classify_mention_intent.py --film-slug quy_tu_vuot_giau --reclassify >>"$LOG" 2>&1 || true

FILM="nghi_he_so_nghi_huu"
PLATFORMS=(youtube tiktok facebook instagram threads)

log "========== START $FILM (Nghỉ Hè Sợ Nghỉ Hưu) — parallel platforms =========="
pids=()
for plat in "${PLATFORMS[@]}"; do
  out="$PARALLEL_DIR/${FILM}__${plat}.log"
  log "START $FILM / $plat → $out"
  "$PY" -u scripts/distribution/run_distribution_pipeline.py \
    --film "$FILM" --platform "$plat" --import-db --continue-on-error --skip-seed \
    >"$out" 2>&1 &
  pids+=($!)
done

fail=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then fail=1; fi
done
log "film=$FILM platforms done (fail_flag=$fail)"

log "import + classify + metrics for $FILM"
"$PY" -u scripts/distribution/import_film_mentions.py --film "$FILM" >>"$LOG" 2>&1 || true
"$PY" -u scripts/distribution/classify/classify_mention_intent.py --film-slug "$FILM" --reclassify >>"$LOG" 2>&1 || true
"$PY" -u scripts/distribution/metrics/recompute_daily_film_metrics.py >>"$LOG" 2>&1 || true

log "=== ALL DONE ==="
