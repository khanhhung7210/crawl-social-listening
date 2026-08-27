#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/../.."
PY="$PWD/.venv/bin/python"
export PYTHONPATH=src
export CHROMEDRIVER_PATH="$PWD/runtime/bin/chromedriver"
unset PGHOST PGPORT PGDATABASE PGSCHEMA PGUSER PGPASSWORD
mkdir -p /tmp/dis-mxh-parallel

FILM=nguoi_nhen_khoi_dau_moi
PLATFORMS=(youtube tiktok facebook instagram threads)

echo "[$(date +%H:%M:%S)] seed_films (once)"
"$PY" -u scripts/distribution/seed_films.py

for plat in "${PLATFORMS[@]}"; do
  log="/tmp/dis-mxh-parallel/${FILM}__${plat}.log"
  echo "[$(date +%H:%M:%S)] START $FILM / $plat → $log"
  "$PY" -u scripts/distribution/run_distribution_pipeline.py \
    --film "$FILM" --platform "$plat" --import-db --continue-on-error --skip-seed \
    >"$log" 2>&1 &
done
wait
echo "[$(date +%H:%M:%S)] all platforms done — classify"
"$PY" -u scripts/distribution/classify/classify_mention_intent.py --film-slug "$FILM" --reclassify || true
"$PY" -u scripts/distribution/classify/classify_mention_region.py || true
"$PY" -u scripts/distribution/metrics/recompute_daily_film_metrics.py || true
"$PY" - <<'PY'
from social_listening.pg import get_connection
with get_connection() as conn:
    cur=conn.cursor()
    cur.execute("""
      SELECT m.platform_code, m.mention_kind, COUNT(*)
      FROM mentions m JOIN mention_films mf ON mf.mention_id=m.mention_id
      JOIN films f ON f.film_id=mf.film_id
      WHERE f.film_slug='nguoi_nhen_khoi_dau_moi' AND m.is_spam=FALSE
      GROUP BY 1,2 ORDER BY 1,2
    """)
    print('=== inventory ===')
    for r in cur.fetchall(): print(r)
PY
echo "=== DONE $(date +%H:%M:%S) ==="
