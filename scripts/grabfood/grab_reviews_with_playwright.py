#!/usr/bin/env python3
"""
Get GrabFood reviews using Playwright context (keeps all cookies & auth)
"""

import json
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright not installed")
    sys.exit(1)

TEST_URL = "https://food.grab.com/vn/vi/restaurant/meili-m%C3%AC-b%C3%B2-%C4%91%C3%A0i-loan-m%C3%AC-s%E1%BB%A7i-c%E1%BA%A3o-mai-v%C4%83n-v%C4%A9nh-delivery/5-C7EZGXTWGVNVV2"
MERCHANT_ID = "5-C7EZGXTWGVNVV2"


def main():
    print("\n" + "=" * 70)
    print("🔍 GrabFood Reviews Extractor (Playwright)")
    print("=" * 70)

    captured_api_data = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='vi-VN',
        )

        # Capture API responses
        def handle_response(response):
            if 'portal.grab.com' in response.url and 'merchants' in response.url:
                print(f"\n📡 Captured API: {response.url}")
                print(f"   Status: {response.status}")

                if response.status == 200:
                    try:
                        data = response.json()
                        captured_api_data['merchant'] = data
                        print(f"   ✅ Got merchant data!")

                        # Save immediately
                        output_file = Path(__file__).parent / "merchant_full_response.json"
                        output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                        print(f"   💾 Saved to: {output_file.name}")
                    except Exception as e:
                        print(f"   ⚠️  Could not parse JSON: {e}")

        page = context.new_page()
        page.on('response', handle_response)

        print(f"\n🌐 Loading: {TEST_URL}")
        page.goto(TEST_URL, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(5000)

        # Try to find and click reviews tab
        print("\n🔍 Looking for reviews tab...")
        review_tab_selectors = [
            'text=Reviews',
            'text=Đánh giá',
            'text=Review',
            '[role="tab"]:has-text("Review")',
            '[role="tab"]:has-text("Đánh giá")',
            'button:has-text("Đánh giá")',
            'button:has-text("Review")',
        ]

        for selector in review_tab_selectors:
            try:
                elements = page.query_selector_all(selector)
                if elements:
                    print(f"   ✅ Found reviews tab: {selector}")
                    elements[0].click()
                    print(f"   🖱️  Clicked reviews tab")
                    page.wait_for_timeout(3000)
                    break
            except Exception as e:
                pass

        # Try API calls directly using Playwright context
        print("\n📡 Testing API endpoints with Playwright context...")

        api_endpoints = [
            f"https://portal.grab.com/foodweb/v2/reviews?merchantID={MERCHANT_ID}",
            f"https://portal.grab.com/foodweb/guest/v2/reviews/{MERCHANT_ID}",
            f"https://portal.grab.com/foodweb/v2/merchants/{MERCHANT_ID}/reviews",
            f"https://portal.grab.com/foodweb/guest/v2/reviews?merchantID={MERCHANT_ID}",
        ]

        for endpoint in api_endpoints:
            try:
                print(f"\n   Testing: {endpoint}")
                api_response = context.request.get(endpoint)
                print(f"   Status: {api_response.status}")

                if api_response.status == 200:
                    data = api_response.json()
                    print(f"   ✅ SUCCESS! Got reviews data!")

                    # Save reviews
                    output_file = Path(__file__).parent / "grab_reviews_success.json"
                    output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                    print(f"   💾 Saved to: {output_file.name}")

                    # Show preview
                    preview = json.dumps(data, indent=2, ensure_ascii=False)[:800]
                    print(f"\n   📋 Preview:\n{preview}...")

                    captured_api_data['reviews'] = data
                    break
                elif api_response.status == 404:
                    print(f"   404 - Not found")
                else:
                    print(f"   {api_response.status} - Failed")
            except Exception as e:
                print(f"   ❌ Error: {e}")

        browser.close()

    # Analyze captured data
    print("\n" + "=" * 70)
    print("📊 ANALYSIS")
    print("=" * 70)

    if 'merchant' in captured_api_data:
        merchant_data = captured_api_data['merchant']
        print("\n✅ Merchant API Data:")

        # Look for review-related fields
        def find_review_fields(obj, path="", depth=0):
            if depth > 8:
                return []
            results = []
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if any(kw in key.lower() for kw in ['review', 'rating', 'comment', 'feedback', 'star']):
                        results.append({
                            'path': f"{path}.{key}",
                            'type': type(value).__name__,
                            'value': value if not isinstance(value, (dict, list)) else f"{type(value).__name__} with {len(value)} items"
                        })
                    results.extend(find_review_fields(value, f"{path}.{key}", depth + 1))
            elif isinstance(obj, list):
                for i, item in enumerate(obj[:3]):
                    results.extend(find_review_fields(item, f"{path}[{i}]", depth + 1))
            return results

        review_fields = find_review_fields(merchant_data)
        if review_fields:
            print("   Found review-related fields:")
            for field in review_fields[:20]:  # Show first 20
                print(f"     • {field['path']}")
                print(f"       Type: {field['type']}, Value: {field['value']}")
        else:
            print("   ⚠️  No review fields found in merchant API")

    if 'reviews' in captured_api_data:
        print("\n✅ Reviews API Data:")
        reviews_data = captured_api_data['reviews']
        print(f"   Type: {type(reviews_data)}")
        if isinstance(reviews_data, dict):
            print(f"   Keys: {list(reviews_data.keys())}")
        elif isinstance(reviews_data, list):
            print(f"   Items: {len(reviews_data)}")
    else:
        print("\n❌ No reviews API found")

    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
