#!/usr/bin/env python3
"""
Check data quality across all generated dashboards
"""

import json
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = PROJECT_ROOT / 'data' / 'dashboard'

def check_dashboard_quality(dashboard_path):
    """Check quality issues in a dashboard"""
    issues = []
    warnings = []

    with open(dashboard_path, 'r', encoding='utf-8') as f:
        dashboard = json.load(f)

    # Check for capped scores (100, 100) in matrix data
    if dashboard.get('chart') == 'matrix':
        data = dashboard.get('data', [])
        capped_count = sum(1 for row in data if len(row) >= 3 and row[1] == 100 and row[2] == 100)
        if capped_count > len(data) // 2:
            issues.append(f"Too many capped scores (100,100): {capped_count}/{len(data)} rows")

    # Check for empty or minimal data
    data = dashboard.get('data')
    if isinstance(data, list) and len(data) == 0:
        issues.append("Empty data array")
    elif isinstance(data, list) and len(data) < 3:
        warnings.append(f"Minimal data: only {len(data)} items")

    # Check for repeated/generic text
    analysis = dashboard.get('analysis', [])
    if len(analysis) < 2:
        warnings.append(f"Too few analysis points: {len(analysis)}")

    # Check for missing Vietnamese
    full_text = json.dumps(dashboard, ensure_ascii=False)
    if not any(c in full_text for c in 'àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ'):
        warnings.append("No Vietnamese text detected")

    # Check for placeholder text
    if 'No data' in full_text or 'N/A' in full_text or 'undefined' in full_text.lower():
        warnings.append("Contains placeholder text")

    # Check chart-specific issues
    chart_type = dashboard.get('chart')
    if chart_type == 'stacked':
        # Check if percentages add up to ~100
        for row in dashboard.get('data', []):
            if len(row) >= 4:
                total = sum(row[1:4])  # Positive, neutral, negative percentages
                if abs(total - 100) > 5:
                    issues.append(f"Stacked percentages don't add to 100: {row[0]} = {total}%")

    elif chart_type == 'donut':
        # Check if donut has reasonable number of segments
        values = dashboard.get('data', {}).get('values', [])
        if len(values) > 10:
            warnings.append(f"Too many donut segments: {len(values)}")

    elif chart_type == 'gauge':
        # Check if gauge value is in range
        value = dashboard.get('data', {}).get('value', 0)
        if value < 0 or value > 100:
            issues.append(f"Gauge value out of range: {value}")

    return issues, warnings

def main():
    print("=" * 80)
    print("DASHBOARD DATA QUALITY CHECK")
    print("=" * 80)

    screens = ['overview', 'listen', 'brand_health', 'reputation']

    total_dashboards = 0
    total_issues = 0
    total_warnings = 0

    problem_dashboards = []

    for screen in screens:
        screen_dir = DASHBOARD_DIR / screen
        if not screen_dir.exists():
            print(f"\n⚠️  Screen directory not found: {screen}")
            continue

        print(f"\n📂 {screen.upper().replace('_', ' ')}")
        print("-" * 80)

        json_files = sorted(screen_dir.glob('*.json'))
        # Exclude combined files
        json_files = [f for f in json_files if not f.name.endswith('_all.json')]

        for json_file in json_files:
            total_dashboards += 1
            issues, warnings = check_dashboard_quality(json_file)

            if issues or warnings:
                status = "❌" if issues else "⚠️ "
                print(f"{status} {json_file.name}")

                if issues:
                    for issue in issues:
                        print(f"   🔴 ISSUE: {issue}")
                        total_issues += 1
                    problem_dashboards.append({
                        'file': str(json_file),
                        'screen': screen,
                        'name': json_file.stem,
                        'issues': issues,
                        'warnings': warnings
                    })

                if warnings:
                    for warning in warnings:
                        print(f"   🟡 WARNING: {warning}")
                        total_warnings += 1
            else:
                print(f"✅ {json_file.name}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total Dashboards: {total_dashboards}")
    print(f"Issues Found: {total_issues}")
    print(f"Warnings Found: {total_warnings}")
    print(f"Dashboards with Issues: {len(problem_dashboards)}")

    if problem_dashboards:
        print("\n" + "=" * 80)
        print("DASHBOARDS NEEDING FIXES:")
        print("=" * 80)
        for dash in problem_dashboards:
            print(f"\n📄 {dash['screen']}/{dash['name']}")
            for issue in dash['issues']:
                print(f"   🔴 {issue}")

    print("\n" + "=" * 80)

    if total_issues == 0:
        print("✅ All dashboards pass quality checks!")
    else:
        print(f"⚠️  {len(problem_dashboards)} dashboards need attention")

    return len(problem_dashboards)

if __name__ == "__main__":
    exit_code = main()
    exit(0 if exit_code == 0 else 1)
