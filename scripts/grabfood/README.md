# GrabFood Web Crawler

Extract restaurant data, ratings, reviews, and order counts from GrabFood website using Playwright.

## 🎯 Overview

**GrabFood** has a **web interface** at https://food.grab.com/ - much simpler than app-based crawling!

**Approach:** Automated web scraping with Playwright (same as Facebook, Instagram, etc.)

## 📋 Prerequisites

### 1. Python Dependencies

```bash
pip3 install playwright
playwright install chromium
```

### 2. That's it!

No emulator, no Appium, no manual navigation needed! ✅

## 🚀 Usage

### Test Configuration

Before crawling, verify your configuration:

```bash
python3 scripts/grabfood/test_location_config.py
```

**What it shows:**
- Default location settings
- All configured locations (enabled/disabled)
- Search keywords
- Crawler settings
- Crawl plan (how many searches will be performed)

**Example output:**
```
CRAWL PLAN
Enabled locations: 2
Search keywords:   2
Total searches:    4

Crawl sequence:
  - Quận 1 × "Meili"
  - Quận 1 × "美粒"
  - Quận 3 × "Meili"
  - Quận 3 × "美粒"
```

### Two-Stage Crawling

#### Stage 1: Search & List Restaurants

```bash
python3 scripts/grabfood/grabfood_search_runner.py
```

**What it does:**
- Searches for "Meili" and "美粒" on GrabFood
- Extracts all matching restaurants
- Gets: name, rating, reviews, URL, delivery info
- Output: `data/grabfood/raw/grabfood_search_YYYYMMDD_HHMMSS.json`

**Output Example:**
```json
[
  {
    "platform": "grabfood",
    "restaurant_id": "meili_taiwanese_food",
    "name": "Meili - Taiwanese Food",
    "url": "https://food.grab.com/vn/vi/restaurant/meili-...",
    "rating": 4.8,
    "review_count": "150+",
    "delivery_time": "30-40 min",
    "distance": "2.5 km",
    "promo": "Giảm 20%",
    "crawled_at": "2026-05-20T..."
  }
]
```

#### Stage 2: Extract Menu & Orders

```bash
python3 scripts/grabfood/grabfood_detail_runner.py
```

**What it does:**
- Loads latest search results
- Visits each restaurant page
- Scrolls through full menu
- Extracts dishes with order counts, prices
- Output: `data/grabfood/raw/grabfood_details_YYYYMMDD_HHMMSS.json`

**Output Example:**
```json
[
  {
    "platform": "grabfood",
    "restaurant_id": "meili_taiwanese_food",
    "name": "Meili - Taiwanese Food",
    "rating": 4.8,
    "dishes": [
      {
        "name": "Pao gà Phô Mai Béo Ngậy",
        "price": "45,000₫",
        "order_count": "500+ orders",
        "description": "Delicious cheese chicken bao...",
        "image_url": "https://..."
      },
      {
        "name": "Mì xá xíu súp",
        "price": "65,000₫",
        "order_count": "300+ orders"
      }
    ],
    "detail_crawled_at": "2026-05-20T..."
  }
]
```

### Full Pipeline

```bash
# Step 1: Crawl
python3 scripts/grabfood/grabfood_search_runner.py
python3 scripts/grabfood/grabfood_detail_runner.py

# Step 2: Process
python3 scripts/grabfood/grabfood_format_job.py
python3 scripts/grabfood/grabfood_keyword_filter_job.py

# Step 3: Sync to MongoDB
python3 scripts/grabfood/grabfood_mongodb_sync.py
```

**One-liner:**
```bash
python3 scripts/grabfood/grabfood_search_runner.py && \
python3 scripts/grabfood/grabfood_detail_runner.py && \
python3 scripts/grabfood/grabfood_format_job.py && \
python3 scripts/grabfood/grabfood_keyword_filter_job.py && \
python3 scripts/grabfood/grabfood_mongodb_sync.py
```

## 📊 Data Flow

```
grabfood_search_runner.py
├─ Search "Meili" on GrabFood
├─ Extract restaurant cards
└─ Save to grabfood_search_YYYYMMDD.json
         ↓
grabfood_detail_runner.py
├─ Load search results
├─ Visit each restaurant page
├─ Extract full menu with order counts
└─ Save to grabfood_details_YYYYMMDD.json
         ↓
grabfood_format_job.py
├─ Parse prices, order counts
├─ Normalize restaurant names
├─ Extract branch info
└─ Save to grabfood_formatted.json
         ↓
grabfood_keyword_filter_job.py
├─ Filter by "Meili" keywords
├─ Tag dishes with keywords
└─ Save to grabfood_filtered.json
         ↓
grabfood_mongodb_sync.py
├─ Upsert grabfood_restaurants
├─ Upsert grabfood_dishes
├─ Insert rating snapshots
└─ MongoDB ready!
```

## 🔍 Extraction Details

