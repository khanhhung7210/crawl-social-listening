# scripts/distribution — crawl phim → Postgres (như MKT)

Pipeline thật, không chỉ config JSON:

```text
keyword films/*.json
  → platform runners (FB/IG/Threads/TikTok/YT)  ← chạy TÁCH từng platform
  → *_keyword_mentions.json
  → import_film_mentions.py  (posts/comments/mentions + mention_films)
  → recompute_daily_film_metrics.py
```

## Tách platform (khuyến nghị — nhanh hơn)

Mỗi platform 1 Chrome + 1 terminal. Có thể chạy song song.

| Platform | Port | Lệnh |
|----------|------|------|
| Threads | 9222 | `run_by_platform.py threads …` |
| TikTok | 9223 | `run_by_platform.py tiktok …` |
| Instagram | 9224 | `run_by_platform.py instagram …` |
| YouTube | 9225 | `run_by_platform.py youtube …` |
| Facebook | 9226 | `run_by_platform.py facebook …` |

```bash
cd social-listening
source .venv/bin/activate
export PYTHONPATH=src

# Xem port / Chrome đang lên chưa
python3 scripts/distribution/run_by_platform.py --list

# Terminal 1 — TikTok
python3 scripts/distribution/run_by_platform.py tiktok --chrome-only
# (login TikTok trong cửa sổ Chrome vừa mở)
python3 scripts/distribution/run_by_platform.py tiktok --all-active --import-db --continue-on-error

# Terminal 2 — YouTube (song song)
python3 scripts/distribution/run_by_platform.py youtube --all-active --import-db --continue-on-error

# Treo liên tục 1 platform
python3 scripts/distribution/run_by_platform.py tiktok --all-active --continuous --sleep 180
```

**Tránh** `--platform all` — sẽ chạy tuần tự rất chậm.

## Chạy 1 lần (cách cũ vẫn dùng được)

```bash
cd social-listening
source .venv/bin/activate
export PYTHONPATH=src

# Seed schema + catalog phim vào DB
python3 scripts/distribution/seed_films.py --apply-schema

# Crawl 1 phim + 1 platform + import DB + metrics
python3 scripts/distribution/run_distribution_pipeline.py \
  --film the_odyssey --platform tiktok --import-db

# Nhiều phim active, vẫn 1 platform
python3 scripts/distribution/run_distribution_pipeline.py \
  --all-active --platform facebook --import-db --continue-on-error
```

Cần Chrome debug đã login (port theo bảng trên). `run_by_platform.py` sẽ tự mở Chrome nếu chưa có.

## Continuous (treo terminal)

```bash
python3 scripts/distribution/run_continuous_distribution.py \
  --all-active --platform tiktok --import-db --sleep 180
# hoặc
python3 scripts/distribution/run_by_platform.py tiktok --all-active --continuous
```

Lock theo `logs/continuous-locks/dis-<film|all>-<platform>.lock` → nhiều terminal song song được.

## Scripts

| File | Việc |
|------|------|
| `run_by_platform.py` | **Entry** — 1 platform / lần, auto Chrome, optional continuous |
| `seed_films.py` | Apply `sql/galaxy_dis_schema.sql` + seed films/aliases/milestones |
| `run_distribution_pipeline.py` | Crawl → import film mentions → daily_film_metrics |
| `import_film_mentions.py` | Ghi Postgres; **không** bắt buộc brand như MKT |
| `metrics/recompute_daily_film_metrics.py` | Aggregate buzz / sentiment / unique voices / views |
| `run_continuous_distribution.py` | Loop liên tục như `run_continuous.py` MKT |
| `run_dis_full_sync.py` | Seed + Google News + screens Moveek + region/intent + metrics |
| `crawl/crawl_region_screens.py` | Crawl suất chiếu/rạp theo vùng (Moveek) → `film_region_screens.json` |
| `classify/classify_mention_region.py` | Gán `metadata.dis_region` cho heatmap Buzz/Intent |
| `crawl/crawl_heatmap_data.py` | Orchestrator heatmap: screens + region + intent + metrics |
| `classify/classify_mention_intent.py` | Gán `mentions.intent` (want_to_see, …) |

## Heatmap Buzz theo Khu Vực

```bash
cd social-listening
source .venv/bin/activate
export PYTHONPATH=src

# Crawl suất chiếu Galaxy theo vùng + classify region/intent
python3 scripts/distribution/crawl/crawl_heatmap_data.py --all-active --seed-db

# Chỉ screens 1 phim (không ghi DB classify)
python3 scripts/distribution/crawl/crawl_region_screens.py --film the_odyssey --seed-db

# Full market (mọi cụm rạp), đếm số rạp thay vì suất
python3 scripts/distribution/crawl/crawl_region_screens.py --all-active --chain all --metric cinemas
```

| Hàng heatmap | Nguồn |
|--------------|--------|
| **Buzz** | Mentions phim + region (`metadata.dis_region` hoặc text) |
| **Intent** | `% want_to_see` sau `classify_mention_intent.py` |
| **Screens** | Moveek showtimes/cinemas → `film_region_screens.json` → seed |

## DB tables (schema `galaxy_sl`)

`films` · `film_aliases` · `film_milestones` · `mention_films` · `daily_film_metrics` · `mentions.intent`

Keyword configs vẫn nằm ở `data/distribution/` — đó là **search query**, không phải data mock.
