# ShopeeFood Data Extraction Guide

## 🎯 Problem

After 200+ automation attempts, **automated navigation to restaurants is unreliable** due to:
- React Native dynamic UI
- Changing element positions
- Unstable clickable areas

## ✅ Working Solution: Hybrid Approach

**You control navigation** (reliable) + **Script extracts data** (fast)

---

## 📋 Step-by-Step Workflow

### Prerequisites
- Emulator running with ShopeeFood app
- Appium server running: `appium --allow-cors`

### Extraction Process

#### For Each Restaurant:

**1. Navigate Manually in Emulator**
   - Click on ShopeeFood search bar
   - Type "Meili"
   - Click on desired restaurant (e.g., "Meili Nguyễn Văn Khối")
   - Wait for restaurant page to fully load (menu visible)

**2. Run Extraction Script**
```bash
python3 scripts/shopeefood/extract_current_page.py
```

**3. Check Output**
   - Script shows: restaurant name, rating, review count, dishes found
   - Data appends to: `data/shopeefood/raw/shopeefood_manual_extraction.json`

**4. Navigate to Next Restaurant**
   - Press back button in emulator
   - Click on next Meili restaurant
   - Repeat step 2

---

## 🎬 Example Session

```bash
# Terminal 1: Start Appium
appium --allow-cors

# Terminal 2: Extract data

# [Navigate manually to: Meili Nguyễn Văn Khối]
python3 scripts/shopeefood/extract_current_page.py
# ✅ Extracted: Rating 4.9, Reviews: 50+, Dishes: 25

# [Navigate manually to: Meili Ung Văn Khiêm]
python3 scripts/shopeefood/extract_current_page.py
# ✅ Extracted: Rating 4.6, Reviews: 30+, Dishes: 23

# [Navigate manually to: Meili Nhiêu Tứ]
python3 scripts/shopeefood/extract_current_page.py
# ✅ Extracted: Rating 4.8, Reviews: 40+, Dishes: 24

# [Navigate manually to: Meili Mai Văn Vinh]
python3 scripts/shopeefood/extract_current_page.py
# ✅ Extracted: Rating 4.7, Reviews: 35+, Dishes: 22
```

---

## 📊 What Gets Extracted

For each restaurant:
```json
{
  "platform": "shopeefood",
  "name": "Meili - Mì Bò Đài Loan & Bánh Bao Kẹp - Nguyễn Văn Khối",
  "rating": 4.9,
  "review_count": "50+ Reviews",
  "crawled_at": "2026-05-20T...",
  "dishes": [
    {
      "name": "Mì xá xíu súp cơn hồ / 餛飩叉燒麵湯",
      "sold_count": "500+"
    },
    {
      "name": "Pao gà Phô Mai Béo Ngậy / 起司雞肉包",
      "sold_count": "300+"
    }
    // ... more dishes
  ]
}
```

---

## ⏱️ Time Estimate

- **Manual navigation per restaurant:** 10-15 seconds
- **Automated extraction per restaurant:** 15-20 seconds
- **Total per restaurant:** ~30 seconds
- **For 4 Meili restaurants:** ~2 minutes total

---

## 🚫 Why Full Automation Failed

Attempted approaches (200+ attempts):
1. ❌ ADB tap coordinates - positions change between runs
2. ❌ Appium element clicks - parent elements not clickable
3. ❌ Deep links - open browser instead of app
4. ❌ UIAutomator selectors - elements not stable
5. ❌ Text-based finding - triggers search bar
6. ❌ Hybrid tap approaches - same coordinate issues

**Root cause:** React Native's dynamic layout system makes automation extremely unreliable.

---

## 💡 Tips

- Keep emulator visible while running script
- Don't touch emulator while script is scrolling
- If extraction fails, just run script again
- Data appends, so safe to re-run
- Check `data/shopeefood/raw/shopeefood_manual_extraction.json` after each run

---

## 🎯 Result

After completing all 4 restaurants, you'll have:
- ✅ Complete restaurant data (ratings, reviews)
- ✅ All dishes with sold counts
- ✅ 100% accuracy (you verified each restaurant)
- ✅ Ready for formatting/analysis pipeline