### Restaurant Card Extraction

**Selectors tried (in order):**
1. `article`
2. `[class*="RestaurantListCol"]`
3. `[class*="restaurant-item"]`
4. `[data-testid*="restaurant"]`

**Data extracted:**
- Restaurant name (h2/h3)
- Rating (0.0-5.0 pattern)
- Review count (e.g., "150+ đánh giá")
- Delivery time (e.g., "30-40 min")
- Distance (e.g., "2.5 km")
- Promo (e.g., "Giảm 20%")
- Restaurant URL (for detail page)

### Dish Extraction

**Selectors tried:**
1. `[class*="MenuItem"]`
2. `[class*="DishCard"]`
3. `[class*="dish-item"]`
4. `[data-testid*="menu-item"]`
5. `article` / `[role="article"]`

**Data extracted:**
- Dish name (h3/h4)
- Price (e.g., "45,000₫")
- Order count (e.g., "500+ orders")
- Description
- Image URL

## 📦 MongoDB Collections

### grabfood_restaurants

```javascript
{
  restaurant_id: "meili_taiwanese_food_20260520",
  platform: "grabfood",
  restaurant_name: "Meili - Taiwanese Food",
  restaurant_name_normalized: "Meili Taiwanese Food",
  branch: "District 1",
  rating: 4.8,
  review_count: 150,
  review_count_raw: "150+",
  url: "https://food.grab.com/vn/vi/restaurant/...",
  delivery_time: "30-40 min",
  distance: "2.5 km",
  crawled_at: ISODate("..."),
  updated_at: ISODate("...")
}
```

### grabfood_dishes

```javascript
{
  restaurant_id: "meili_taiwanese_food_20260520",
  dish_id: "pao_ga_pho_mai",
  dish_name: "Pao gà Phô Mai Béo Ngậy",
  price_raw: "45,000₫",
  price_vnd: 45000,
  order_count_raw: "500+ orders",
  order_count_min: 500,
  description: "...",
  image_url: "https://...",
  crawled_at: ISODate("..."),
  updated_at: ISODate("...")
}
```

### grabfood_ratings (Time Series)

```javascript
{
  restaurant_id: "meili_taiwanese_food_20260520",
  platform: "grabfood",
  rating: 4.8,
  review_count: 150,
  recorded_at: ISODate("...")
}
```

## ⚙️ Configuration

### Location-Based Configuration

**Configuration File:** `data/grabfood/config/location_config.json`

```json
{
  "default_location": {
    "address": "Quận 1, Thành phố Hồ Chí Minh",
    "latitude": 10.7769,
    "longitude": 106.7009,
    "description": "District 1, HCMC - Default location"
  },
  "locations": [
    {
      "id": "hcmc_district_1",
      "name": "Quận 1",
      "address": "Quận 1, Thành phố Hồ Chí Minh",
      "latitude": 10.7769,
      "longitude": 106.7009,
      "enabled": true
    },
    {
      "id": "hcmc_district_3",
      "name": "Quận 3",
      "address": "Quận 3, Thành phố Hồ Chí Minh",
      "latitude": 10.7756,
      "longitude": 106.6878,
      "enabled": true
    }
  ],
  "search_keywords": ["Meili", "美粒"],
  "crawler_settings": {
    "max_restaurants_per_search": 50,
    "scroll_count": 5,
    "delay_between_requests": 2,
    "headless": false
  }
}
```

**How it works:**
1. Crawler loads enabled locations from config
2. For each location, sets browser geolocation (latitude/longitude)
3. Searches all keywords in that location context
4. Results include location metadata (location_id, location_name, coordinates)
5. Different locations may show different restaurants/rankings

**To add new locations:**
1. Find coordinates for your location (use Google Maps)
2. Add to `locations` array in config
3. Set `enabled: true` to activate
4. Run crawler - it will automatically crawl all enabled locations

### Search Keywords

Edit `search_keywords` in `location_config.json`:

```json
"search_keywords": ["Meili", "美粒", "另一個關鍵詞"]
```

### Filter Keywords

Edit in `grabfood_keyword_filter_job.py`:

```python
GRABFOOD_KEYWORDS = {
    "restaurants": ["Meili", "美粒", "meili", "MEILI"],
    "dishes": ["mì", "pao", "bánh bao", "gà", "bò", "taiwanese"],
    "exclude": ["grab express", "grabmart", "grabpay"]
}
```

### Crawler Settings

Edit `crawler_settings` in `location_config.json`:

```json
"crawler_settings": {
  "max_restaurants_per_search": 50,  // Limit results per keyword+location
  "scroll_count": 5,                  // Number of scrolls to load more results
  "delay_between_requests": 2,        // Seconds between searches (rate limiting)
  "headless": false                   // Set true for server/production
}
```

**Headless mode:**
- `false`: Opens visible browser (good for debugging)
- `true`: Runs in background (faster, for production)

