# Hiện trạng Source — Galaxy Social Listening (Crawl)

> Ngày cập nhật: **2026-08-25**  
> Phạm vi: repo **source / crawl** (`social-listening`)  
> File này mô tả hiện trạng hệ thống lấy data MXH + review, không gồm UI dashboard.

---

## 1. Link repo Source

| Mục | Giá trị |
|-----|---------|
| **Repo Source (crawl)** | [https://github.com/galaxy-cinema/galaxy-social-listening](https://github.com/galaxy-cinema/galaxy-social-listening) |
| Tên GitHub | `galaxy-cinema/galaxy-social-listening` |
| Local folder | `social-listening/` |
| Vai trò | Crawl MXH / News / Maps / App reviews → parse/filter → import Postgres → classify / metrics |
| Stack | Python + Selenium (Chrome remote debug) + Postgres |
| DB | `galaxy_social_listening` / schema `galaxy_sl` |
| Schema SQL | `sql/galaxy_mkt_schema.sql`, `sql/galaxy_dis_schema.sql` |

Repo UI (tham chiếu, không thuộc source): [https://github.com/galaxy-cinema/galaxy-dashboard-social](https://github.com/galaxy-cinema/galaxy-dashboard-social) — `galaxy-dashboard-social` → màn `/marketing`, `/distribution`.

---

## 2. Kiến trúc hiện tại (tóm tắt)

```text
Keyword config
  ├─ Marketing (brand rạp): data/shared/social_keywords.json
  └─ Distribution (phim):   data/distribution/films/<slug>.json + film_catalog.json
        ↓
Crawl raw (Selenium / RSS / Store)
        ↓
Search filter → Detail → Format → Keyword filter
        ↓
Import Postgres (scripts/shared/*)
        ↓
Classify + recompute metrics (MKT / DIS)
        ↓
Dashboard đọc DB qua API (/api/mkt/*, /api/dis/*)
```

Hai nhánh chạy song song trên cùng DB:

| Nhánh | Mục tiêu | Entry chính |
|-------|----------|-------------|
| **Marketing** | Brand health rạp (Galaxy vs CGV / Lotte / Beta / BHD…) | `scripts/marketing/run_full_pipeline.py`, `run_continuous.py` |
| **Distribution** | Buzz / WOM theo phim chiếu | `scripts/distribution/run_by_platform.py`, `run_distribution_pipeline.py` |

---

## 3. Inventory Source (đang có code)

| Source | Loại | Cách lấy | Chrome port (MKT) | Port DIS | Trạng thái code |
|--------|------|----------|-------------------|----------|-----------------|
| Facebook | MXH | Selenium self-crawl | 9226 | 9236 | Có pipeline đầy đủ |
| Instagram | MXH | Selenium self-crawl | 9224 | 9234 | Có pipeline đầy đủ |
| Threads | MXH | Selenium self-crawl | 9222 | 9232 | Có pipeline đầy đủ |
| TikTok | MXH | Selenium self-crawl | 9223 | 9233 | Có pipeline đầy đủ |
| YouTube | MXH | Selenium self-crawl | 9225 | 9235 | Có pipeline đầy đủ |
| Google Maps | Review rạp | Selenium self-crawl | 9227 | — | Có (marketing/reviews) |
| Google News | Tin | RSS (không Chrome) | — | — | Có (MKT + DIS) |
| App Store / Play | App review | Live crawl store | — | — | Có (`crawl_app_reviews`) |
| GBO Share | Nội bộ | Import CSV | — | — | Có (`import_gbo_share`) |

Pipeline chung:

```text
Crawl raw → (Search filter) → Detail crawl → Format/parse → Keyword filter → Import Postgres → Classify / metrics
```

---

## 4. Hiện trạng vận hành

### 4.1 Marketing (brand)

- Keyword brand: `data/shared/social_keywords.json` (`film_title`: Galaxy Cinema)
- Có keyword campaign / hashtag / branch (tên rạp) / exclude
- Continuous: mỗi platform 1 terminal + 1 Chrome debug profile đã login
- Windows Server: `scripts/windows/run_social_listening_daily.ps1` (chạy song song theo port)
- Output: `data/<platform>/processed/.../*_keyword_mentions.json` → bảng `mentions` / metrics brand

### 4.2 Distribution (phim)

- Catalog: `data/distribution/film_catalog.json`
- Phim trong catalog (cập nhật 2026-08-25): **10** phim — **9 active**, 1 inactive (`lilo_stitch`)
  - Active: The Odyssey, Minion, Người Nhện: Khởi Đầu Mới, Nghỉ Hè Sợ Nghỉ Hưu, Ám, Thư Tình Gửi Ngoại, Conan, Quý Tử Vượt Giàu, Hộ Linh Tráng Sĩ
- Seed / schema: `scripts/distribution/seed_films.py`
- Continuous theo platform: `run_by_platform.py <platform> --all-active --continuous --import-db`
- Metrics / intent: `classify_mention_intent`, `recompute_daily_film_metrics`

### 4.3 Data phụ trợ đã export gần đây

| File | Nội dung |
|------|----------|
| `exports/marketing/appstore_play_maps_raw_20260824.xlsx` | App Store + Play + Google Maps reviews (raw) |
| `exports/marketing/appstore_play_maps_alltime_20260824.xlsx` | Bản all-time cùng nhóm nguồn |
| Các CSV/xlsx trong `exports/marketing/` | Dump Mentions / posts / comments theo platform (FB, IG, Threads…) |

---

## 5. Điểm mạnh / hạn chế hiện tại

| Hạng mục | Hiện trạng |
|----------|------------|
| Kiểm soát data | Self-crawl → schema Postgres riêng → UI custom |
| Chi phí vendor | Thấp (không phụ thuộc Awario/Brand24 cho ingest chính) |
| Phụ thuộc Chrome session | Cao với FB/IG/Threads/TikTok — cần profile login ổn định |
| DOM đổi / timeout | Có rủi ro partial crawl (search/detail timeout) |
| Ngày đăng bài | Đã xử lý/cải thiện parse date (FB…); vẫn cần giám sát quality |
| Ngày tạo tài khoản social | Chỉ YouTube public ổn định; FB/IG/Threads/TikTok gần như không lấy hàng loạt được |
| Phân tách MKT vs DIS | Đã tách folder scripts + keyword + metrics |

---

## 6. Tài liệu trong repo Source

| File | Nội dung |
|------|----------|
| `README.md` | Setup, crawl từng platform, import DB |
| `scripts/README.md` | Cây scripts MKT/DIS, continuous, ports |
| `scripts/distribution/README.md` | Pipeline Distribution |
| `scripts/distribution/SERVER_CRAWL.md` | Hướng dẫn crawl trên server |
| `sql/galaxy_mkt_schema.sql` | Schema Brand Health |
| `sql/galaxy_dis_schema.sql` | Schema phim / milestones |

---

## 7. Kết luận ngắn (gửi nội bộ)

1. **Source of truth code crawl:** [https://github.com/galaxy-cinema/galaxy-social-listening](https://github.com/galaxy-cinema/galaxy-social-listening)
2. Hệ đã cover **MXH chính + News + Maps + App reviews**, chia **Marketing (brand)** và **Distribution (phim)**.
3. Vận hành thực tế phụ thuộc **Chrome debug + session login** trên máy/server crawl; News/App/GBO nhẹ hơn.
4. UI đọc data qua repo dashboard riêng (`galaxy-dashboard-social`), không nằm trong repo source.

---

*Tạo tự động từ workspace Social Listening — 2026-08-25.*
