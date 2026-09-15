#!/usr/bin/env bash
# Dừng supervisor, đợi vòng crawl hiện tại xong (đã import DB), rồi tắt hết worker.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG="$ROOT/runtime/logs/finish_round_then_stop.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== finish_round_then_stop ==="
log "Stopping supervisor (no restart)…"
pkill -f run_continuous_supervisor 2>/dev/null || true
sleep 2

log "Waiting for pipeline rounds to finish (crawl + import)…"
while pgrep -f "run_distribution_pipeline.py" >/dev/null 2>&1; do
  pgrep -fl "run_distribution_pipeline.py" 2>/dev/null | head -8 >>"$LOG" || true
  sleep 20
done
log "All pipeline rounds finished."

log "Waiting classify/metrics post-steps…"
sleep 30

log "Stopping continuous workers and orphan crawlers…"
pkill -f run_continuous_distribution.py 2>/dev/null || true
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
rm -f "$ROOT/logs/continuous-locks"/dis-*.lock 2>/dev/null || true

sleep 2
REMAIN=$(pgrep -fc "run_continuous|run_distribution|facebook_raw|threads_|tiktok_|instagram_|youtube_" 2>/dev/null || echo 0)
log "Remaining crawl processes: $REMAIN"
log "=== DONE — terminals stopped after final import ==="
