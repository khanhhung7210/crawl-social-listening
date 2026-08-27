# Scripts Reference

Cây thư mục sau khi gọn theo **Marketing / Distribution → platform → keyword**:

```text
scripts/
├── marketing/
│   ├── run_continuous.py          # treo terminal MKT
│   ├── run_full_pipeline.py       # crawl → filter → import 1 platform
│   ├── crawl/
│   │   ├── facebook/ tiktok/ threads/ instagram/ youtube/
│   │   ├── news/                  # Google News RSS
│   │   └── reviews/               # App Store/Play + google_maps/
│   ├── classify/                  # campaign / CX topic / media_type
│   └── metrics/                   # daily_brand_metrics
├── distribution/
│   ├── run_by_platform.py         # treo terminal DIS (1 Chrome / platform)
│   ├── crawl/                     # news phim, heatmap, screens
│   ├── classify/                  # intent + region
│   └── metrics/                   # daily_film_metrics
├── shared/                        # import DB, purge, setup Postgres
└── windows/
```

Hot News / Sentiment **không** tách folder crawl — cùng stream mention, classify/aggregate sau.

## Pipeline tổng quan

```text
Crawl raw → (Search filter) → Detail crawl → Format/parse → Keyword filter → Import Postgres → Classify / metrics
```

Orchestrator:

| Entry | Môi trường | Mô tả |
|-------|------------|--------|
| `marketing/run_full_pipeline.py` | Mac/Linux | Chạy full pipeline 1 platform hoặc `all` |
| `marketing/run_continuous.py` | Mac/Linux | Loop vô hạn 1 platform (hoặc `news` / `all`) |
| `windows/run_social_listening_daily.ps1` | Windows | Daily job: chạy song song 6 platform |
| `windows/run_platform_pipeline.ps1` | Windows | Chạy tuần tự các step của 1 platform |

Thứ tự điển hình (ví dụ TikTok):

1. `tiktok_search_runner.py`
2. `tiktok_search_filter_job.py`
3. `tiktok_video_runner.py`
4. `tiktok_format_job.py`
5. `tiktok_keyword_filter_job.py`
6. `shared/import_keyword_mentions.py`
7. (tuỳ chọn) `build_campaign_tracking.py` / classify / recompute metrics

Hoặc:

```bash
PYTHONPATH=src python3 scripts/marketing/run_full_pipeline.py tiktok
```

### Chạy liên tục (treo terminal)

Mỗi platform **1 terminal**. Hết keyword + tên rạp (`branch_keywords`) → nghỉ → chạy lại (incremental).

```bash
cd social-listening
source .venv/bin/activate
export PYTHONPATH=src

# Facebook (Chrome debug 9226 đã login)
python3 scripts/marketing/run_continuous.py facebook

# Instagram (port 9224)
python3 scripts/marketing/run_continuous.py instagram --sleep 180

# Có import DB mỗi vòng
python3 scripts/marketing/run_continuous.py facebook --import-db --sleep 120
```

`Ctrl+C` để dừng. Lock: `logs/continuous-locks/<platform>.lock`

Chrome debug ports:

| Platform | Port env | Default |
|----------|----------|---------|
| Threads | `THREADS_DEBUGGER_ADDRESS` | `127.0.0.1:9222` |
| TikTok | `TIKTOK_DEBUGGER_ADDRESS` | `127.0.0.1:9223` |
| Instagram | `INSTAGRAM_DEBUGGER_ADDRESS` | `127.0.0.1:9224` |
| YouTube | `YOUTUBE_DEBUGGER_ADDRESS` | `127.0.0.1:9225` |
| Facebook | `FACEBOOK_DEBUGGER_ADDRESS` | `127.0.0.1:9226` |
| Google Maps | `GOOGLE_MAPS_DEBUGGER_ADDRESS` | `127.0.0.1:9227` |

Keyword config dùng chung (Marketing / brand rạp): `data/shared/social_keywords.json`

### Distribution (phim chiếu → DB)

```bash
PYTHONPATH=src python3 scripts/distribution/seed_films.py --apply-schema
PYTHONPATH=src python3 scripts/distribution/run_distribution_pipeline.py \
  --film 28_years_later_the_bone_temple --platform tiktok --import-db
```

Chi tiết: `scripts/distribution/README.md`

---

## `marketing/crawl/facebook/`

