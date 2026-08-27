#!/usr/bin/env bash
# DIS MXH: platforms song song / film; 2 film tuần tự (cùng Chrome không chia được).
# Crawl+import parallel; nếu import lỗi sẽ retry import tuần tự cuối cùng.
set -u
cd "$(dirname "$0")/../.."
PY="$PWD/.venv/bin/python"
export PYTHONPATH=src
export CHROMEDRIVER_PATH="$PWD/runtime/bin/chromedriver"
unset PGHOST PGPORT PGDATABASE PGSCHEMA PGUSER PGPASSWORD
mkdir -p /tmp/dis-mxh-parallel

FILMS=(thu_tinh_gui_ngoai conan_thien_than_sa_nga_tren_xa_lo)
PLATFORMS=(youtube tiktok facebook instagram threads)

# Seed 1 lần — tránh 5 job parallel gọi seed_films cùng lúc
echo "[$(date +%H:%M:%S)] seed_films (once)"
"$PY" -u scripts/distribution/seed_films.py

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
    # Skip if this platform already crawling this film (e.g. youtube left from sequential run)
    if pgrep -fl "run_distribution_pipeline.py --film $film --platform $plat" >/dev/null 2>&1; then
      echo "[$(date +%H:%M:%S)] KEEP already-running $film / $plat"
      continue
    fi
    run_one "$film" "$plat" &
    pids+=($!)
  done
  # Also wait for any pre-existing pipeline for this film
  fail=0
  for pid in "${pids[@]:-}"; do
    if ! wait "$pid"; then
      fail=1
    fi
  done
  # Wait leftover pre-existing processes for this film
  while pgrep -fl "run_distribution_pipeline.py --film $film " >/dev/null 2>&1; do
    echo "[$(date +%H:%M:%S)] waiting leftover pipelines for $film ..."
    sleep 15
  done
  echo "[$(date +%H:%M:%S)] film=$film platforms done (fail_flag=$fail)"
done

echo ""
echo "=== retry import + classify $(date +%H:%M:%S) ==="
for film in "${FILMS[@]}"; do
  "$PY" -u scripts/distribution/import_film_mentions.py --film "$film" || true
  "$PY" -u scripts/distribution/classify/classify_mention_intent.py --film-slug "$film" --reclassify || true
done
"$PY" -u scripts/distribution/classify/classify_mention_region.py || true
"$PY" -u scripts/distribution/metrics/recompute_daily_film_metrics.py || true

"$PY" - <<'PY'
from social_listening.pg import get_connection
films = ["thu_tinh_gui_ngoai", "conan_thien_than_sa_nga_tren_xa_lo"]
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
