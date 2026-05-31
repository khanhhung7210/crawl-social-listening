#!/usr/bin/env python3
"""
Verify all generated dashboards match the mockup HTML
"""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOCKUP_HTML = PROJECT_ROOT / 'Dotn_v19_hybrid_fixed.html'
DASHBOARD_DIR = PROJECT_ROOT / 'data' / 'dashboard'

def extract_data():
    """Extract DATA constant from mockup"""
    with open(MOCKUP_HTML, 'r') as f:
        content = f.read()

    match = re.search(r'const DATA = ({.*?});', content, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except:
        return None

def get_generated():
    """Get generated dashboards"""
    result = {}
    for screen in ['overview', 'listen', 'brand_health', 'reputation']:
        screen_dir = DASHBOARD_DIR / screen
        result[screen] = []
        if screen_dir.exists():
            for f in sorted(screen_dir.glob('*.json')):
                if not f.name.endswith('_all.json'):
                    with open(f) as fp:
                        data = json.load(fp)
                        result[screen].append({
                            'file': f.name,
                            'title': data.get('title', ''),
                            'chart': data.get('chart', '')
                        })
    return result

def main():
    print("=" * 80)
    print("MOCKUP COMPLIANCE VERIFICATION")
    print("=" * 80)

    mockup = extract_data()
    if not mockup:
        print("\n❌ Failed to load mockup")
        return 1

    generated = get_generated()

    mapping = {
        'overview': 'overview',
        'listen': 'listen',
        'brand': 'brand_health',
        'reputation': 'reputation'
    }

    perfect = 0
    chart_errors = 0
    missing = 0
    extra = 0

    for m_screen, g_screen in mapping.items():
        if m_screen not in mockup:
            continue

        print(f"\n{'=' * 80}")
        print(f"{g_screen.upper().replace('_', ' ')}")
        print("=" * 80)

        m_mods = mockup[m_screen].get('modules', [])
        g_mods = generated[g_screen]

        g_by_title = {m['title']: m for m in g_mods}

        for m_mod in m_mods:
            title = m_mod['title']
            m_chart = m_mod['chart']

            if title in g_by_title:
                g_chart = g_by_title[title]['chart']
                if m_chart == g_chart:
                    print(f"✅ {title} ({m_chart})")
                    perfect += 1
                else:
                    print(f"❌ {title} - chart mismatch: {g_chart} != {m_chart}")
                    chart_errors += 1
            else:
                print(f"❌ {title} - MISSING")
                missing += 1

        # Check extra
        m_titles = {m['title'] for m in m_mods}
        for g_mod in g_mods:
            if g_mod['title'] not in m_titles:
                print(f"🆕 {g_mod['title']} ({g_mod['chart']}) - EXTRA")
                extra += 1

    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print("=" * 80)
    print(f"✅ Perfect matches: {perfect}")
    print(f"❌ Chart mismatches: {chart_errors}")
    print(f"❌ Missing: {missing}")
    print(f"🆕 Extra: {extra}")

    if chart_errors + missing == 0:
        print("\n🎉 ALL MOCKUP DASHBOARDS MATCH!")
        return 0
    else:
        print(f"\n⚠️  {chart_errors + missing} ISSUES FOUND")
        return 1

if __name__ == "__main__":
    exit(main())
