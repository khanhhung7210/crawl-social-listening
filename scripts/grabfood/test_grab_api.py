#!/usr/bin/env python3
"""Test GrabFood merchant API to see if it contains reviews"""

import json
import requests

# Test merchant: MeiLi
MERCHANT_ID = "5-C7EZGXTWGVNVV2"
LAT_LNG = "10.7769,106.7009"  # HCMC District 1

url = f"https://portal.grab.com/foodweb/guest/v2/merchants/{MERCHANT_ID}?latlng={LAT_LNG}"

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'vi',
    'x-gfc-country': 'VN',
    'x-country-code': 'VN',
    'Referer': 'https://food.grab.com/',
}

print(f"🔍 Testing API: {url}\n")

try:
    response = requests.get(url, headers=headers, timeout=30)
    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}\n")

    if response.status_code == 200:
        try:
            data = response.json()
            print("=" * 70)
            print("✅ API RESPONSE (First 500 characters):")
            print("=" * 70)
            print(json.dumps(data, indent=2, ensure_ascii=False)[:1500])
            print("\n...")

            # Check for reviews
            print("\n" + "=" * 70)
            print("🔍 SEARCHING FOR REVIEWS DATA:")
            print("=" * 70)

            json_str = json.dumps(data, ensure_ascii=False).lower()
            if any(keyword in json_str for keyword in ['review', 'rating', 'comment', 'feedback']):
                print("✅ Found potential reviews data keywords!")

                # Try to find reviews structure
                def find_reviews(obj, path=""):
                    if isinstance(obj, dict):
                        for key, value in obj.items():
                            if any(kw in key.lower() for kw in ['review', 'rating', 'comment', 'feedback']):
                                print(f"  📌 Found at: {path}.{key}")
                                print(f"     Type: {type(value)}")
                                if isinstance(value, (dict, list)):
                                    print(f"     Value: {json.dumps(value, ensure_ascii=False, indent=2)[:300]}...")
                            find_reviews(value, f"{path}.{key}")
                    elif isinstance(obj, list):
                        for i, item in enumerate(obj):
                            find_reviews(item, f"{path}[{i}]")

                find_reviews(data)
            else:
                print("❌ No review-related keywords found in response")

        except json.JSONDecodeError:
            print("❌ Response is not JSON")
            print(f"Response text: {response.text[:500]}")
    else:
        print(f"❌ Request failed with status {response.status_code}")
        print(f"Response: {response.text[:500]}")

except Exception as e:
    print(f"❌ Error: {e}")
