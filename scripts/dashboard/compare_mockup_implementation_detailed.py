"""
So sánh chi tiết Mockup vs Implementation dựa trên data thực tế
"""
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
import json
import re

def extract_data_from_html(html_path):
    """Extract JavaScript DATA object from HTML file"""
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    match = re.search(r'const DATA = ({.*?});', content, re.DOTALL)
    if not match:
        raise ValueError("Could not find DATA object in HTML")

    data_str = match.group(1)
    data = json.loads(data_str)
    return data

def create_comparison_excel():
    """Create detailed comparison Excel"""
    html_path = "/Users/khangnhq/Desktop/WorkGalaxy/social-listening/Dotn_v19_hybrid_fixed.html"
    mockup_data = extract_data_from_html(html_path)

    wb = Workbook()
    wb.remove(wb.active)

    # Colors
    header_fill = PatternFill(start_color="1F4788", end_color="1F4788", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    complete_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    partial_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    missing_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    screen_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Implementation status mapping
    implementation_status = {
        'overview': [
            {'title': 'Pain Priority Matrix', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced'},
            {'title': 'Revenue Impact Estimate', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced'},
            {'title': 'Lost Customer Signals', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced'},
            {'title': "Today's Action Timeline", 'status': '✓ Implemented', 'data_source': 'action_feed', 'notes': 'Dynamic from PostgreSQL'},
        ],
        'listen': [
            {'title': 'Topic Health Breakdown', 'status': '✓ Implemented', 'data_source': 'evidence_cards', 'notes': 'Dynamic - Pain/Demand/Positive themes'},
            {'title': 'Demand Signal Trend', 'status': '✓ Implemented', 'data_source': 'platform_summary', 'notes': 'Dynamic line chart'},
            {'title': 'Positive Theme Treemap', 'status': '✓ Implemented', 'data_source': 'evidence_cards', 'notes': 'Dynamic grouped columns'},
            {'title': 'Behavior Segment Funnel', 'status': '✓ Implemented', 'data_source': 'evidence_cards', 'notes': 'Dynamic funnel'},
        ],
        'brand': [
            {'title': 'Score Waterfall', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced'},
            {'title': 'Component Trendline', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced'},
            {'title': 'Fix / Amplify Matrix', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced'},
            {'title': 'Proof of Value Gauge', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced'},
        ],
        'reputation': [
            {'title': 'Crisis Spike Monitor', 'status': '⚠️ Code Ready', 'data_source': 'crisis_spike_alerts', 'notes': 'Table exists, needs data pipeline: detect_crisis_spikes.mjs'},
            {'title': 'Review Health Heatmap', 'status': '✓ Implemented', 'data_source': 'branch_intelligence + daily_branch_metrics', 'notes': 'Dynamic from PostgreSQL'},
            {'title': 'Response SLA Donut', 'status': '✓ Implemented', 'data_source': 'Hardcoded mock', 'notes': 'Mock data - can be enhanced with real SLA tracking'},
            {'title': 'Social Proof Pipeline', 'status': '✓ Implemented', 'data_source': 'evidence_cards', 'notes': 'Dynamic from PostgreSQL'},
        ],
        'competitor': [
            {'title': 'Competitive Pressure Radar', 'status': '✓ Implemented', 'data_source': 'competitor_pressure', 'notes': 'Dynamic - real competitor data'},
            {'title': 'Winning Pattern Comparison', 'status': '✓ Implemented', 'data_source': 'competitor_patterns', 'notes': 'Dynamic - real pattern analysis'},
            {'title': '5-Mode Response Map', 'status': '✓ Implemented', 'data_source': 'competitor_responses', 'notes': 'Dynamic - real response recommendations'},
            {'title': '7-Day Audit Funnel', 'status': '✓ Implemented', 'data_source': 'Calculated', 'notes': 'Dynamic audit readiness funnel'},
        ],
    }

    # Additional modules in implementation (not in original mockup base but added via augmentation)
    additional_modules = {
        'reputation': [
            {'title': 'Founder / CEO Reputation Watch', 'status': '⚠️ Code Ready', 'data_source': 'founder_mentions', 'notes': 'NEW - Table exists, needs data pipeline: detect_founder_mentions.mjs'},
            {'title': 'Qualified Negative Signal', 'status': '⚠️ Code Ready', 'data_source': 'qualified_negative_summary', 'notes': 'NEW - Table exists, needs data pipeline: analyze_qualified_negative.mjs'},
            {'title': 'Sensitive Topic Lifecycle', 'status': '⚠️ Code Ready', 'data_source': 'topic_lifecycle', 'notes': 'NEW - Table exists, needs data pipeline: track_topic_lifecycle.mjs'},
        ],
        'competitor': [
            {'title': 'Competitor Campaign Ranking', 'status': '⚠️ Code Ready', 'data_source': 'campaign_intelligence', 'notes': 'NEW - Table exists, needs data pipeline: analyze_competitor_campaigns.mjs'},
            {'title': 'Winning Content Pattern', 'status': '⚠️ Code Ready', 'data_source': 'content_patterns', 'notes': 'NEW - Table exists, needs data pipeline: detect_content_patterns.mjs'},
            {'title': '5W-1H Signal Diagnosis', 'status': '⚠️ Code Ready', 'data_source': 'signal_diagnosis', 'notes': 'NEW - Table exists, needs data pipeline: generate_5w1h_diagnosis.mjs'},
        ],
    }

    screens = {
        'overview': 'Overview',
        'listen': 'Listen',
        'brand': 'Brand Health',
        'reputation': 'Reputation',
        'competitor': 'Competitor Radar'
    }

    # Create main comparison sheet
    ws = wb.create_sheet("📋 Comparison", 0)

    # Headers
    headers = ["Screen", "Module Name (Mockup)", "Chart Type", "Mockup", "Implementation", "Data Source", "Notes / Action Needed"]
    ws.append(headers)

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    current_screen = ""
    total_implemented = 0
    total_code_ready = 0
    total_missing = 0

    for screen_key in ['overview', 'listen', 'brand', 'reputation', 'competitor']:
        screen_name = screens[screen_key]
        screen_data = mockup_data.get(screen_key, {})
        modules = screen_data.get('modules', [])

        # Process base mockup modules
        for module in modules:
            module_title = module.get('title', '')
            chart_type = module.get('chart', '')

            # Find implementation status
            impl_module = next((m for m in implementation_status.get(screen_key, []) if m['title'] == module_title), None)

            if impl_module:
                status = impl_module['status']
                data_source = impl_module['data_source']
                notes = impl_module['notes']

                if '✓' in status:
                    total_implemented += 1
                elif '⚠️' in status:
                    total_code_ready += 1
                else:
                    total_missing += 1
            else:
                status = '✗ Missing'
                data_source = 'N/A'
                notes = 'Not implemented yet'
                total_missing += 1

            ws.append([
                screen_name if screen_name != current_screen else '',
                module_title,
                chart_type,
                '✓ In Mockup',
                status,
                data_source,
                notes
            ])

            current_row = ws.max_row
            current_screen = screen_name

            # Apply borders
            for col_num in range(1, 8):
                cell = ws.cell(row=current_row, column=col_num)
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

            # Screen name - bold
            if ws.cell(row=current_row, column=1).value:
                ws.cell(row=current_row, column=1).font = Font(bold=True, size=11)
                ws.cell(row=current_row, column=1).fill = screen_fill

            # Color code status
            status_cell = ws.cell(row=current_row, column=5)
            if '✓' in status:
                status_cell.fill = complete_fill
                status_cell.font = Font(bold=True)
            elif '⚠️' in status:
                status_cell.fill = partial_fill
                status_cell.font = Font(bold=True)
            elif '✗' in status:
                status_cell.fill = missing_fill
                status_cell.font = Font(bold=True)

        # Add additional modules (not in base mockup)
        if screen_key in additional_modules:
            for module in additional_modules[screen_key]:
                ws.append([
                    '',
                    module['title'],
                    'various',
                    '✓ In Mockup v16+',
                    module['status'],
                    module['data_source'],
                    module['notes']
                ])

                current_row = ws.max_row

                if '✓' in module['status']:
                    total_implemented += 1
                elif '⚠️' in module['status']:
                    total_code_ready += 1

                for col_num in range(1, 8):
                    cell = ws.cell(row=current_row, column=col_num)
                    cell.border = thin_border
                    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

                status_cell = ws.cell(row=current_row, column=5)
                if '⚠️' in module['status']:
                    status_cell.fill = partial_fill
                    status_cell.font = Font(bold=True)

    # Column widths
    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 35
    ws.column_dimensions['C'].width = 15
    ws.column_dimensions['D'].width = 18
    ws.column_dimensions['E'].width = 18
    ws.column_dimensions['F'].width = 30
    ws.column_dimensions['G'].width = 60

    # Create Summary sheet
    summary_ws = wb.create_sheet("📊 Summary", 0)

    summary_ws.append(["Mockup vs Implementation Summary"])
    summary_ws.merge_cells('A1:C1')
    summary_ws['A1'].fill = header_fill
    summary_ws['A1'].font = Font(bold=True, color="FFFFFF", size=14)
    summary_ws['A1'].alignment = Alignment(horizontal="center", vertical="center")

    summary_ws.append([])
    summary_ws.append(["Status", "Count", "Percentage"])

    for col in range(1, 4):
        cell = summary_ws.cell(row=3, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    total = total_implemented + total_code_ready + total_missing

    summary_ws.append(["✓ Fully Implemented", total_implemented, f"{total_implemented/total*100:.0f}%"])
    summary_ws.append(["⚠️ Code Ready (No Data)", total_code_ready, f"{total_code_ready/total*100:.0f}%"])
    summary_ws.append(["✗ Missing", total_missing, f"{total_missing/total*100:.0f}%"])
    summary_ws.append([])
    summary_ws.append(["TOTAL", total, "100%"])

    # Color code summary
    summary_ws.cell(row=4, column=1).fill = complete_fill
    summary_ws.cell(row=5, column=1).fill = partial_fill
    summary_ws.cell(row=6, column=1).fill = missing_fill

    for row in range(4, 8):
        for col in range(1, 4):
            cell = summary_ws.cell(row=row, column=col)
            cell.border = thin_border
            if row == 7:
                cell.font = Font(bold=True, size=12)
                cell.fill = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")

    # Add screen breakdown
    summary_ws.append([])
    summary_ws.append([])
    summary_ws.append(["Screen", "Mockup Modules", "Implemented", "Code Ready", "Missing"])

    for col in range(1, 6):
        cell = summary_ws.cell(row=10, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for screen_key, screen_name in screens.items():
        mockup_count = len(mockup_data.get(screen_key, {}).get('modules', []))
        additional_count = len(additional_modules.get(screen_key, []))
        total_mockup = mockup_count + additional_count

        impl_count = len([m for m in implementation_status.get(screen_key, []) if '✓' in m['status']])
        ready_count = len([m for m in implementation_status.get(screen_key, []) if '⚠️' in m['status']])
        ready_count += len([m for m in additional_modules.get(screen_key, []) if '⚠️' in m['status']])

        missing_count = total_mockup - impl_count - ready_count

        summary_ws.append([screen_name, total_mockup, impl_count, ready_count, missing_count])

        current_row = summary_ws.max_row
        for col in range(1, 6):
            summary_ws.cell(row=current_row, column=col).border = thin_border

    summary_ws.column_dimensions['A'].width = 20
    summary_ws.column_dimensions['B'].width = 18
    summary_ws.column_dimensions['C'].width = 15
    summary_ws.column_dimensions['D'].width = 15
    summary_ws.column_dimensions['E'].width = 15

    # Save
    output_file = "/Users/khangnhq/Desktop/WorkGalaxy/social-listening/MOCKUP_VS_IMPLEMENTATION.xlsx"
    wb.save(output_file)

    print(f"✅ Comparison Excel created: {output_file}")
    print(f"\n📊 Summary:")
    print(f"   • Total modules in mockup: {total}")
    print(f"   • ✓ Fully implemented: {total_implemented} ({total_implemented/total*100:.0f}%)")
    print(f"   • ⚠️ Code ready (no data): {total_code_ready} ({total_code_ready/total*100:.0f}%)")
    print(f"   • ✗ Missing: {total_missing} ({total_missing/total*100:.0f}%)")

if __name__ == "__main__":
    create_comparison_excel()
