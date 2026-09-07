#!/usr/bin/env bash
# Crawl thêm WAIT_HOURS, dừng hết crawler, format/filter raw đã có, import DB.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
LOG="$ROOT/runtime/logs/crawl_3h_then_import.log"
PIDFILE="$ROOT/runtime/logs/crawl_3h_then_import.pid"

# Self-daemonize so process survives terminal close.
if [ "${1:-}" != "--daemon" ]; then
  mkdir -p "$(dirname "$LOG")"
  nohup "$0" --daemon >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  echo "Scheduler PID $(cat "$PIDFILE") — log: $LOG"
  exit 0
fi
shift || true
PY="$ROOT/.venv/bin/python"
export PYTHONPATH=src
export SOCIAL_CONFIG_SOURCE=db
export CHROMEDRIVER_PATH="$ROOT/runtime/bin/chromedriver"

WAIT_HOURS="${WAIT_HOURS:-3}"
WAIT_SEC=$((WAIT_HOURS * 3600))
FILMS=(quy_tu_vuot_giau nghi_he_so_nghi_huu)
PLATFORMS=(facebook tiktok threads instagram youtube)
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

stop_crawlers() {
  log "Stopping all crawlers…"
  pkill -f run_continuous_supervisor 2>/dev/null || true
  pkill -f run_continuous_distribution 2>/dev/null || true
  pkill -f run_distribution_pipeline 2>/dev/null || true
  pkill -f run_full_pipeline 2>/dev/null || true
  pkill -f facebook_raw_runner 2>/dev/null || true
  pkill -f threads_crawl_runner 2>/dev/null || true
  pkill -f threads_replies_runner 2>/dev/null || true
  pkill -f threads_search_filter 2>/dev/null || true
  pkill -f tiktok_search_runner 2>/dev/null || true
  pkill -f tiktok_video_runner 2>/dev/null || true
  pkill -f instagram_search_runner 2>/dev/null || true
  pkill -f instagram_post_runner 2>/dev/null || true
  pkill -f youtube_search_runner 2>/dev/null || true
  pkill -f youtube_video_runner 2>/dev/null || true
  sleep 5
  rm -f "$ROOT/logs/continuous-locks"/dis-*.lock 2>/dev/null || true
}

run_format_filter() {
  local film="$1" plat="$2"
  log "Format+filter film=$film platform=$plat (skip crawl)"
  env SOCIAL_LISTENING_PROFILE=dis SOCIAL_FILM_SLUG="$film" \
    "$PY" -u scripts/marketing/run_full_pipeline.py "$plat" \
    --skip-crawl --skip-sync --continue-on-error >>"$LOG" 2>&1 || true
}

run_import_all() {
  log "Import DB for both films…"
  for film in "${FILMS[@]}"; do
    log "import_film_mentions --film $film"
    "$PY" -u scripts/distribution/import_film_mentions.py --film "$film" >>"$LOG" 2>&1 || true
    log "classify intent --film-slug $film"
    "$PY" -u scripts/distribution/classify/classify_mention_intent.py \
      --film-slug "$film" --reclassify >>"$LOG" 2>&1 || true
  done
  log "recompute_daily_film_metrics"
  "$PY" -u scripts/distribution/metrics/recompute_daily_film_metrics.py >>"$LOG" 2>&1 || true
}

print_db_summary() {
  "$PY" - <<'PY' | tee -a "$LOG"
from social_listening.pg import get_connection
films = ["quy_tu_vuot_giau", "nghi_he_so_nghi_huu"]
with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("""
      SELECT f.film_slug::text, m.platform_code, m.mention_kind, COUNT(DISTINCT mf.mention_id)
      FROM films f
      JOIN mention_films mf ON mf.film_id = f.film_id
      JOIN mentions m ON m.mention_id = mf.mention_id AND COALESCE(m.is_spam, FALSE) = FALSE
      WHERE f.film_slug = ANY(%s)
      GROUP BY 1,2,3 ORDER BY 1,2,3
    """, (films,))
    print("=== DB after import ===")
    for r in cur.fetchall():
        print(r)
PY
}

END_AT=$(date -v+"${WAIT_HOURS}H" '+%H:%M' 2>/dev/null || date -d "+${WAIT_HOURS} hours" '+%H:%M' 2>/dev/null || echo "?")
log "START — crawl tiếp ${WAIT_HOURS}h, dừng ~${END_AT}, rồi import DB"
log "Crawlers hiện tại vẫn chạy cho đến khi hết ${WAIT_HOURS}h"

sleep "$WAIT_SEC"

log "===== ${WAIT_HOURS}h elapsed — stop & import ====="
stop_crawlers

for film in "${FILMS[@]}"; do
  for plat in "${PLATFORMS[@]}"; do
    run_format_filter "$film" "$plat"
  done
done

run_import_all
print_db_summary
log "DONE — import xong"
