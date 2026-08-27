# Hiện trạng tổng hợp — Galaxy Social Listening

> Ngày cập nhật: **2026-08-25**  
> Phạm vi: **2 repo** — crawl/pipeline (`social-listening`) + UI dashboard (`galaxy-dashboard-social`)

---

## 0. Hai repo — link & vai trò

| Repo | Link GitHub | Local folder | Vai trò |
|------|-------------|--------------|---------|
| **Source (crawl)** | [https://github.com/galaxy-cinema/galaxy-social-listening](https://github.com/galaxy-cinema/galaxy-social-listening) | `social-listening/` | Crawl MXH / News / Maps / App reviews → parse/filter → import Postgres → classify / metrics |
| **Dashboard (UI)** | [https://github.com/galaxy-cinema/galaxy-dashboard-social](https://github.com/galaxy-cinema/galaxy-dashboard-social) | `galaxy-dashboard-social/` | Next.js dashboard: Marketing, Distribution, Auth/RBAC; đọc Postgres qua API |

| | Source | Dashboard |
|---|--------|-----------|
| Stack | Python + Selenium + Postgres | Next.js 14 + Tailwind + TanStack Query + Zustand |
| Branch local (tham khảo) | `socialDotAI` | `feat/mkt-dashboard` |
| DB chính | `galaxy_social_listening` / schema `galaxy_sl` | Cùng Postgres (`PGHOST`, `PGSCHEMA=galaxy_sl`) |

---

## 1. Luồng end-to-end

```text
[social-listening]
  Keyword config (MKT: social_keywords.json | DIS: films/<slug>.json)
        ↓
  Crawl raw (Selenium / RSS / Store)
        ↓
  Search filter → Detail → Format → Keyword filter
        ↓
  Import Postgres (scripts/shared/* hoặc import_film_mentions)
        ↓
  Classify + recompute metrics (MKT brand / DIS film)
        ↓
[galaxy-dashboard-social]
  /api/mkt/*  →  /marketing
  /api/dis/*  →  /distribution
```

**Nguyên tắc:** UI **không seed demo** — không có data trong DB thì API/UI trả trống hoặc lỗi.

---

# PHẦN A — social-listening (Source / Crawl)

## A1. Inventory Source

| Source | Loại | Port MKT | Port DIS | Ghi chú |
|--------|------|----------|----------|---------|
| Facebook | MXH Selenium | 9226 | 9236 | Search + detail gộp |
| Instagram | MXH Selenium | 9224 | 9234 | Search → post detail |
| Threads | MXH Selenium | 9222 | 9232 | Search → replies |
| TikTok | MXH Selenium | 9223 | 9233 | Search → video + comment |
| YouTube | MXH Selenium | 9225 | 9235 | Search → video + comment |
| Google Maps | Review rạp | 9227 | — | Chỉ MKT |
| Google News | RSS | — | — | MKT + DIS, không Chrome |
| App Store / Play | Store crawl | — | — | Chỉ MKT |
| GBO Share | CSV nội bộ | — | — | Chỉ MKT |

---

## A2. MARKETING crawl — crawl như thế nào?

### Mục tiêu
Theo dõi **brand rạp chiếu phim**: Galaxy vs CGV / Lotte / Beta / BHD / Cinestar — buzz, sentiment, SoV, campaign, CX topic, app review.

### Keyword config
- File: `data/shared/social_keywords.json`
- `film_title`: **Galaxy Cinema**
- Gồm: keyword brand đối thủ, `branch_keywords` (tên rạp Galaxy), hashtag campaign (`#GalaxySummer`…), `exclude_keywords`, `listening_keywords`
- Output processed: `data/<platform>/processed/galaxy_cinema/*_keyword_mentions.json`

### Pipeline chung (mỗi platform MXH)

```text
1. Search crawl      → tìm post/video theo keyword
2. Search filter     → lọc URL trùng / không liên quan (tuỳ platform)
3. Detail crawl      → mở từng link, lấy post + comment
4. Format job        → parse JSON thống nhất (grouped post–comment)
5. Keyword filter    → giữ mention match brand/keyword + context VN
6. Import Postgres   → import_keyword_mentions.py (--film galaxy_cinema)
7. Classify/metrics  → campaign, CX topic, daily_brand_metrics
```

### Chi tiết từng platform (script thực tế)

| Platform | Bước crawl (theo thứ tự) |
|----------|--------------------------|
| **Threads** | `threads_crawl_runner` → `threads_search_filter` → `threads_replies_runner` → `threads_format_job` → `threads_keyword_filter` |
| **Facebook** | `facebook_raw_runner` (search+detail gộp) → `facebook_keyword_filter` → `facebook_format_job` |
| **Instagram** | `instagram_search_runner` → `instagram_post_runner` → `instagram_format_job` → `instagram_keyword_filter` |
| **TikTok** | `tiktok_search_runner` → `tiktok_search_filter` → `tiktok_video_runner` → `tiktok_format_job` → `tiktok_keyword_filter` |
| **YouTube** | `youtube_search_runner` → `youtube_search_filter` → `youtube_video_runner` → `youtube_format_job` → `youtube_keyword_filter` |
| **Google Maps** | `google_maps_search_runner` → `google_maps_review_runner` → `google_maps_format_job` → `google_maps_keyword_filter` |

### Nguồn không cần Chrome

| Nguồn | Script | Import |
|-------|--------|--------|
| **Google News** | `crawl_news_mentions.py --days 30` | `import_keyword_mentions.py` |
| **App Store / Play** | `crawl_app_reviews.py` | `import_app_reviews.py` |
| **GBO Share** | — | `import_gbo_share.py` (CSV nội bộ) |

### Chrome debug — Marketing

Mỗi platform **1 Chrome profile riêng**, port riêng, **phải login sẵn** (FB/IG/Threads/TikTok):

| Platform | Port | Profile mặc định |
|----------|------|------------------|
| Threads | **9222** | `runtime/chrome/dis-threads` hoặc `/tmp/chrome-codex-threads` |
| TikTok | **9223** | tương tự |
| Instagram | **9224** | tương tự |
| YouTube | **9225** | ít cần login |
| Facebook | **9226** | bắt buộc login |
| Google Maps | **9227** | tương tự |

Env override: `THREADS_DEBUGGER_ADDRESS`, `TIKTOK_DEBUGGER_ADDRESS`, …

### Cách chạy Marketing

**Chạy 1 lần — 1 platform:**
```bash
cd social-listening && source .venv/bin/activate && export PYTHONPATH=src
./run-pipeline.sh tiktok
# hoặc
python3 scripts/marketing/run_full_pipeline.py facebook --continue-on-error
```

**Chạy tất cả platform (tuần tự):**
```bash
./run-pipeline.sh all --continue-on-error
```

**Treo liên tục — 1 terminal / platform (khuyến nghị prod):**
```bash
python3 scripts/marketing/run_continuous.py facebook --import-db --sleep 180
python3 scripts/marketing/run_continuous.py instagram --import-db --sleep 180
# … tương tự threads / tiktok / youtube / google_maps
```

**Mode `news` — không MXH, chỉ News + App + classify:**
```bash
python3 scripts/marketing/run_continuous.py news --import-db --sleep 300
```

**Windows Server — chạy song song 5–6 platform:**
```powershell
scripts/windows/run_social_listening_daily.ps1 -RepoRoot C:\social-listening -StartChrome
```

### Sau import — classify & metrics (Marketing)

Khi dùng `--import-db` hoặc mode `news`/`all`, pipeline tự chạy thêm:

| Script | Việc |
|--------|------|
| `import_keyword_mentions.py` | Ghi `mentions`, `comments`, `mention_brands` |
| `build_campaign_tracking.py` | Gắn campaign hashtag → `mention_campaigns` |
| `classify_mention_topics.py` | CX topic trên comment Galaxy |
| `recompute_daily_brand_metrics.py` | Aggregate buzz / sentiment / SoV theo ngày |
| `import_app_reviews.py` | App Store + Play → `app_reviews` |

### DB & UI Marketing

| Bảng chính | UI block |
|------------|----------|
| `mentions`, `comments`, `mention_brands` | SoV, Sentiment, Hot News |
| `daily_brand_metrics` | Market Overview, trend |
| `mention_campaigns`, `daily_campaign_metrics` | Campaign tracking |
| `app_reviews`, `cinema_places` | Unified Reviews |

---

## A3. DISTRIBUTION crawl — crawl như thế nào?

### Mục tiêu
Theo dõi **buzz / WOM theo phim chiếu** (không phải brand rạp): muốn xem, đã xem khen/chê, news, heatmap theo vùng.

### Keyword config
- Catalog: `data/distribution/film_catalog.json` — danh sách phim + `active` + milestone dates
- Mỗi phim: `data/distribution/films/<slug>.json` (cùng schema keyword, có `core_keywords`, `ambiguous_keywords`, `require_context`)
- Hiện có **10 phim** (**9 active**): The Odyssey, Minion, Người Nhện, Nghỉ Hè, Ám, Thư Tình Gửi Ngoại, Conan, Quý Tử Vượt Giàu, Hộ Linh Tráng Sĩ (+ Lilo inactive)

### Khác Marketing ở đâu?

| | Marketing | Distribution |
|---|-----------|----------------|
| Keyword file | `social_keywords.json` (1 file brand) | `films/<slug>.json` (1 file / phim) |
| Chrome port | 9222–9227 | **9232–9236** (MKT + 10, profile riêng) |
| Import script | `import_keyword_mentions.py` | `import_film_mentions.py` |
| Bắt buộc brand Galaxy? | **Có** (detect CGV/Lotte…) | **Không** — match theo film slug |
| Metrics | `daily_brand_metrics` | `daily_film_metrics` |
| Intent WOM | — | `classify_mention_intent.py` → `mentions.intent` |

**Cơ chế tái sử dụng:** Distribution **không viết crawler mới** — gọi lại `run_full_pipeline.py` (Marketing) nhưng set env:

```bash
SOCIAL_KEYWORD_CONFIG_FILE=data/distribution/films/the_odyssey.json
```

→ cùng runner Selenium, keyword khác, import khác.

### Pipeline Distribution (1 phim × 1 platform)

```text
1. seed_films.py              → đảm bảo bảng films/aliases/milestones
2. Set SOCIAL_KEYWORD_CONFIG_FILE = films/<slug>.json
3. run_full_pipeline.py <platform> --skip-sync   → crawl MXH theo keyword phim
4. import_film_mentions.py    → ghi mentions + link mention_films
5. classify_mention_intent.py → want_to_see / watched_praise / watched_criticize…
6. recompute_daily_film_metrics.py → buzz / sentiment / intent theo ngày
```

### Google News (Distribution — không Chrome)

Chạy trước hoặc song song để có buzz ngay:

```bash
python3 scripts/distribution/run_dis_full_sync.py --days 90
```

Script này: seed phim + crawl News RSS theo từng phim + (tuỳ chọn) screens Moveek + classify region/intent + metrics.

### Chrome debug — Distribution (port riêng, tránh đụng MKT)

| Platform | Port DIS | Profile |
|----------|----------|---------|
| Threads | **9232** | `runtime/chrome/dis-threads` |
| TikTok | **9233** | `runtime/chrome/dis-tiktok` |
| Instagram | **9234** | `runtime/chrome/dis-instagram` |
| YouTube | **9235** | `runtime/chrome/dis-youtube` |
| Facebook | **9236** | `runtime/chrome/dis-facebook` |

Kiểm tra Chrome đang up:
```bash
python3 scripts/distribution/run_by_platform.py --list
```

### Cách chạy Distribution

**Bước 0 — seed DB (1 lần):**
```bash
python3 scripts/distribution/seed_films.py --apply-schema
python3 scripts/distribution/run_distribution_pipeline.py --list
```

**Mở Chrome + login (1 lần / platform):**
```bash
python3 scripts/distribution/run_by_platform.py tiktok --chrome-only
# login TikTok trong cửa sổ vừa mở, rồi đóng terminal giữ Chrome chạy
```

**Crawl 1 platform — tất cả phim active:**
```bash
python3 scripts/distribution/run_by_platform.py tiktok \
  --all-active --import-db --continue-on-error --no-chrome
```

**Treo liên tục — khuyến nghị prod (1 terminal / platform):**
```bash
python3 scripts/distribution/run_by_platform.py tiktok \
  --all-active --continuous --import-db --continue-on-error --sleep 180 --no-chrome
```

**Terminal News (loop riêng):**
```bash
while true; do
  python3 scripts/distribution/run_dis_full_sync.py --days 90
  sleep 300
done
```

**Setup prod điển hình = 6 terminal:**
- 1 × News loop (`run_dis_full_sync`)
- 5 × MXH continuous (TikTok / YouTube / FB / IG / Threads) — mỗi cái 1 Chrome port DIS

### Heatmap Buzz theo khu vực (Distribution)

```bash
python3 scripts/distribution/crawl/crawl_heatmap_data.py --all-active --seed-db
```

| Hàng heatmap | Nguồn |
|--------------|--------|
| Buzz | Mentions phim + `metadata.dis_region` |
| Intent | `% want_to_see` sau classify |
| Screens | Moveek showtimes → `film_region_screens.json` |

### DB & UI Distribution

| Bảng | UI block |
|------|----------|
| `films`, `film_aliases`, `film_milestones` | Film picker, lifecycle markers |
| `mention_films` + `mentions` | KPIs, trend, compare |
| `daily_film_metrics` | Buzz delta, SoV phim |
| `mentions.intent` | WOM khen / chê |
| `film_region_screens` | Heatmap region |

---

## A4. So sánh nhanh MKT vs DIS

| Tiêu chí | Marketing | Distribution |
|----------|-----------|--------------|
| Crawl cái gì | Brand rạp + campaign + review app/maps | Buzz phim đang chiếu |
| Keyword | 1 file `social_keywords.json` | N file `films/*.json` |
| Entry chính | `run_full_pipeline.py` / `run_continuous.py` | `run_by_platform.py` |
| Chrome | Port 9222–9227 | Port 9232–9236 (profile khác) |
| Import | `import_keyword_mentions` | `import_film_mentions` |
| Classify | campaign + CX topic | intent WOM + region |
| Metrics | `daily_brand_metrics` | `daily_film_metrics` |
| Dashboard | `/marketing` | `/distribution` |

---

# PHẦN B — galaxy-dashboard-social (UI Dashboard)

> Branch: `feat/mkt-dashboard`  
> Repo: [galaxy-dashboard-social](https://github.com/galaxy-cinema/galaxy-dashboard-social)

## B0. Thang Readiness

| Mức | Ý nghĩa |
|-----|---------|
| **Live** | UI + API + DB nối xong; có crawl/import thì có data |
| **Partial** | UI/API có nhưng thiếu data thực tế, chưa save DB, hoặc tính năng phụ chưa làm |
| **Stub** | Demo / hardcode / chưa nối backend |

---

## B1. Shell & Auth

| Hạng mục | Route / file | Readiness | Ghi chú |
|----------|--------------|-----------|---------|
| Topbar (MKT / DIS tabs) | `layout.tsx`, `dashboard-shell.css` | **Live** | Export, Alerts badge, ⚙️ Settings |
| Login JWT + Entra | `/login`, `/api/auth/*` | **Live** | RBAC theo screen |
| Admin Users / Roles | `/admin/*` | **Live** | Postgres auth tables |
| Legacy Social film | `/dashboard` | **Stub** | Mongo đã bỏ → mock empty |
| Legacy Forecast | `/analytics` | **Stub** | Mongo đã bỏ → mock empty |

---

## B2. Marketing View (`/marketing`)

Filter: brand · platform · date range. Data đọc Postgres qua `/api/mkt/*`.

### B2.1. Data blocks

| Block | Component | API | Readiness | Phụ thuộc crawl |
|-------|-----------|-----|-----------|-----------------|
| **Hot News** (24h) | `HotNewsStrip` | `GET /api/mkt/hot-news` | **Live** | News RSS + MXH mentions |
| **Market Overview** (Total / Brand / Topic tabs) | `MarketOverviewCard` | `GET /api/mkt/brand-health` | **Live** | MXH brand mentions + metrics |
| **Share of Voice** + trend chart | `ShareOfVoiceCard`, `SovTrendChart` | brand-health | **Live** | MXH mentions; media mix cần `classify media_type` |
| **Sentiment Analysis** | `SentimentAnalysisCard` | brand-health | **Live** | MXH + classified sentiment |
| **Campaign Tracking** | inline `page.tsx` | `GET /api/mkt/campaigns` | **Live** | Campaign hashtag crawl + `build_campaign_tracking` |
| **Unified Reviews** (App + Maps) | `UnifiedReviewsCard` | `GET /api/mkt/app-reviews` | **Live** | `crawl_app_reviews` + Maps crawl |
| **Review modal** (full list) | overlay trong page | `/api/mkt/app-reviews/list` | **Live** | App reviews trong DB |
| **Feedback Detail drawer** | `FeedbackDetailDrawer` | `GET /api/mkt/feedback-detail` | **Live** | Risky comments / topics / Google reviews |
| Filter bar (brand, platform, date) | `page.tsx` | query params → API | **Live** | — |

**Tổng Marketing data blocks: Live** — code + API + DB đủ; số liệu hiển thị phụ thuộc pipeline MKT chạy.

### B2.2. Settings ⚙️ — Keyword & Alert (`KeywordSettingsDrawer`)

| Tab | Readiness | Backend | Ghi chú |
|-----|-----------|---------|---------|
| **Brand** (keyword CGV/Lotte/GLX…) | **Partial → Live** | `GET/PUT /api/settings` → `listening_queries` Postgres | Cần seed `seed_listening_config.py`; save OK |
| **Exclude** (context sai, spam, ngôn ngữ) | **Live** | `/api/settings` → exclude tables | Save OK |
| **Alert** (ngưỡng buzz/neg/rating) | **Partial** | `/api/settings` lưu threshold | UI + save OK; **chưa có job gửi email/Teams thật** |
| **Phim** (keyword Distribution) | **Partial** | Load từ `/api/dis/films`; **không save** | UI edit được nhưng `handleSave` **không ghi tab Phim** → chưa sync với `films/*.json` crawl |
| **Keyword Config** (bảng BRD) | **Stub** | `KeywordConfigPanel` — **hardcode** | Chỉ hiển thị bảng BR (BRAND/COMPETITOR/GENERIC/CRISIS); **chưa nối DB, chưa save, chưa drive crawl** |

**Gap Settings:** Tab Brand/Exclude đã nối DB. Tab **Keyword Config** + tab **Phim** chưa nối backend / chưa save.

### B2.3. Marketing — việc còn lại

| Việc | Ưu tiên |
|------|---------|
| Nối `KeywordConfigPanel` → DB (hoặc sync từ BR doc) | Cao |
| Save tab **Phim** → `films` / keyword file hoặc bảng listening | Cao |
| Wire alert job (email / Teams webhook) | Trung bình |
| Media mix Paid/Earned/Owned đầy đủ hơn | Trung bình (phụ thuộc classify) |

---

## B3. Distribution View (`/distribution`)

Filter: phim · date · compare đối thủ. Data đọc Postgres qua `/api/dis/overview`.

> **Lưu ý:** Distribution **UI + API đã có** (`distribution/page.tsx` + `/api/dis/overview`). Nhiều block **Partial** vì DIS MXH crawl + heatmap chưa chạy đủ trên server — không phải do thiếu code UI.

### B3.1. Filter & navigation

| Hạng mục | API | Readiness | Ghi chú |
|----------|-----|-----------|---------|
| Film picker | `GET /api/dis/films` | **Live** | Fallback `DEFAULT_FILMS` hardcode khi API fail |
| Date preset (1/7/30/custom) | query → overview | **Live** | |
| Compare phim đối thủ | overview `filmCompare` | **Live** | |
| Export Excel | `GET /api/dis/export` | **Live** | |

### B3.2. Data blocks

| Block | API field | Readiness | Phụ thuộc crawl |
|-------|-----------|-----------|-----------------|
| **Film Overview KPIs** (Buzz, Voices, Views, Intent, Negative) | `overview.kpis` | **Partial** | News → buzz OK; **Views/MXH** cần DIS crawl TT/YT/FB |
| **Buzz & Sentiment Trend** + milestone overlay | `overview.trend`, `milestones` | **Partial** | Trend từ mentions; milestone cần `film_milestones` seed đủ ngày |
| **Film Milestones** timeline | `overview.milestones` | **Partial** | Có UI; trống nếu chưa nhập trailer/premiere/W1 |
| **So Sánh Đa Phim & SoV** | `overview.sov`, `filmCompare` | **Live** | News + MXH đủ phim |
| **Heatmap Buzz theo Khu Vực** | `overview.heatmap` | **Partial** | Cần `crawl_heatmap_data.py` + `classify_mention_region` |
| **Audience Intent & WOM** bars | `overview.intentBars` | **Partial** | Cần DIS MXH + `classify_mention_intent` |
| **Khen / Chê tiêu biểu** | `overview.opinionSamples` | **Partial** | Chủ yếu từ comment MXH; News-only → trống |
| **Top Source theo Tier** | `overview.sources` | **Partial** | Cần comment khán giả từ MXH crawl |

### B3.3. Distribution — tóm tắt block

| Block | Readiness | Lý do nếu Partial |
|-------|-----------|---------------------|
| Film picker + Export | **Live** | API + UI OK |
| KPI cards + delta | **Partial** | Views/MXH thiếu data crawl |
| Lifecycle chart + milestones | **Partial** | Milestone dates / MXH trend |
| Multi-film SoV table | **Live** | News + mentions đủ |
| Heatmap (Buzz/Intent/Screens) | **Partial** | Pipeline heatmap chưa chạy |
| WOM khen/chê | **Partial** | Cần comment MXH + classify intent |
| Settings tab Phim | **Partial** | Load OK, chưa save keyword |

**Kết luận Distribution:** API overview **Live**; UI đủ block; **data thực tế** mới là bottleneck (DIS crawl + heatmap).

### B3.4. Distribution — việc còn lại

| Việc | Ưu tiên |
|------|---------|
| Chạy DIS continuous 5 MXH + News loop trên server | Cao |
| Heatmap pipeline (`crawl_heatmap_data`) | Cao |
| Save keyword Phim từ Settings → sync `films/*.json` | Cao |
| Nhập milestone dates đủ cho 9 phim active | Trung bình |

---

## B4. API routes (tóm tắt)

### Marketing
| Path | Block UI |
|------|----------|
| `/api/mkt/brand-health` | Market Overview, SoV, Sentiment |
| `/api/mkt/campaigns` | Campaign tracking |
| `/api/mkt/app-reviews`, `/list` | Unified Reviews |
| `/api/mkt/hot-news` | Hot News |
| `/api/mkt/feedback-detail` | Detail drawer |

### Distribution
| Path | Block UI |
|------|----------|
| `/api/dis/films` | Film picker, Settings tab Phim |
| `/api/dis/overview` | Toàn bộ blocks Distribution |
| `/api/dis/export` | Export Excel |

### Settings & Auth
| Path | Block UI |
|------|----------|
| `/api/settings` | ⚙️ Brand / Exclude / Alert |
| `/api/auth/*`, `/api/admin/*` | Login, RBAC |

---

## B5. Readiness tổng — Dashboard

| View | UI + API | Data thực tế | Gap chính | Ước lượng |
|------|----------|--------------|-----------|-----------|
| **Marketing** | ✅ Live | 🟡 Phụ thuộc crawl MKT | Keyword Config tab chưa nối DB | **~85%** |
| **Distribution** | ✅ Live | 🟡 News OK; MXH/heatmap thiếu | Crawl DIS chưa chạy đủ server | **~65%** |
| **Settings ⚙️** | 🟡 Partial | — | KwConfig stub; tab Phim chưa save | **~50%** |
| **Legacy /dashboard** | Stub | Không dùng | Bỏ Mongo, chưa migrate | **0%** |

---

## B6. Chạy Dashboard

```bash
cd galaxy-dashboard-social && npm install && npm run db:migrate && npm run dev
# http://localhost:3001 — PGHOST trỏ DB đã import crawl (VPN nếu prod)
```

---

# PHẦN C — Mapping crawl → DB → UI

| Crawl step | Postgres | UI |
|------------|----------|-----|
| MKT MXH mentions | `mentions`, `daily_brand_metrics` | Marketing SoV/Sentiment |
| MKT campaign | `mention_campaigns` | Campaign tracking |
| MKT App/Maps | `app_reviews` | Unified Reviews |
| DIS film MXH + News | `mention_films`, `daily_film_metrics` | Distribution overview |
| DIS intent | `mentions.intent` | WOM khen/chê |

---

## Kết luận

1. **Marketing crawl:** keyword brand (`social_keywords.json`) → Selenium port 9222–9227 → import brand → metrics → `/marketing`
2. **Distribution crawl:** keyword phim (`films/*.json`) → **cùng runner** nhưng port 9232–9236 + `import_film_mentions` → intent/metrics → `/distribution`
3. **Repo source:** [https://github.com/galaxy-cinema/galaxy-social-listening](https://github.com/galaxy-cinema/galaxy-social-listening) · **Repo UI:** [https://github.com/galaxy-cinema/galaxy-dashboard-social](https://github.com/galaxy-cinema/galaxy-dashboard-social)

---

*Cập nhật 2026-08-25.*
