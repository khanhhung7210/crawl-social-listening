#!/usr/bin/env python3
"""
Check if GrabFood page has reviews in HTML
"""

import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright not installed")
    sys.exit(1)

TEST_URL = "https://food.grab.com/vn/vi/restaurant/meili-m%C3%AC-b%C3%B2-%C4%91%C3%A0i-loan-m%C3%AC-s%E1%BB%A7i-c%E1%BA%A3o-mai-v%C4%83n-v%C4%A9nh-delivery/5-C7EZGXTWGVNVV2"

def main():
    print("\n" + "=" * 70)
    print("🔍 Checking for reviews in HTML")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='vi-VN',
        )

        print(f"\n🌐 Loading: {TEST_URL}")
        page.goto(TEST_URL, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(5000)

        # Scroll to bottom
        print("📜 Scrolling...")
        for i in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(1000)

        # Get full body text
        body_text = page.locator("body").inner_text()

        print("\n" + "=" * 70)
        print("🔍 SEARCHING FOR REVIEWS IN PAGE TEXT")
        print("=" * 70)

        # Check for review keywords
        review_keywords = ['đánh giá', 'review', 'bình luận', 'nhận xét', 'ratings', 'feedback']
        found_keywords = [kw for kw in review_keywords if kw in body_text.lower()]

        if found_keywords:
            print(f"✅ Found review keywords: {', '.join(found_keywords)}")

            # Try to find review section
            review_selectors = [
                '[data-testid*="review"]',
                '[class*="review"]',
                '[class*="Review"]',
                '[class*="rating"]',
                '[class*="Rating"]',
                'text=Đánh giá',
                'text=Reviews',
            ]

            for selector in review_selectors:
                try:
                    elements = page.query_selector_all(selector)
                    if elements:
                        print(f"\n📌 Found {len(elements)} elements with selector: {selector}")
                        for idx, elem in enumerate(elements[:3]):
                            text = elem.inner_text()[:200]
                            print(f"   [{idx}] {text}...")
                except Exception:
                    pass
        else:
            print("❌ No review keywords found in page text")

        # Save HTML for analysis
        html_content = page.content()
        output_file = Path(__file__).parent / "grabfood_page_with_reviews.html"
        output_file.write_text(html_content, encoding='utf-8')
        print(f"\n💾 Saved HTML to: {output_file}")

        # Check for review count in text
        import re
        rating_match = re.search(r'(\d+[\.,]?\d*)\s*(?:đánh giá|reviews?)', body_text, re.IGNORECASE)
        if rating_match:
            print(f"\n⭐ Found review count mention: {rating_match.group(0)}")

        browser.close()

    print("=" * 70)
    return 0

if __name__ == "__main__":
    sys.exit(main())
