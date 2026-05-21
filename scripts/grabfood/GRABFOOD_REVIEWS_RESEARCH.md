# GrabFood Reviews Research Summary

## 🎯 Objective
Lấy được reviews (bình luận text) từ GrabFood cho các nhà hàng Meili

## 📊 Các phương pháp đã thử

### 1. Web Scraping (Playwright)
**Status**: ❌ FAILED

**Tested**:
- ✅ Checked HTML content - No reviews
- ✅ Intercepted API calls - Found merchant API
- ✅ Extracted JWT token - Success
- ✅ Tested reviews API endpoints - All 502 (not exist)

**Results**:
- Web API chỉ có `rating` và `ratingDetail`
- KHÔNG có review text/comments
- KHÔNG có reviewer names
- KHÔNG có review dates

**Data available from Web**:
```json
{
  "rating": 4.4,
  "ratingDetail": [
    {"score": 1, "voteCountPercentage": 9},
    {"score": 2, "voteCountPercentage": 3},
    {"score": 3, "voteCountPercentage": 5},
    {"score": 4, "voteCountPercentage": 4},
    {"score": 5, "voteCountPercentage": 77}
  ]
}
```

**API Endpoints Tested**:
- ❌ `https://portal.grab.com/foodweb/v2/reviews?merchantID=xxx` → 502
- ❌ `https://portal.grab.com/foodweb/guest/v2/reviews/xxx` → 502
- ❌ `https://portal.grab.com/foodweb/v2/merchants/xxx/reviews` → 502
- ❌ `https://portal.grab.com/foodweb/guest/v2/reviews?merchantID=xxx` → 502

---

### 2. Mobile App (Appium)
**Status**: 🔄 IN PROGRESS - NEEDS MANUAL VERIFICATION

**Setup**:
- ✅ GrabFood app installed: `com.grab.food.pax`
- ✅ Emulator running
- ✅ Appium server running
- ✅ Test script created

**Current State**:
- App opens to login/home screen
- No reviews visible on home screen
- **Need to manually navigate to restaurant page to verify if reviews exist**

**Next Steps**:
1. Manual test: Search "Meili" → Open restaurant → Check for reviews tab
2. If reviews found: Capture UI elements for automation
3. If no reviews: Confirm reviews not available anywhere

---

## 🤔 Why Reviews Might Not Be Available

### Theory 1: Reviews Only in Consumer App (Not Merchant)
- GrabFood có 2 apps: Consumer app và Merchant app
- Package `com.grab.food.pax` có thể là merchant-facing app
- Reviews có thể chỉ có trong main Grab consumer app

### Theory 2: Reviews Gated Behind Login
- Web không có reviews cho guest users
- App cần login để xem reviews
- API cần different authentication level

### Theory 3: GrabFood Không Có Public Reviews
- GrabFood có thể không public reviews như platforms khác
- Chỉ có internal ratings, không có review comments
- Reviews chỉ visible cho merchant, không cho public

---

## 💡 Recommended Next Actions

### Option A: Verify Reviews Existence Manually
**Priority**: HIGH
**Effort**: 5 minutes

Manual steps:
1. Trong emulator GrabFood app
2. Search "Meili"
3. Open restaurant page
4. Look for "Reviews" or "Đánh giá" tab
5. Screenshot if found

**If reviews found** → Proceed to Option B
**If no reviews** → Proceed to Option C

---

### Option B: Automate Review Extraction (If Reviews Exist)
**Prerequisites**: Reviews confirmed in Option A

**Approach**:
1. Use Appium to automate navigation
2. Intercept app API calls with mitmproxy
3. Extract review data from API
4. Build crawler script

**Estimated Effort**: 1-2 days

**Pros**:
- Get full review text + metadata
- Automated solution

**Cons**:
- Complex setup
- Requires app navigation automation
- API may be protected

---

### Option C: Accept Rating-Only Data
**Prerequisites**: Reviews confirmed NOT available

**What We Can Get**:
- Overall rating (e.g., 4.4 stars)
- Rating distribution (% of 1-5 stars)
- Restaurant info (name, address, menu, etc.)

**Pros**:
- Already implemented and working
- Reliable data from web API
- No app automation needed
- Fast execution

**Cons**:
- No review text/comments
- Cannot do sentiment analysis on text
- Less insight than full reviews

**Implementation**: Already done in `grabfood_detail_runner.py`

---

### Option D: Focus on ShopeeFood Instead
**Rationale**: ShopeeFood confirmed to have reviews in app

**Pros**:
- Reviews confirmed available
- Emulator + Appium setup done
- Can extract review text + ratings

**Cons**:
- Different platform
- Manual navigation required (hybrid approach)

---

## 📁 Files Created

1. `scripts/grabfood/intercept_api.py` - Intercept web API calls
2. `scripts/grabfood/check_reviews_in_html.py` - Check HTML for reviews
3. `scripts/grabfood/extract_jwt_and_test_api.py` - Extract JWT and test APIs
4. `scripts/grabfood/grab_reviews_with_playwright.py` - Playwright with JWT
5. `scripts/grabfood/test_grab_api.py` - Simple API test
6. `scripts/grabfood/grabfood_app_explore_reviews.py` - Explore app UI
7. `scripts/grabfood/merchant_full_response.json` - Sample API response
8. `scripts/grabfood/captured_api_requests.json` - Intercepted requests

---

## 🎯 Recommendation

**Immediate**: Complete **Option A** (manual verification) - takes 5 minutes

**Then**:
- **If reviews found** → Proceed with Option B (app automation)
- **If no reviews** → Choose between:
  - Option C: Accept rating-only data (fastest, already done)
  - Option D: Switch to ShopeeFood (more effort, but full reviews)

---

## 📝 Notes

- GrabFood web API authentication uses JWT tokens with 10-minute expiration
- App package: `com.grab.food.pax`
- Main API: `https://portal.grab.com/foodweb/guest/v2/merchants/{merchantID}`
- Rating data is reliable and already extractable
- Full review text availability is UNCONFIRMED pending manual test

