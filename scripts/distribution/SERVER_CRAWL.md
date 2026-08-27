# Distribution server crawl — chung DB Marketing, port Chrome riêng

DB: `galaxy_social_listening` / schema `galaxy_sl` (cùng MKT).  
Chỉ thêm bảng Dis + cột `mentions.intent`.

## Port Chrome (tránh trùng MKT)

| Platform | MKT | **DIS** | Profile DIS |
|----------|-----|---------|-------------|
| Threads | 9222 | **9232** | `runtime/chrome/dis-threads` |
| TikTok | 9223 | **9233** | `runtime/chrome/dis-tiktok` |
| Instagram | 9224 | **9234** | `runtime/chrome/dis-instagram` |
| YouTube | 9225 | **9235** | `runtime/chrome/dis-youtube` |
| Facebook | 9226 | **9236** | `runtime/chrome/dis-facebook` |

---

## 1) DB đã có MKT → chỉ seed Dis

```bash
cd social-listening
source .venv/bin/activate
export PYTHONPATH=src

# Thêm bảng films/… nếu chưa có + seed 5 phim active
python3 scripts/distribution/seed_films.py --apply-schema
```

Phim active hiện tại: The Odyssey · Ám · Người Nhện · Nghỉ Hè · Minion  
(Lilo `active: false`)

---

## 2) Mở Chrome DIS (login sẵn)

```bash
export PYTHONPATH=src
python3 scripts/distribution/run_by_platform.py --list

python3 scripts/distribution/run_by_platform.py tiktok --chrome-only
python3 scripts/distribution/run_by_platform.py youtube --chrome-only
python3 scripts/distribution/run_by_platform.py facebook --chrome-only
python3 scripts/distribution/run_by_platform.py instagram --chrome-only
python3 scripts/distribution/run_by_platform.py threads --chrome-only
```

Hoặc tay:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9233 --remote-allow-origins='*' \
  --user-data-dir="$PWD/runtime/chrome/dis-tiktok" \
  --no-first-run --no-default-browser-check about:blank &
# tương tự 9235 youtube / 9236 facebook / 9234 ig / 9232 threads
```

---

## 3) Crawl trước (News + 1 vòng MXH)

```bash
# News — buzz có ngay, không cần Chrome
PYTHONPATH=src python3 scripts/distribution/run_dis_full_sync.py --days 90

# 1 platform / all 5 phim active
PYTHONPATH=src python3 scripts/distribution/run_by_platform.py tiktok \
  --all-active --import-db --continue-on-error
```

---

## 4) Continuous — 1 terminal / platform (như MKT)

```bash
cd social-listening && source .venv/bin/activate && export PYTHONPATH=src

# Terminal A — News
while true; do
  python3 scripts/distribution/run_dis_full_sync.py --days 90
  sleep 300
done

# Terminal B — TikTok :9233
python3 scripts/distribution/run_continuous_distribution.py \
  --all-active --platform tiktok --import-db --sleep 180 --continue-on-error

# Terminal C — YouTube :9235
python3 scripts/distribution/run_continuous_distribution.py \
  --all-active --platform youtube --import-db --sleep 180 --continue-on-error

# Terminal D — Facebook :9236
python3 scripts/distribution/run_continuous_distribution.py \
  --all-active --platform facebook --import-db --sleep 180 --continue-on-error

# Terminal E — Instagram :9234
python3 scripts/distribution/run_continuous_distribution.py \
  --all-active --platform instagram --import-db --sleep 180 --continue-on-error

# Terminal F — Threads :9232
python3 scripts/distribution/run_continuous_distribution.py \
  --all-active --platform threads --import-db --sleep 180 --continue-on-error
```

Mỗi vòng: crawl → import → classify intent → metrics.  
Lock: `logs/continuous-locks/dis-all-<platform>.lock`

---

## 5) Check 5 phim

```bash
psql -d galaxy_social_listening -c "
SET search_path TO galaxy_sl;
SELECT f.film_title,
       COUNT(*) FILTER (WHERE m.platform_code='news') AS news,
       COUNT(*) FILTER (WHERE m.mention_kind='comment') AS comments,
       COUNT(*) FILTER (WHERE m.intent IS NOT NULL) AS intent
FROM films f
LEFT JOIN mention_films mf ON mf.film_id=f.film_id
LEFT JOIN mentions m ON m.mention_id=mf.mention_id AND m.is_spam=FALSE
WHERE f.is_active
GROUP BY f.film_title ORDER BY comments DESC, news DESC;
"
```
