# Social Listening Scripts

Crawl + process social listening cho **Galaxy Cinema** (MXH + Maps). Schema MKT mới: `sql/galaxy_mkt_schema.sql` (DB `galaxy_social_listening`, schema `galaxy_sl`).

```text
social-listening/
├── data/             # raw/processed theo platform (không đổi)
├── scripts/
│   ├── marketing/    # crawl MXH + news/reviews + classify/metrics brand
│   ├── distribution/ # crawl phim + classify/metrics film
│   └── shared/       # import DB, purge, setup Postgres
├── sql/galaxy_mkt_schema.sql
├── src/social_listening/
```

## Cài đặt

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quy ước thư mục

- `scripts/marketing/`: crawl brand (platform → keyword), classify, metrics.
- `scripts/distribution/`: crawl phim, classify intent/region, film metrics.
- `scripts/shared/`: import Postgres, purge, setup.
- `src/social_listening/`: helper dùng chung như path và text normalization.
- `data/*/raw/`: dữ liệu crawl thô.
- `data/*/processed/`: dữ liệu đã parse/lọc.
- `reports/`: file Excel báo cáo.
- `sql/galaxy_mkt_schema.sql`: Postgres schema brand health MKT (Galaxy vs CGV/Lotte/Beta).

## Shared Keyword Config

Tất cả source đang đọc chung file:

- `data/shared/social_keywords.json`

Format cũ vẫn chạy nguyên như trước:

```json
{
  "film_title": "Hẹn Em Ngày Nhật Thực",
  "keywords": ["Hẹn Em Ngày Nhật Thực"],
  "sub_keywords": [],
  "hashtags": []
}
```

Nếu cần lưu nhiều key nhưng chỉ cho một process cụ thể chạy, có thể dùng object:

```json
{
  "active_process": "local",
  "film_title": "Hẹn Em Ngày Nhật Thực",
  "keywords": [
    "Hẹn Em Ngày Nhật Thực",
    {"value": "hen em review", "processes": ["local"]},
    {"value": "hen em server only", "processes": ["server"]}
  ]
}
```

Rule áp dụng cho tất cả source:

- string thường sẽ luôn chạy như trước
- object có `processes` chỉ chạy khi khớp `active_process`
- key nằm ngoài process hiện tại chỉ được lưu trong file, không tham gia crawl/filter
- có thể override bằng env `SOCIAL_LISTENING_PROCESS` hoặc `KEYWORD_PROCESS`

## Chạy Threads

Mở Chrome với remote debugging và dùng profile đã login Threads:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-codex-threads
```

Keyword config dùng chung:

- `data/shared/social_keywords.json`

```bash
python3 scripts/marketing/crawl/threads/threads_crawl_runner.py
python3 scripts/marketing/crawl/threads/threads_search_filter_job.py
python3 scripts/marketing/crawl/threads/threads_replies_runner.py
python3 scripts/marketing/crawl/threads/threads_format_job.py
python3 scripts/marketing/crawl/threads/threads_keyword_filter_job.py
```

Output mặc định:

- `data/threads/raw/threads_search_results.json`
- `data/threads/raw/threads_search_results_filtered.json`
- `data/threads/raw/threads_all_threads.json`
- `data/threads/processed/threads_grouped_parsed.json`
- `data/threads/processed/threads_keyword_mentions.json`
  Các file thực tế hiện được lưu dưới thư mục con theo `film_title`.

## Chạy TikTok

Mở Chrome với remote debugging trước:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9223 \
  --user-data-dir=/tmp/chrome-codex-tiktok
```

Sau đó chạy:

```bash
python3 scripts/marketing/crawl/tiktok/tiktok_search_runner.py
python3 scripts/marketing/crawl/tiktok/tiktok_search_filter_job.py
python3 scripts/marketing/crawl/tiktok/tiktok_video_runner.py
python3 scripts/marketing/crawl/tiktok/tiktok_format_job.py
python3 scripts/marketing/crawl/tiktok/tiktok_keyword_filter_job.py
```

Output mặc định:

- `data/tiktok/raw/tiktok_search_results.json`
- `data/tiktok/raw/tiktok_search_results_filtered.json`
- `data/tiktok/raw/tiktok_all_videos.json`
- `data/tiktok/processed/tiktok_grouped_parsed.json`
- `data/tiktok/processed/tiktok_keyword_mentions.json`
  Các file thực tế hiện được lưu dưới thư mục con theo `film_title`.

## Chạy Facebook

Mở Chrome với remote debugging và dùng profile đã login Facebook:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9226 \
  --user-data-dir=/tmp/chrome-codex-facebook
