#!/usr/bin/env bash
# Crawl MXH thêm comment cho phim thiếu khen/chê (Ám + Nghỉ Hè). Platforms song song / phim.
set -u
cd "$(dirname "$0")/../.."
PY="$PWD/.venv/bin/python"
export PYTHONPATH=src
export CHROMEDRIVER_PATH="$PWD/runtime/bin/chromedriver"
unset PGHOST PGPORT PGDATABASE PGSCHEMA PGUSER PGPASSWORD
mkdir -p /tmp/dis-mxh-parallel

FILMS=(am_chuoi_phim_ngan_linh_di nghi_he_so_nghi_huu)
PLATFORMS=(youtube tiktok facebook instagram threads)

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
    run_one "$film" "$plat" &
    pids+=($!)
  done
  fail=0
  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then fail=1; fi
  done
  echo "[$(date +%H:%M:%S)] film=$film platforms done (fail_flag=$fail)"
done

echo "=== reclassify + metrics $(date +%H:%M:%S) ==="
for film in "${FILMS[@]}" conan_thien_than_sa_nga_tren_xa_lo; do
  "$PY" -u scripts/distribution/classify/classify_mention_intent.py --film-slug "$film" --reclassify || true
done
"$PY" -u - <<'PY'
from social_listening.pg import get_connection
from social_listening.film_classify import classify_intent, detect_sentiment
slugs=['am_chuoi_phim_ngan_linh_di','nghi_he_so_nghi_huu','conan_thien_than_sa_nga_tren_xa_lo']
with get_connection() as conn:
    cur=conn.cursor()
    cur.execute("""
      SELECT m.mention_id::text, m.content_text FROM mentions m
      JOIN mention_films mf ON mf.mention_id=m.mention_id
      JOIN films f ON f.film_id=mf.film_id
      WHERE f.film_slug=ANY(%s) AND m.is_spam=FALSE AND m.platform_code<>'news'
    """, (slugs,))
    for mid, text in cur.fetchall():
        intent=classify_intent(str(text or ''))
        sent=detect_sentiment(str(text or ''))
        cur.execute(
            "UPDATE mentions SET intent=%s, sentiment=%s, updated_at=NOW() WHERE mention_id=%s::uuid",
            (intent, sent, mid),
        )
    # keep active
    cur.execute("""
      UPDATE films SET is_active=TRUE, status='in_release', updated_at=NOW()
      WHERE film_slug=ANY(%s)
    """, (slugs,))
    conn.commit()
    cur.execute("""
      SELECT f.film_title,
             COUNT(*) FILTER (WHERE m.intent='watched_praise') p,
             COUNT(*) FILTER (WHERE m.intent='watched_criticize') c,
             COUNT(*) FILTER (WHERE m.mention_kind='comment' AND m.intent IN ('watched_praise','watched_criticize')) cw
      FROM films f
      JOIN mention_films mf ON mf.film_id=f.film_id
      JOIN mentions m ON m.mention_id=mf.mention_id AND m.is_spam=FALSE AND m.platform_code<>'news'
      WHERE f.film_slug=ANY(%s)
        AND (m.occurred_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date >= CURRENT_DATE - INTERVAL '30 days'
      GROUP BY 1 ORDER BY 1
    """, (slugs,))
    print('=== inventory khen/che 30d ===')
    for r in cur.fetchall(): print(r)
PY
"$PY" -u scripts/distribution/metrics/recompute_daily_film_metrics.py || true
echo "=== ALL DONE $(date +%H:%M:%S) ==="
