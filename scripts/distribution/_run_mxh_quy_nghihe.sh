#!/usr/bin/env bash
# DIS MXH: Quý Tử Vượt Giàu + Nghỉ Hè Sợ Nghỉ Hưu
# Platforms song song / film; 2 film tuần tự (cùng Chrome không chia được).
set -u
cd "$(dirname "$0")/../.."
PY="$PWD/.venv/bin/python"
export PYTHONPATH=src
export SOCIAL_CONFIG_SOURCE=db
export CHROMEDRIVER_PATH="$PWD/runtime/bin/chromedriver"
unset PGHOST PGPORT PGDATABASE PGSCHEMA PGUSER PGPASSWORD
mkdir -p /tmp/dis-mxh-parallel

FILMS=(quy_tu_vuot_giau nghi_he_so_nghi_huu)
PLATFORMS=(youtube tiktok facebook instagram threads)

echo "[$(date +%H:%M:%S)] seed_films (once)"
"$PY" -u scripts/distribution/seed_films.py --force-queries

run_one() {
  local film="$1" plat="$2"
  local log="/tmp/dis-mxh-parallel/${film}__${plat}.log"
  echo "[$(date +%H:%M:%S)] START $film / $plat → $log"
  if "$PY" -u scripts/distribution/run_distribution_pipeline.py \
      --film "$film" --platform "$plat" --import-db --continue-on-error --skip-seed \
      >"$log" 2>&1
  then
    echo "[$(date +%H:%M:%S)] OK   $film / $plat"
    return 0
  else
    echo "[$(date +%H:%M:%S)] FAIL $film / $plat (see $log)"
    return 1
  fi
}

for film in "${FILMS[@]}"; do
  echo ""
  echo "########## $(date +%H:%M:%S) film=$film — parallel platforms ##########"
  pids=()
  for plat in "${PLATFORMS[@]}"; do
    if pgrep -fl "run_distribution_pipeline.py --film $film --platform $plat" >/dev/null 2>&1; then
      echo "[$(date +%H:%M:%S)] KEEP already-running $film / $plat"
      continue
    fi
    run_one "$film" "$plat" &
    pids+=($!)
  done
  fail=0
  if ((${#pids[@]} > 0)); then
    for pid in "${pids[@]}"; do
      if ! wait "$pid"; then
        fail=1
      fi
    done
  fi
  while pgrep -fl "run_distribution_pipeline.py --film $film " >/dev/null 2>&1; do
    echo "[$(date +%H:%M:%S)] waiting leftover pipelines for $film ..."
    sleep 15
  done
  echo "[$(date +%H:%M:%S)] film=$film platforms done (fail_flag=$fail)"
done

echo "=== retry import + classify $(date +%H:%M:%S) ==="
for film in "${FILMS[@]}"; do
  "$PY" -u scripts/distribution/import_film_mentions.py --film "$film" || true
  "$PY" -u scripts/distribution/classify/classify_mention_intent.py --film-slug "$film" --reclassify || true
done
"$PY" -u scripts/distribution/classify/classify_mention_region.py || true
"$PY" -u scripts/distribution/metrics/recompute_daily_film_metrics.py || true

"$PY" - <<'PY'
from social_listening.pg import get_connection
films = ["quy_tu_vuot_giau", "nghi_he_so_nghi_huu"]
with get_connection() as conn:
    cur = conn.cursor()
    cur.execute(
        """
      SELECT f.film_slug, m.platform_code, m.mention_kind, COUNT(*)
      FROM films f
      LEFT JOIN mention_films mf ON mf.film_id=f.film_id
      LEFT JOIN mentions m ON m.mention_id=mf.mention_id AND COALESCE(m.is_spam,FALSE)=FALSE
      WHERE f.film_slug = ANY(%s)
      GROUP BY 1,2,3 ORDER BY 1,2,3
        """,
        (films,),
    )
    print("=== inventory ===")
    for r in cur.fetchall():
        print(r)
PY
echo "=== ALL DONE $(date +%H:%M:%S) ==="
