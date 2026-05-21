#!/usr/bin/env python3
"""
GrabFood API Interceptor - Capture all network requests to find reviews API
"""

import json
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright not installed")
    sys.exit(1)

# Test restaurant: MeiLi - Mì Bò Đài Loan & Mì Sủi Cảo - Mai Văn Vĩnh
TEST_URL = "https://food.grab.com/vn/vi/restaurant/meili-m%C3%AC-b%C3%B2-%C4%91%C3%A0i-loan-m%C3%AC-s%E1%BB%A7i-c%E1%BA%A3o-mai-v%C4%83n-v%C4%A9nh-delivery/5-C7EZGXTWGVNVV2"

captured_requests = []


def main():
    print("\n" + "=" * 70)
    print("🔍 GrabFood API Interceptor")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='vi-VN',
        )

        page = context.new_page()

        # Capture all requests
        def handle_request(request):
            if any(keyword in request.url for keyword in ['api', 'graphql', 'review', 'rating', 'merchant']):
                captured_requests.append({
                    'url': request.url,
                    'method': request.method,
                    'headers': dict(request.headers),
                    'post_data': request.post_data if request.method == 'POST' else None,
                })
                print(f"\n📡 {request.method} {request.url}")

        # Capture responses
        def handle_response(response):
            if any(keyword in response.url for keyword in ['review', 'rating']):
                print(f"✅ {response.status} {response.url}")
                try:
                    if 'json' in response.headers.get('content-type', ''):
                        body = response.json()
                        print(f"📦 Response preview: {json.dumps(body, indent=2, ensure_ascii=False)[:500]}")
                except Exception as e:
                    print(f"⚠️  Could not parse response: {e}")

        page.on('request', handle_request)
        page.on('response', handle_response)

        print(f"\n🌐 Loading: {TEST_URL}")
        page.goto(TEST_URL, wait_until='networkidle', timeout=60000)

        print("\n⏳ Waiting 10 seconds for lazy-loaded content...")
        page.wait_for_timeout(10000)

        # Scroll down to trigger lazy loading
        print("📜 Scrolling to trigger lazy loading...")
        for i in range(3):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        # Try to click on reviews tab if exists
        print("\n🔍 Looking for reviews section...")
        try:
            reviews_selectors = [
                'text=Reviews',
                'text=Đánh giá',
                '[data-testid*="review"]',
                '[class*="review"]',
            ]
            for selector in reviews_selectors:
                elements = page.query_selector_all(selector)
                if elements:
                    print(f"✅ Found reviews element: {selector}")
                    elements[0].click()
                    page.wait_for_timeout(3000)
                    break
        except Exception as e:
            print(f"⚠️  No reviews section found: {e}")

        print("\n⏳ Waiting for final requests...")
        page.wait_for_timeout(5000)

        browser.close()

    # Save captured requests
    output_file = Path(__file__).parent / "captured_api_requests.json"
    output_file.write_text(json.dumps(captured_requests, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print("✅ INTERCEPTION COMPLETE")
    print("=" * 70)
    print(f"📊 Captured {len(captured_requests)} API requests")
    print(f"💾 Saved to: {output_file}")

    # Summary
    if captured_requests:
        print("\n📋 Summary of captured URLs:")
        unique_domains = set()
        for req in captured_requests:
            from urllib.parse import urlparse
            domain = urlparse(req['url']).netloc
            unique_domains.add(domain)
            print(f"   • {req['method']} {req['url'][:100]}...")

        print(f"\n🌐 Unique domains: {', '.join(unique_domains)}")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
