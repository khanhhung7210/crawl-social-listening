# Social Listening Scripts

Repo này hiện là bộ script ad-hoc để crawl và lọc dữ liệu social listening, đã được dọn lại theo cấu trúc gọn hơn:

```text
social-listening/
├── data/
│   ├── facebook/
│   │   ├── raw/
│   │   └── processed/
│   ├── threads/
│   │   ├── raw/
│   │   └── processed/
│   ├── tiktok/
│   │   ├── raw/
│   │   └── processed/
│   ├── youtube/
│   │   ├── raw/
│   │   └── processed/
│   ├── instagram/
│   │   ├── raw/
│   │   └── processed/
│   └── archive/
├── reports/
├── scripts/
│   ├── facebook/
│   ├── threads/
│   ├── tiktok/
│   ├── youtube/
│   └── instagram/
└── src/social_listening/
```

## Cài đặt

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quy ước thư mục

- `scripts/`: runner/job để crawl, parse, filter.
- `src/social_listening/`: helper dùng chung như path và text normalization.
- `data/*/raw/`: dữ liệu crawl thô.
- `data/*/processed/`: dữ liệu đã parse/lọc.
- `data/archive/`: file mẫu hoặc output cũ được giữ lại để tham chiếu.
- `reports/`: file Excel báo cáo.

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
python3 scripts/threads/threads_crawl_runner.py
python3 scripts/threads/threads_search_filter_job.py
python3 scripts/threads/threads_replies_runner.py
python3 scripts/threads/threads_format_job.py
python3 scripts/threads/threads_keyword_filter_job.py
python3 scripts/threads/threads_mongodb_sync.py
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
python3 scripts/tiktok/tiktok_search_runner.py
python3 scripts/tiktok/tiktok_search_filter_job.py
python3 scripts/tiktok/tiktok_video_runner.py
python3 scripts/tiktok/tiktok_format_job.py
python3 scripts/tiktok/tiktok_keyword_filter_job.py
python3 scripts/tiktok/tiktok_mongodb_sync.py
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
python3 scripts/facebook/facebook_raw_runner.py
python3 scripts/facebook/facebook_keyword_filter_job.py
python3 scripts/facebook/facebook_mongodb_sync.py
```

Keyword config:

- `data/shared/social_keywords.json`

Output mặc định:

- `data/facebook/raw/<YYYYMMDD>/*.jsonl`
- `data/facebook/processed/facebook_keyword_mentions.json`
  Các file thực tế hiện được lưu dưới thư mục con theo `film_title`.

Lưu ý:

- `facebook_raw_runner.py` hiện crawl web từ page Facebook public bằng browser session, không còn dùng Graph API.
- Nên dùng Chrome profile đã login để tránh popup và hạn chế nội dung.

## Chạy YouTube

Mở Chrome với remote debugging:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9225 \
  --user-data-dir=/tmp/chrome-codex-youtube
```

```bash
python3 scripts/youtube/youtube_search_runner.py
python3 scripts/youtube/youtube_search_filter_job.py
python3 scripts/youtube/youtube_video_runner.py
python3 scripts/youtube/youtube_format_job.py
python3 scripts/youtube/youtube_keyword_filter_job.py
python3 scripts/youtube/youtube_mongodb_sync.py
# hoặc
MONGO_URI='mongodb://user:pass@localhost:27017/?authSource=admin' python3 scripts/youtube/youtube_mongodb_sync.py
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
- Script MongoDB mặc định sync vào `CRM.tblSocial` trên `192.168.0.223` với user `galaxy`; có thể override bằng `MONGO_URI` hoặc các biến `MONGO_HOST`, `MONGO_PORT`, `MONGO_DB`, `MONGO_COLLECTION`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_AUTH_SOURCE`, `FILM_TITLE`.

## Chạy Instagram

Mở Chrome với remote debugging và dùng profile đã login Instagram:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9224 \
  --user-data-dir=/tmp/chrome-codex-instagram
```

Sau đó chạy:

```bash
python3 scripts/instagram/instagram_search_runner.py
python3 scripts/instagram/instagram_post_runner.py
python3 scripts/instagram/instagram_format_job.py
python3 scripts/instagram/instagram_keyword_filter_job.py
python3 scripts/instagram/instagram_mongodb_sync.py
```

Output mặc định:

- `data/instagram/raw/instagram_search_results.json`
- `data/instagram/raw/instagram_all_posts.json`
- `data/instagram/processed/instagram_grouped_parsed.json`
- `data/instagram/processed/instagram_keyword_mentions.json`

Lưu ý:

- Instagram hiện nên chạy với session đã login, nếu không search và comments rất dễ bị hạn chế.
- `created_at` của comment ưu tiên thời gian thật nếu trang có dữ liệu nhúng; nếu chỉ có label tương đối thì sẽ quy đổi xấp xỉ theo thời điểm crawl.

## Sync MongoDB

Mỗi platform hiện có script sync riêng:

```bash
python3 scripts/facebook/facebook_mongodb_sync.py
python3 scripts/threads/threads_mongodb_sync.py
python3 scripts/tiktok/tiktok_mongodb_sync.py
python3 scripts/youtube/youtube_mongodb_sync.py
python3 scripts/instagram/instagram_mongodb_sync.py
```

Các script này mặc định sync vào `CRM.tblSocial`, và đều hỗ trợ:

- `MONGO_URI`
- `MONGO_HOST`
- `MONGO_PORT`
- `MONGO_DB`
- `MONGO_COLLECTION`
- `MONGO_USER`
- `MONGO_PASSWORD`
- `MONGO_AUTH_SOURCE`
- `MONGO_APP_NAME`
- `FILM_TITLE`
- `INPUT_FILE`

## Chạy Dashboard Report

Dashboard web mới nằm ngay trong repo và đọc trực tiếp từ Mongo `CRM.tblSocial` + `CRM.tblSentiment`.

Chạy local:

```bash
export MONGO_HOST=192.168.0.223
export MONGO_PORT=27017
export MONGO_DB=CRM
export MONGO_USER=galaxy
export MONGO_PASSWORD='<PwaVsk31Lro'
python3 scripts/dashboard/dashboard_server.py
```

Mặc định web sẽ lên ở:

- `http://127.0.0.1:8787`

Biến môi trường hỗ trợ:

- `DASHBOARD_HOST`
- `DASHBOARD_PORT`
- `MONGO_URI`
- `MONGO_HOST`
- `MONGO_PORT`
- `MONGO_DB`
- `MONGO_USER`
- `MONGO_PASSWORD`
- `MONGO_AUTH_SOURCE`

Dashboard hiện có:

- metric cards: total buzz, posts, comments, positive ratio, negative ratio
- social media type breakdown
- platform share breakdown
- top source by mentions
- platform sentiment table từ `tblSentiment`
- sentiment donut
- real feedbacks by topic từ `tblSocial.comments_`
- sample positive/negative comments
- methodology blocks giống format report

Test:

```bash
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests -v
```

Lưu ý:

- `facebook_raw_runner.py` hiện vẫn dùng giá trị cấu hình hardcode trong file.
- Nếu muốn sạch hơn nữa, bước tiếp theo nên chuyển các hằng số này sang `.env`.
