#!/usr/bin/env python3
"""
Compare generated dashboards with mockup HTML to find mismatches
"""

import json
import re
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOCKUP_HTML = PROJECT_ROOT / 'Dotn_v19_hybrid_fixed.html'
DASHBOARD_DIR = PROJECT_ROOT / 'data' / 'dashboard'

def extract_mockup_dashboards():
    """Extract dashboard definitions from mockup HTML"""
    with open(MOCKUP_HTML, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find DATA constant
    match = re.search(r'const DATA = ({.*?});', content, re.DOTALL)
    if not match:
        print("❌ Could not find DATA constant in mockup HTML")
        return None

    # Parse JSON (with single quotes, need to convert)
    data_str = match.group(1)
    # Convert single quotes to double quotes for JSON parsing
    # This is a simplified approach - may need adjustment
    data_str = data_str.replace("'", '"')
    # Handle JavaScript syntax like trailing commas
    data_str = re.sub(r',(\s*[}\]])', r'\1', data_str)

    try:
        data = json.loads(data_str)
        return data
    except json.JSONDecodeError as e:
        print(f"❌ Could not parse DATA: {e}")
        # Try alternative extraction
        return extract_mockup_manual(content)

def extract_mockup_manual(content):
    """Manual extraction of dashboard data from HTML"""
    mockup_data = {
        'overview': {'modules': []},
        'listen': {'modules': []},
        'brand': {'modules': []},
        'reputation': {'modules': []}
    }

    # Extract sections with regex
    patterns = {
        'overview': r'"overview":\s*{[^}]*"modules":\s*\[(.*?)\]',
        'listen': r'"listen":\s*{[^}]*"modules":\s*\[(.*?)\]',
        'brand': r'"brand":\s*{[^}]*"modules":\s*\[(.*?)\]',
        'reputation': r'"reputation":\s*{[^}]*"modules":\s*\[(.*?)\]'
    }

    for screen, pattern in patterns.items():
        match = re.search(pattern, content, re.DOTALL)
        if match:
            modules_text = match.group(1)
            # Extract individual module objects
            module_matches = re.finditer(r'{title:"([^"]+)",.*?chart:"([^"]+)"', modules_text)
            for m in module_matches:
                mockup_data[screen]['modules'].append({
                    'title': m.group(1),
                    'chart': m.group(2)
                })

    return mockup_data

def get_generated_dashboards():
    """Get all generated dashboards"""
    dashboards = {
        'overview': [],
        'listen': [],
        'brand_health': [],
        'reputation': []
    }

    for screen_name, screen_dashboards in dashboards.items():
        screen_dir = DASHBOARD_DIR / screen_name
        if not screen_dir.exists():
            continue

        for json_file in sorted(screen_dir.glob('*.json')):
            if json_file.name.endswith('_all.json'):
                continue

            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                dashboards[screen_name].append({
                    'file': json_file.name,
                    'title': data.get('title', 'N/A'),
                    'chart': data.get('chart', 'N/A'),
                    'data': data.get('data'),
                    'takeaway': data.get('takeaway', ''),
                    'analysis': data.get('analysis', []),
                    'action': data.get('action', {})
                })

    return dashboards

def compare_dashboards():
    """Compare generated dashboards with mockup"""
    print("=" * 80)
    print("DASHBOARD MOCKUP COMPARISON")
    print("=" * 80)

    # Load mockup
    print("\n📥 Loading mockup from HTML...")
    mockup = extract_mockup_dashboards()

    if not mockup:
        print("⚠️  Could not load mockup, using manual extraction...")
        with open(MOCKUP_HTML, 'r', encoding='utf-8') as f:
            mockup = extract_mockup_manual(f.read())

    # Load generated
    print("📥 Loading generated dashboards...")
    generated = get_generated_dashboards()

    # Map screen names
    screen_mapping = {
        'overview': 'overview',
        'listen': 'listen',
        'brand': 'brand_health',
        'reputation': 'reputation'
    }

    mismatches = []
    matches = []

    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    for mockup_screen, gen_screen in screen_mapping.items():
        print(f"\n📂 {gen_screen.upper().replace('_', ' ')}")
        print("-" * 80)

        mockup_modules = mockup.get(mockup_screen, {}).get('modules', [])
        gen_modules = generated.get(gen_screen, [])

        # Create lookup
        gen_by_title = {m['title']: m for m in gen_modules}

        for mockup_mod in mockup_modules:
            title = mockup_mod.get('title', '')
            mockup_chart = mockup_mod.get('chart', '')

            if title in gen_by_title:
                gen_mod = gen_by_title[title]
                gen_chart = gen_mod['chart']

                if mockup_chart == gen_chart:
                    print(f"✅ {title}")
                    print(f"   Chart: {mockup_chart}")
                    matches.append({
                        'screen': gen_screen,
                        'title': title,
                        'status': 'OK'
                    })
                else:
                    print(f"❌ {title}")
                    print(f"   Chart mismatch: mockup={mockup_chart}, generated={gen_chart}")
                    mismatches.append({
                        'screen': gen_screen,
                        'title': title,
                        'issue': 'chart_mismatch',
                        'mockup_chart': mockup_chart,
                        'gen_chart': gen_chart,
                        'file': gen_mod['file']
                    })
            else:
                print(f"⚠️  {title}")
                print(f"   NOT FOUND in generated dashboards")
                mismatches.append({
                    'screen': gen_screen,
                    'title': title,
                    'issue': 'missing',
                    'mockup_chart': mockup_chart
                })

        # Check for extra dashboards
        mockup_titles = {m.get('title') for m in mockup_modules}
        for gen_mod in gen_modules:
            if gen_mod['title'] not in mockup_titles:
                print(f"🆕 {gen_mod['title']}")
                print(f"   EXTRA dashboard (not in mockup)")
                mismatches.append({
                    'screen': gen_screen,
                    'title': gen_mod['title'],
                    'issue': 'extra',
                    'gen_chart': gen_mod['chart'],
                    'file': gen_mod['file']
                })

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"✅ Matching dashboards: {len(matches)}")
    print(f"❌ Mismatches found: {len(mismatches)}")

    if mismatches:
        print("\n" + "=" * 80)
        print("DETAILED MISMATCHES")
        print("=" * 80)

        # Group by issue type
        by_issue = defaultdict(list)
        for m in mismatches:
            by_issue[m['issue']].append(m)

        for issue_type, items in by_issue.items():
            print(f"\n🔴 {issue_type.upper().replace('_', ' ')} ({len(items)} dashboards)")
            print("-" * 80)

            for item in items:
                print(f"\n📊 {item['title']}")
                print(f"   Screen: {item['screen']}")
                if 'file' in item:
                    print(f"   File: {item['file']}")
                if 'mockup_chart' in item:
                    print(f"   Mockup chart: {item['mockup_chart']}")
                if 'gen_chart' in item:
                    print(f"   Generated chart: {item['gen_chart']}")

                if issue_type == 'chart_mismatch':
                    print(f"   🔧 FIX: Change chart type from '{item['gen_chart']}' to '{item['mockup_chart']}'")
                elif issue_type == 'missing':
                    print(f"   🔧 FIX: Generate this dashboard with chart type '{item['mockup_chart']}'")
                elif issue_type == 'extra':
                    print(f"   🔧 FIX: Remove or verify if this should exist")

    print("\n" + "=" * 80)

    # Create fix checklist
    if mismatches:
        print("\n📋 FIX CHECKLIST:")
        print("-" * 80)
        for i, item in enumerate(mismatches, 1):
            if item['issue'] == 'chart_mismatch':
                print(f"{i}. [{item['screen']}] {item['title']}: chart '{item['gen_chart']}' → '{item['mockup_chart']}'")
            elif item['issue'] == 'missing':
                print(f"{i}. [{item['screen']}] {item['title']}: MISSING - need to generate")
            elif item['issue'] == 'extra':
                print(f"{i}. [{item['screen']}] {item['title']}: EXTRA - verify if needed")
    else:
        print("\n🎉 ALL DASHBOARDS MATCH MOCKUP!")

    print("\n" + "=" * 80)

    return len(mismatches)

if __name__ == "__main__":
    exit_code = compare_dashboards()
    exit(0 if exit_code == 0 else 1)