## ⏱️ Performance

| Stage | Time | Output |
|-------|------|--------|
| Search (Stage 1) | ~10 seconds | Restaurant list |
| Details (Stage 2) | ~5 sec per restaurant | Full menu |
| Format | ~1 second | Normalized data |
| Filter | ~1 second | Filtered data |
| MongoDB Sync | ~2 seconds | Database ready |
| **Total (4 restaurants)** | **~35 seconds** | Complete |

## 🆚 Comparison: Web vs App

| Aspect | GrabFood Web | ShopeeFood App |
|--------|--------------|----------------|
| **Tool** | Playwright | Appium |
| **Setup** | pip install playwright | Emulator + Appium |
| **Navigation** | Automated | Manual |
| **Reliability** | ⭐⭐⭐⭐ Good | ⭐⭐⭐ Fair |
| **Speed** | Fast (~35s for 4) | Slow (~2min for 4) |
| **Maintenance** | Easy | Hard |
| **Difficulty** | ⭐⭐ Easy | ⭐⭐⭐⭐⭐ Very Hard |

**Winner: Web approach! 🎉**

## 🐛 Troubleshooting

### Issue 1: No restaurants found

**Cause:** Page structure changed or anti-bot detection

**Solution:**
```bash
# Check debug HTML file
cat data/grabfood/raw/debug_page_Meili.html | grep -i "restaurant"

# Try adjusting selectors in grabfood_search_runner.py
```

### Issue 2: No dishes extracted

**Cause:** Dish selectors outdated

**Solution:**
1. Open restaurant page manually
2. Inspect HTML structure
3. Update selectors in `grabfood_detail_runner.py`

### Issue 3: Playwright timeout

**Cause:** Slow internet or page loading

**Solution:**
```python
# Increase timeout in code
page.goto(url, wait_until='networkidle', timeout=60000)  # 60s
```

### Issue 4: Anti-bot detection

**Symptoms:**
- Captcha appears
- Page redirects
- Empty results

**Solutions:**
1. **Add delays:**
   ```python
   time.sleep(5)  # Between requests
   ```

2. **Rotate user agents:**
   ```python
   user_agents = [
       'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...',
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...'
   ]
   ```

3. **Use residential proxy** (if needed)

## 📈 Monitoring

### Check crawl results:

```bash
# Count restaurants found
cat data/grabfood/raw/grabfood_search_*.json | jq '. | length'

# View restaurant names
cat data/grabfood/raw/grabfood_details_*.json | jq '.[] | {name: .name, dishes: .dishes | length}'

# Check MongoDB
mongo "$MONGODB_URI" --eval "db.grabfood_restaurants.count()"
```

### Logs:

```bash
# Redirect output to log
python3 scripts/grabfood/grabfood_search_runner.py > logs/grabfood.log 2>&1
```

## 🔄 Update Frequency

**Recommended:**
- **Weekly**: Full crawl (search + details)
- **Daily**: Quick search to check new restaurants
- **Monthly**: Verify data accuracy

**Rationale:** Order counts and ratings change frequently enough to warrant weekly updates

## 🚫 Limitations

1. **Public Data Only**
   - No login required = no personalized data
   - Can't see order history, favorites

2. **Order Count Format**
   - Shows "500+" not exact
   - Only get minimum threshold

3. **Search Results**
   - Location-based (may vary by IP)
   - Limited to first N results

4. **Rate Limiting**
   - Too many requests may trigger detection
   - Add delays between requests

5. **Page Structure Changes**
   - GrabFood may update UI
   - Selectors need maintenance

## 💡 Tips

1. **Run headless=False first**
   - See what's happening
   - Debug visually

2. **Check debug files**
   - If extraction fails, check `debug_page_*.html`
   - Inspect actual HTML structure

3. **Use latest search results**
   - Detail runner auto-loads latest search file
   - No need to specify manually

4. **Monitor for changes**
   - If suddenly no data, check page structure
   - Update selectors as needed

5. **Batch processing**
   - Process multiple keywords in one run
   - Automatic deduplication

## 🎯 Example Workflow

**First time setup:**
```bash
# Install dependencies
pip3 install playwright
playwright install chromium
```

**Regular crawl (weekly):**
```bash
# Full automated pipeline
./scripts/grabfood/run_grabfood_pipeline.sh
```

**Quick check:**
```bash
# Just search, see what's new
python3 scripts/grabfood/grabfood_search_runner.py

# View results
cat data/grabfood/raw/grabfood_search_*.json | jq '.[] | {name, rating, reviews: .review_count}'
```

## 📞 Support

**Issues:** See main project README
**Documentation:** SOCIAL_LISTENING_COMPLETE_GAPS.md

---

**Created:** 2026-05-20
**Version:** 2.0 (Web-based)
**Status:** ✅ Production Ready
**Approach:** Automated web scraping (much better than app!) 🎉
