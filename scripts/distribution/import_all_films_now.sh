#!/usr/bin/env bash
# Format/filter raw đã crawl + import DB cho 2 phim Distribution.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
export PYTHONPATH=src
export SOCIAL_CONFIG_SOURCE=db
export CHROMEDRIVER_PATH="$ROOT/runtime/bin/chromedriver"

FILMS=(quy_tu_vuot_giau nghi_he_so_nghi_huu)
PLATFORMS=(facebook tiktok threads instagram youtube)
LOG="$ROOT/runtime/logs/import_all_films.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== IMPORT ALL (skip crawl) ==="

for film in "${FILMS[@]}"; do
  for plat in "${PLATFORMS[@]}"; do
    log "format+filter film=$film platform=$plat"
    env SOCIAL_LISTENING_PROFILE=dis SOCIAL_FILM_SLUG="$film" \
      "$PY" -u scripts/marketing/run_full_pipeline.py "$plat" \
      --skip-crawl --skip-sync --continue-on-error >>"$LOG" 2>&1 || true
  done
done

for film in "${FILMS[@]}"; do
  log "import_film_mentions --film $film"
  "$PY" -u scripts/distribution/import_film_mentions.py --film "$film" >>"$LOG" 2>&1 || true
  log "classify intent --film-slug $film"
  "$PY" -u scripts/distribution/classify/classify_mention_intent.py \
    --film-slug "$film" --reclassify >>"$LOG" 2>&1 || true
done

log "recompute_daily_film_metrics"
"$PY" -u scripts/distribution/metrics/recompute_daily_film_metrics.py >>"$LOG" 2>&1 || true

log "export CSV"
"$PY" -u scripts/distribution/export_film_mentions_csv.py \
  --film quy_tu_vuot_giau --film nghi_he_so_nghi_huu >>"$LOG" 2>&1 || true

log "=== DB SUMMARY ==="
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
    for r in cur.fetchall():
        print(r)
PY

log "=== DONE ==="
