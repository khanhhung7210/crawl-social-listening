#!/usr/bin/env python3
"""
Extract JWT token from GrabFood and test reviews API
"""

import json
import sys
import requests
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright not installed")
    sys.exit(1)

TEST_URL = "https://food.grab.com/vn/vi/restaurant/meili-m%C3%AC-b%C3%B2-%C4%91%C3%A0i-loan-m%C3%AC-s%E1%BB%A7i-c%E1%BA%A3o-mai-v%C4%83n-v%C4%A9nh-delivery/5-C7EZGXTWGVNVV2"
MERCHANT_ID = "5-C7EZGXTWGVNVV2"

captured_jwt = None
captured_headers = {}


def main():
    global captured_jwt, captured_headers

    print("\n" + "=" * 70)
    print("🔑 Extract JWT and Test Reviews API")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='vi-VN',
        )
        page = context.new_page()

        # Capture JWT from requests
        def handle_request(request):
            global captured_jwt, captured_headers
            if 'portal.grab.com' in request.url and 'merchants' in request.url:
                headers = request.headers
                if 'x-hydra-jwt' in headers:
                    captured_jwt = headers['x-hydra-jwt']
                    captured_headers = dict(headers)
                    print(f"\n✅ Captured JWT token!")
                    print(f"   URL: {request.url}")

        page.on('request', handle_request)

        print(f"\n🌐 Loading page to capture JWT...")
        page.goto(TEST_URL, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(3000)

        browser.close()

    if not captured_jwt:
        print("\n❌ Failed to capture JWT token")
        return 1

    print("\n" + "=" * 70)
    print("🧪 Testing APIs with captured JWT")
    print("=" * 70)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'vi',
        'x-hydra-jwt': captured_jwt,
        'x-gfc-country': 'VN',
        'x-country-code': 'VN',
        'Referer': 'https://food.grab.com/',
    }

    # Test 1: Merchant API
    print("\n📡 Test 1: Merchant API")
    merchant_url = f"https://portal.grab.com/foodweb/guest/v2/merchants/{MERCHANT_ID}?latlng=10.7769,106.7009"

    try:
        response = requests.get(merchant_url, headers=headers, timeout=30)
        print(f"   Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            # Save full response
            output_file = Path(__file__).parent / "merchant_api_response.json"
            output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f"   💾 Saved response to: {output_file.name}")

            # Check for reviews
            json_str = json.dumps(data, ensure_ascii=False).lower()
            if any(kw in json_str for kw in ['review', 'rating', 'comment']):
                print("   ✅ Found review-related data in merchant API!")

                # Find reviews structure
                def find_reviews(obj, path="", depth=0):
                    if depth > 10:  # Limit recursion
                        return
                    if isinstance(obj, dict):
                        for key, value in obj.items():
                            if any(kw in key.lower() for kw in ['review', 'rating', 'comment', 'feedback']):
                                print(f"      📌 {path}.{key}")
                                print(f"         Type: {type(value)}")
                                if isinstance(value, (str, int, float, bool)):
                                    print(f"         Value: {value}")
                                elif isinstance(value, (dict, list)):
                                    preview = json.dumps(value, ensure_ascii=False, indent=2)[:200]
                                    print(f"         Value: {preview}...")
                            find_reviews(value, f"{path}.{key}", depth + 1)
                    elif isinstance(obj, list):
                        for i, item in enumerate(obj[:3]):  # Only first 3 items
                            find_reviews(item, f"{path}[{i}]", depth + 1)

                find_reviews(data)
            else:
                print("   ⚠️  No review data in merchant API")
        else:
            print(f"   ❌ Failed: {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 2: Try reviews endpoint
    print("\n📡 Test 2: Reviews API Endpoint")
    reviews_endpoints = [
        f"https://portal.grab.com/foodweb/v2/reviews?merchantID={MERCHANT_ID}",
        f"https://portal.grab.com/foodweb/guest/v2/reviews/{MERCHANT_ID}",
        f"https://portal.grab.com/foodweb/v2/merchants/{MERCHANT_ID}/reviews",
    ]

    for endpoint in reviews_endpoints:
        try:
            print(f"\n   Trying: {endpoint}")
            response = requests.get(endpoint, headers=headers, timeout=30)
            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ SUCCESS! Found reviews API!")

                # Save response
                output_file = Path(__file__).parent / "reviews_api_response.json"
                output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                print(f"   💾 Saved to: {output_file.name}")

                # Show preview
                print(f"\n   Preview:")
                print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
                break
            elif response.status_code == 404:
                print(f"   404 - Endpoint not found")
            else:
                print(f"   {response.status_code} - {response.text[:100]}")
        except Exception as e:
            print(f"   Error: {e}")

    print("\n" + "=" * 70)
    print("✅ TESTING COMPLETE")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