```

Sau đó chạy:

```bash
python3 scripts/marketing/crawl/facebook/facebook_raw_runner.py
python3 scripts/marketing/crawl/facebook/facebook_keyword_filter_job.py
python3 scripts/marketing/crawl/facebook/facebook_format_job.py
```

Keyword config:

- `data/shared/social_keywords.json`

Output mặc định:

- `data/facebook/raw/<YYYYMMDD>/*.jsonl`
- `data/facebook/processed/facebook_keyword_mentions.json`
  Các file thực tế hiện được lưu dưới thư mục con theo `film_title`.

Lưu ý:

- `facebook_raw_runner.py` hiện lấy `search_terms` từ `data/shared/social_keywords.json`, mở Facebook search tổng quát theo từng keyword rồi lọc các URL post tìm được để crawl bằng browser session.
- Nên dùng Chrome profile đã login để tránh popup và hạn chế nội dung.

## Chạy YouTube

Mở Chrome với remote debugging:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9225 \
  --user-data-dir=/tmp/chrome-codex-youtube
```

```bash
python3 scripts/marketing/crawl/youtube/youtube_search_runner.py
python3 scripts/marketing/crawl/youtube/youtube_search_filter_job.py
python3 scripts/marketing/crawl/youtube/youtube_video_runner.py
python3 scripts/marketing/crawl/youtube/youtube_format_job.py
python3 scripts/marketing/crawl/youtube/youtube_keyword_filter_job.py
```

Output mặc định:

- `data/youtube/raw/youtube_search_results.json`
- `data/youtube/raw/youtube_search_results_filtered.json`
- `data/youtube/raw/youtube_all_videos.json`
- `data/youtube/processed/youtube_grouped_parsed.json`
- `data/youtube/processed/youtube_keyword_mentions.json`
  Các file thực tế hiện được lưu dưới thư mục con theo `film_title`.


Lưu ý:

- YouTube script không cần login hay remote debugging để chạy cơ bản.
- YouTube hiện có thể attach vào Chrome debug riêng ở port `9225` để chạy song song với các platform khác.
- `created_at` của comment ưu tiên thời gian thật nếu trang có dữ liệu đầy đủ; nếu chỉ có label tương đối như `4 days ago` thì sẽ quy đổi xấp xỉ theo thời điểm crawl.

## Chạy Instagram

Mở Chrome với remote debugging và dùng profile đã login Instagram:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9224 \
  --user-data-dir=/tmp/chrome-codex-instagram
```

Sau đó chạy:

```bash
python3 scripts/marketing/crawl/instagram/instagram_search_runner.py
python3 scripts/marketing/crawl/instagram/instagram_post_runner.py
python3 scripts/marketing/crawl/instagram/instagram_format_job.py
python3 scripts/marketing/crawl/instagram/instagram_keyword_filter_job.py
```

Output mặc định:

- `data/instagram/raw/instagram_search_results.json`
- `data/instagram/raw/instagram_all_posts.json`
- `data/instagram/processed/instagram_grouped_parsed.json`
- `data/instagram/processed/instagram_keyword_mentions.json`

Lưu ý:

- Instagram hiện nên chạy với session đã login, nếu không search và comments rất dễ bị hạn chế.
- `created_at` của comment ưu tiên thời gian thật nếu trang có dữ liệu nhúng; nếu chỉ có label tương đối thì sẽ quy đổi xấp xỉ theo thời điểm crawl.

## Sync PostgreSQL

Crawl → `data/*/processed/*_keyword_mentions.json` → Postgres DB `galaxy_social_listening` / schema `galaxy_sl`.

```bash
# one-time local PG (Homebrew, no Docker)
./scripts/shared/setup_local_pg.sh

# App Review sample
PYTHONPATH=src python3 scripts/marketing/crawl/reviews/crawl_app_reviews.py
PYTHONPATH=src python3 scripts/shared/import_app_reviews.py --input data/app-reviews/live.json

# MXH keyword mentions (sau khi crawl)
PYTHONPATH=src python3 scripts/shared/import_keyword_mentions.py
PYTHONPATH=src python3 scripts/marketing/metrics/recompute_daily_brand_metrics.py

# Campaign Tracking (seed + match keyword → mention_campaigns + metrics + media_type)
# import_keyword_mentions.py cũng gọi build_campaign_tracking tự động nếu DB sẵn.
PYTHONPATH=src python3 scripts/marketing/classify/build_campaign_tracking.py
PYTHONPATH=src python3 scripts/marketing/classify/classify_mention_topics.py --brand glx

# Brand Health nhanh (không cần Chrome) — Google News RSS
PYTHONPATH=src python3 scripts/marketing/crawl/news/crawl_news_mentions.py --days 30
PYTHONPATH=src python3 scripts/shared/import_keyword_mentions.py --file data/news/processed/galaxy_cinema/news_keyword_mentions.json

# GBO Share (báo cáo nội bộ CSV → gbo_snapshots)
PYTHONPATH=src python3 scripts/shared/import_gbo_share.py
# hoặc: --input path/to/gbo_share.csv
# CSV: period_start,period_end,brand_slug,gbo_share_pct,cinema_count,source_name
```

Pipeline `./run-pipeline.sh <platform>` đã gọi `import_keyword_mentions.py` ở bước sync.

Dashboard MKT: repo `galaxy-dashboard-social` → `/marketing` (API `/api/mkt/brand-health`, `/api/mkt/campaigns`, `/api/mkt/app-reviews`). Không có data thì API/UI trả trống hoặc lỗi — không seed demo UI.

Campaign keywords/hashtags (`#GalaxySummer`, `#GalaxyRewards`, `#GalaxyIMAX`, …) đã thêm vào `data/shared/social_keywords.json` để crawl daily bắt được buzz campaign.

## Dashboard UI

UI nằm ở repo `galaxy-dashboard-social` (Next.js). Schema Postgres MKT: `sql/galaxy_mkt_schema.sql`.

Áp schema:

```bash
createdb galaxy_social_listening   # hoặc: CREATE DATABASE galaxy_social_listening;
psql -h localhost -U <user> -d galaxy_social_listening -f sql/galaxy_mkt_schema.sql
```

## Chạy Tự Động Trên Windows Server

Có thể chạy tự động hằng ngày cho cả 5 platform cùng lúc nếu mỗi platform đã có Chrome riêng với debug port riêng:

- Threads: `9222`
- TikTok: `9223`
- Instagram: `9224`
- YouTube: `9225`
- Facebook: `9226`

Script Windows đã thêm:

- [run_social_listening_daily.ps1](/Users/khangnhq/Desktop/WorkGalaxy/social-listening/scripts/windows/run_social_listening_daily.ps1#L1)
- [run_platform_pipeline.ps1](/Users/khangnhq/Desktop/WorkGalaxy/social-listening/scripts/windows/run_platform_pipeline.ps1#L1)

`run_social_listening_daily.ps1` sẽ:

- set đúng 5 biến `*_DEBUGGER_ADDRESS`
- giữ lock file để tránh chạy đè job cũ
- launch 5 pipeline song song
- mỗi platform tự chạy tuần tự các bước crawl/filter/format của chính nó
- ghi log riêng theo từng platform vào `logs/windows-runs/<timestamp>/`

Ví dụ chạy tay trên Windows:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\windows\run_social_listening_daily.ps1 `
  -RepoRoot C:\social-listening `
  -PythonPath C:\social-listening\.venv\Scripts\python.exe
```

Nếu muốn script tự mở luôn 5 Chrome debug profile:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\windows\run_social_listening_daily.ps1 `
  -RepoRoot C:\social-listening `
  -PythonPath C:\social-listening\.venv\Scripts\python.exe `
  -StartChrome
```

Gợi ý setup Task Scheduler:

1. Tạo task mới trong Windows Task Scheduler
2. Trigger: Daily, chọn giờ chạy
3. Action:

```text
Program/script:
powershell.exe

Add arguments:
-ExecutionPolicy Bypass -File "C:\social-listening\scripts\windows\run_social_listening_daily.ps1" -RepoRoot "C:\social-listening" -PythonPath "C:\social-listening\.venv\Scripts\python.exe"
```

4. Chọn `Run whether user is logged on or not`
5. Chọn `Start in`: `C:\social-listening`

Lưu ý thực tế trên Windows server:

- Nếu platform cần session login, profile Chrome tương ứng phải còn đăng nhập sẵn.
- Chạy song song được vì mỗi platform bám một Chrome port riêng, không đạp tab của nhau.
- Không nên dùng chung một port cho nhiều platform.

Biến môi trường hỗ trợ:

- `PGHOST` / `PGPORT` / `PGDATABASE` / `PGSCHEMA` / `PGUSER` / `PGPASSWORD`
- `SOCIAL_KEYWORDS_FILE` (optional override keyword JSON)

Test:

```bash
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests -v
```

Lưu ý:

- `facebook_raw_runner.py` hiện vẫn dùng giá trị cấu hình hardcode trong file.
- Nếu muốn sạch hơn nữa, bước tiếp theo nên chuyển các hằng số này sang `.env`.
