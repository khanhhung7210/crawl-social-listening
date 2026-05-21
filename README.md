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
- mỗi platform tự chạy tuần tự các bước crawl/filter/format/sync của chính nó
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