| File | Việc làm | Input → Output |
|------|----------|----------------|
| `facebook_raw_runner.py` | Selenium crawl Facebook search | keyword config → `data/facebook/raw/<film>/…/*.jsonl` |
| `facebook_keyword_filter_job.py` | Lọc raw theo keyword | raw JSONL → `facebook_keyword_mentions.json` |
| `facebook_format_job.py` | Đổi sang format legacy để import DB | keyword mentions → `facebook_formatted_mentions.json` |

Ghi chú: Facebook gộp search + detail trong `facebook_raw_runner.py` (không có runner detail riêng).

---

## `marketing/crawl/instagram/`

| File | Việc làm | Input → Output |
|------|----------|----------------|
| `instagram_search_runner.py` | Crawl search Instagram | keywords → `instagram_search_results.json` |
| `instagram_post_runner.py` | Crawl chi tiết post + comments | search results → `instagram_all_posts.json` |
| `instagram_format_job.py` | Parse raw posts | all posts → `instagram_grouped_parsed.json` |
| `instagram_keyword_filter_job.py` | Lọc theo keyword | grouped → `instagram_keyword_mentions.json` |

---

## `marketing/crawl/threads/`

| File | Việc làm | Input → Output |
|------|----------|----------------|
| `threads_crawl_runner.py` | Crawl search Threads | keywords → `threads_search_results.json` |
| `threads_search_filter_job.py` | Pre-filter URL trước khi crawl replies | search results → `threads_search_results_filtered.json` |
| `threads_replies_runner.py` | Crawl thread + replies | filtered/search → `threads_all_threads.json` |
| `threads_format_job.py` | Parse raw threads | all threads → `threads_grouped_parsed.json` |
| `threads_keyword_filter_job.py` | Lọc theo keyword | grouped → `threads_keyword_mentions.json` |
| `threads_runner.py` | **Legacy** — gọi EnsembleData API (không Selenium) | keywords cứng trong file → raw API JSON |

---

## `marketing/crawl/tiktok/`

| File | Việc làm | Input → Output |
|------|----------|----------------|
| `tiktok_search_runner.py` | Crawl search video | keywords → `tiktok_search_results.json` |
| `tiktok_search_runner_incremental.py` | Snippet/template incremental crawl (tham khảo) | — |
| `tiktok_search_filter_job.py` | Pre-filter URL trước khi crawl video | search → `tiktok_search_results_filtered.json` |
| `tiktok_video_runner.py` | Crawl chi tiết video + comments | filtered/search → `tiktok_all_videos.json` |
| `tiktok_format_job.py` | Parse raw videos | all videos → `tiktok_grouped_parsed.json` |
| `tiktok_keyword_filter_job.py` | Lọc theo keyword | grouped → `tiktok_keyword_mentions.json` |

---

## `marketing/crawl/youtube/`

| File | Việc làm | Input → Output |
|------|----------|----------------|
| `youtube_search_runner.py` | Crawl search YouTube | keywords → `youtube_search_results.json` |
| `youtube_search_filter_job.py` | Pre-filter URL trước khi crawl video | search → `youtube_search_results_filtered.json` |
| `youtube_video_runner.py` | Crawl chi tiết video + comments | filtered/search → `youtube_all_videos.json` |
| `youtube_format_job.py` | Parse raw videos | all videos → `youtube_grouped_parsed.json` |
| `youtube_keyword_filter_job.py` | Lọc theo keyword | grouped → `youtube_keyword_mentions.json` |

---

## `marketing/crawl/reviews/google_maps/`

| File | Việc làm | Input → Output |
|------|----------|----------------|
| `start_chrome_debug.sh` | Mở Chrome debug port `9227` | — |
| `google_maps_search_runner.py` | Search địa điểm theo query/URL config | keyword config → `google_maps_search_results.json` |
| `google_maps_review_runner.py` | Vào từng place, scroll lấy reviews | search results → `google_maps_all_places.json` |
| `google_maps_format_job.py` | Parse places/reviews | all places → `google_maps_grouped_parsed.json` |
| `google_maps_keyword_filter_job.py` | Lọc review có chứa keyword | grouped → `google_maps_keyword_mentions.json` |

---

## `marketing/classify/` + `marketing/metrics/`

| File | Việc làm |
|------|----------|
| `classify/seed_campaigns.py` | Seed campaigns + keywords + owned `source_profiles` |
| `classify/classify_mention_campaigns.py` | Gán mention → campaign theo `campaign_keywords` |
| `classify/classify_mention_topics.py` | Gán CX topics (booking, payment, …) → `mention_topics` |
| `classify/build_campaign_tracking.py` | One-shot: seed → classify → resolve media_type |
| `classify/resolve_mention_media_types.py` | Gán `media_type` (owned/earned/…) từ `source_profiles` |
| `metrics/recompute_daily_brand_metrics.py` | Rebuild `daily_brand_metrics` từ mentions |
| `crawl/news/crawl_news_mentions.py` | Crawl Google News RSS |
| `crawl/reviews/crawl_app_reviews.py` | Crawl Google Play + App Store |

## `shared/` — import DB / maintenance

### Setup & import

| File | Việc làm |
|------|----------|
| `setup_local_pg.sh` | Setup Postgres local (Homebrew) + apply `sql/galaxy_mkt_schema.sql` |
| `crawl_state_stats.py` | Xem thống kê incremental crawl theo platform |
| `test_incremental_crawl.py` | Test hệ thống crawl incremental |
| `import_keyword_mentions.py` | Import `*_keyword_mentions.json` → posts / comments / mentions |
| `import_app_reviews.py` | Import JSON App Store/Play → `app_reviews` + snapshots |
| `import_gbo_share.py` | Import CSV GBO share → `gbo_snapshots` |
| `run_continuous.py` / `run_full_pipeline.py` | Shim → `scripts/marketing/…` (lệnh cũ vẫn chạy) |

### Cleanup / maintenance

| File | Việc làm |
|------|----------|
| `dedupe_mentions.py` | Xóa mention/comment trùng + thêm unique index |
| `purge_listening_mentions.py` | Xóa mention không competitive SoV |
| `purge_non_vietnam_mentions.py` | Xóa mention không liên quan thị trường VN |
| `refilter_grouped_parsed.py` | Re-filter `grouped_parsed.json` theo keyword set khác (`--set-name`) |

---

## `windows/`

| File | Việc làm |
|------|----------|
| `run_platform_pipeline.ps1` | Chạy tuần tự các step của 1 platform (`threads`, `tiktok`, `youtube`, `instagram`, `facebook`, `google_maps`) |
| `run_social_listening_daily.ps1` | Daily job: optional mở Chrome debug, chạy song song 6 platform, lock file chống chạy trùng |

Ví dụ:

```powershell
.\scripts\windows\run_platform_pipeline.ps1 -Platform tiktok -RepoRoot "C:\path\to\social-listening"

.\scripts\windows\run_social_listening_daily.ps1 -StartChrome
```

Thứ tự step trong `run_platform_pipeline.ps1`:

| Platform | Steps |
|----------|-------|
| threads | crawl → search_filter → replies → format → keyword_filter |
| tiktok | search → search_filter → video → format → keyword_filter |
| youtube | search → search_filter → video → format → keyword_filter |
| instagram | search → post → format → keyword_filter |
| facebook | raw → keyword_filter → format |
| google_maps | search → review → format → keyword_filter |

> Windows pipeline **chỉ** crawl + format + filter. Import DB / classify chạy riêng (`shared/` + `marketing/classify/`).

---

## Sau khi crawl xong (DB)

```bash
# Import mentions từ mọi platform đã có keyword_mentions.json
PYTHONPATH=src python3 scripts/shared/import_keyword_mentions.py

# Campaign tracking (seed + classify + media_type + metrics)
PYTHONPATH=src python3 scripts/marketing/classify/build_campaign_tracking.py --brand glx

# Hoặc từng bước
PYTHONPATH=src python3 scripts/marketing/classify/seed_campaigns.py
PYTHONPATH=src python3 scripts/marketing/classify/classify_mention_campaigns.py --brand glx
PYTHONPATH=src python3 scripts/marketing/classify/classify_mention_topics.py --brand glx
PYTHONPATH=src python3 scripts/marketing/classify/resolve_mention_media_types.py
PYTHONPATH=src python3 scripts/marketing/metrics/recompute_daily_brand_metrics.py
```

---

## Naming convention

| Suffix | Ý nghĩa |
|--------|---------|
| `*_runner.py` | Crawl Selenium (raw data) |
| `*_search_filter_job.py` | Pre-filter danh sách URL sau search |
| `*_format_job.py` | Parse raw → structured JSON |
| `*_keyword_filter_job.py` | Lọc theo keyword config → mentions sẵn import |
| `import_*.py` | Ghi vào Postgres |
| `classify_*.py` | Gán nhãn (campaign / topic) trên DB |
| `purge_*.py` / `dedupe_*.py` | Dọn dữ liệu DB |
