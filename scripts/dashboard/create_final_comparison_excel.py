"""
Tạo file Excel so sánh Mockup vs Implementation - Phiên bản cuối cùng
"""
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

def create_final_excel():
    wb = Workbook()
    wb.remove(wb.active)

    # Colors
    header_fill = PatternFill(start_color="1F4788", end_color="1F4788", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    mockup_fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
    impl_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    code_ready_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    extra_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Data structure
    data = {
        'Overview': {
            'mockup': [
                'Pain Priority Matrix',
                'Revenue Impact Estimate',
                'Lost Customer Signals',
                "Today's Action Timeline",
                'Marketing Funnel Leakage',
                'Channel Signal Quality',
            ],
            'implementation': [
                'Pain Priority Matrix',
                'Revenue Impact Estimate',
                'Lost Customer Signals',
                "Today's Action Timeline",
                'Qualified Signal Summary',
                'Marketing Funnel Leakage',
                'Channel Signal Quality',
                'Branch Risk Snapshot',
                'Brand-wide vs Branch-specific Issue Split',
            ]
        },
        'Listen': {
            'mockup': [
                'Topic Health Breakdown',
                'Demand Signal Trend',
                'Positive Theme Treemap',
                'Behavior Segment Funnel',
                'Creative Trigger Board',
            ],
            'implementation': [
                'Topic Health Breakdown',
                'Demand Signal Trend',
                'Positive Theme Treemap',
                'Behavior Segment Funnel',
                'Trend Opportunity Radar',
                'Topic Lifecycle Tracker',
                'Signal Source Mix',
                'Influencer Signal Watch Lite',
                'Creative Trigger Board',
                'Topic x Sentiment by Branch',
                'Priority Action Detail',
            ]
        },
        'Brand Health': {
            'mockup': [
                'Score Waterfall',
                'Component Trendline',
                'Fix / Amplify Matrix',
                'Proof of Value Gauge',
                'Brand Equity & Sentiment Score',
                'Proof of Premium Readiness',
            ],
            'implementation': [
                'Score Waterfall',
                'Component Trendline',
                'Fix / Amplify Matrix',
                'Proof of Value Gauge',
                'Category Brand Rank',
                'Campaign Readiness & Benchmark',
                'YMI-style Score Decomposition',
                'Brand Equity & Sentiment Score',
                'Proof of Premium Readiness',
                'Brand Health by Branch',
                'Best Branch Pattern',
                'Priority Action Detail',
            ]
        },
        'Reputation': {
            'mockup': [
                'Crisis Spike Monitor',
                'Review Health Heatmap',
                'Response SLA Donut',
                'Social Proof Pipeline',
            ],
            'implementation': [
                'Crisis Spike Monitor',
                'Review Health Heatmap',
                'Response SLA Donut',
                'Social Proof Pipeline',
                'Founder / CEO Reputation Watch',
                'Qualified Negative Signal',
                'Sensitive Topic Lifecycle',
            ]
        },
        'Competitor': {
            'mockup': [
                'Competitive Pressure Radar',
                'Winning Pattern Comparison',
                '5-Mode Response Map',
                '7-Day Audit Funnel',
                'Marketing Competitor Response Playbook',
            ],
            'implementation': [
                'Competitive Pressure Radar',
                'Winning Pattern Comparison',
                '5-Mode Response Map',
                'Competitive Intelligence Readiness',
                'Competitor Campaign Ranking',
                'Winning Content Pattern',
                '5W-1H Signal Diagnosis',
            ]
        }
    }

    # Code ready modules (need data)
    code_ready = {
        'Crisis Spike Monitor',
        'Founder / CEO Reputation Watch',
        'Qualified Negative Signal',
        'Sensitive Topic Lifecycle',
        'Competitor Campaign Ranking',
        'Winning Content Pattern',
        '5W-1H Signal Diagnosis',
    }

    # ===== SUMMARY SHEET =====
    ws_summary = wb.create_sheet("📊 Summary", 0)

    ws_summary.merge_cells('A1:E1')
    ws_summary['A1'] = "Dashboard Feature Comparison: Mockup vs Implementation"
    ws_summary['A1'].fill = header_fill
    ws_summary['A1'].font = Font(bold=True, color="FFFFFF", size=14)
    ws_summary['A1'].alignment = Alignment(horizontal="center", vertical="center")
    ws_summary.row_dimensions[1].height = 25

    ws_summary.append([])
    ws_summary.append(["Screen", "Mockup", "Implementation", "Extra", "Status"])

    for col in range(1, 6):
        cell = ws_summary.cell(row=3, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    total_mockup = 0
    total_impl = 0
    total_extra = 0

    for screen_name, screen_data in data.items():
        mockup_count = len(screen_data['mockup'])
        impl_count = len(screen_data['implementation'])
        extra_count = impl_count - mockup_count

        status = "✓ Enhanced" if extra_count > 0 else "✓ Same"

        ws_summary.append([screen_name, mockup_count, impl_count, extra_count, status])

        total_mockup += mockup_count
        total_impl += impl_count
        total_extra += extra_count

        row = ws_summary.max_row
        for col in range(1, 6):
            cell = ws_summary.cell(row=row, column=col)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws_summary.append([])
    ws_summary.append(["TOTAL", total_mockup, total_impl, total_extra, ""])
    row = ws_summary.max_row
    for col in range(1, 6):
        cell = ws_summary.cell(row=row, column=col)
        cell.font = Font(bold=True, size=12)
        cell.fill = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Add implementation status
    ws_summary.append([])
    ws_summary.append([])
    ws_summary.append(["Implementation Status", "Count", "Percentage"])

    for col in range(1, 4):
        cell = ws_summary.cell(row=ws_summary.max_row, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    impl_ready = total_impl - len(code_ready)

    ws_summary.append(["✓ Fully Implemented", impl_ready, f"{impl_ready/total_impl*100:.0f}%"])
    ws_summary.append(["⚠️ Code Ready (Need Data)", len(code_ready), f"{len(code_ready)/total_impl*100:.0f}%"])

    for row in [ws_summary.max_row - 1, ws_summary.max_row]:
        for col in range(1, 4):
            cell = ws_summary.cell(row=row, column=col)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws_summary.cell(row=ws_summary.max_row - 1, column=1).fill = impl_fill
    ws_summary.cell(row=ws_summary.max_row, column=1).fill = code_ready_fill

    ws_summary.column_dimensions['A'].width = 25
    ws_summary.column_dimensions['B'].width = 12
    ws_summary.column_dimensions['C'].width = 15
    ws_summary.column_dimensions['D'].width = 12
    ws_summary.column_dimensions['E'].width = 15

    # ===== DETAIL SHEETS =====
    for screen_name, screen_data in data.items():
        ws = wb.create_sheet(f"🎯 {screen_name}")

        # Header
        ws.merge_cells('A1:D1')
        ws['A1'] = f"{screen_name} - Comparison"
        ws['A1'].fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        ws['A1'].font = Font(bold=True, color="FFFFFF", size=13)
        ws['A1'].alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 25

        ws.append([])
        ws.append(["#", "Module Name", "Mockup", "Implementation"])

        for col in range(1, 5):
            cell = ws.cell(row=3, column=col)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        # Get all unique modules
        all_modules = []
        mockup_set = set(screen_data['mockup'])
        impl_set = set(screen_data['implementation'])

        # Add all implementation modules
        for module in screen_data['implementation']:
            all_modules.append(module)

        # Add mockup-only modules that are not in implementation
        for module in screen_data['mockup']:
            if module not in impl_set:
                all_modules.append(module)

        # Write rows
        for idx, module in enumerate(all_modules, 1):
            in_mockup = module in mockup_set
            in_impl = module in impl_set
            is_code_ready = module in code_ready

            mockup_status = "✓" if in_mockup else ""

            if in_impl:
                if is_code_ready:
                    impl_status = "⚠️ Code Ready"
                else:
                    impl_status = "✓ Implemented"
            else:
                impl_status = ""

            ws.append([idx, module, mockup_status, impl_status])

            row = ws.max_row
            for col in range(1, 5):
                cell = ws.cell(row=row, column=col)
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

            # Color coding
            if in_mockup:
                ws.cell(row=row, column=3).fill = mockup_fill
                ws.cell(row=row, column=3).alignment = Alignment(horizontal="center", vertical="center")

            if in_impl:
                if is_code_ready:
                    ws.cell(row=row, column=4).fill = code_ready_fill
                else:
                    ws.cell(row=row, column=4).fill = impl_fill
                ws.cell(row=row, column=4).alignment = Alignment(horizontal="center", vertical="center")

            # Highlight extra modules
            if in_impl and not in_mockup:
                ws.cell(row=row, column=2).fill = extra_fill
                ws.cell(row=row, column=2).font = Font(italic=True)

        ws.column_dimensions['A'].width = 5
        ws.column_dimensions['B'].width = 45
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 20

    # ===== LEGEND SHEET =====
    ws_legend = wb.create_sheet("📖 Legend")

    ws_legend.merge_cells('A1:B1')
    ws_legend['A1'] = "Legend & Notes"
    ws_legend['A1'].fill = header_fill
    ws_legend['A1'].font = Font(bold=True, color="FFFFFF", size=13)
    ws_legend['A1'].alignment = Alignment(horizontal="center", vertical="center")
    ws_legend.row_dimensions[1].height = 25

    ws_legend.append([])
    ws_legend.append(["Symbol/Color", "Meaning"])

    for col in range(1, 3):
        cell = ws_legend.cell(row=3, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    legend_data = [
        ["✓", "Module exists"],
        ["⚠️ Code Ready", "Code implemented but table empty (needs data pipeline)"],
        ["✓ Implemented", "Fully working with data"],
        ["Gray background", "In mockup"],
        ["Green background", "Fully implemented"],
        ["Yellow background", "Code ready, needs data"],
        ["Blue italic", "Extra module (not in mockup)"],
    ]

    for item in legend_data:
        ws_legend.append(item)
        row = ws_legend.max_row
        for col in range(1, 3):
            cell = ws_legend.cell(row=row, column=col)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

        # Apply colors to demonstrate
        if "Gray" in item[1]:
            ws_legend.cell(row=row, column=1).fill = mockup_fill
        elif "Green" in item[1]:
            ws_legend.cell(row=row, column=1).fill = impl_fill
        elif "Yellow" in item[1]:
            ws_legend.cell(row=row, column=1).fill = code_ready_fill
        elif "Blue" in item[1]:
            ws_legend.cell(row=row, column=1).fill = extra_fill

    ws_legend.append([])
    ws_legend.append(["Data Pipelines Needed", ""])
    ws_legend.cell(row=ws_legend.max_row, column=1).font = Font(bold=True, size=11)

    pipelines = [
        "detect_crisis_spikes.mjs - Detect spike anomalies",
        "detect_founder_mentions.mjs - Track CEO/founder mentions",
        "analyze_qualified_negative.mjs - Classify negative by source trust",
        "track_topic_lifecycle.mjs - Track topic stages",
        "analyze_competitor_campaigns.mjs - Detect competitor campaigns",
        "detect_content_patterns.mjs - Extract winning patterns",
        "generate_5w1h_diagnosis.mjs - Generate signal diagnosis",
    ]

    for pipeline in pipelines:
        ws_legend.append([pipeline, ""])
        row = ws_legend.max_row
        ws_legend.cell(row=row, column=1).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    ws_legend.column_dimensions['A'].width = 50
    ws_legend.column_dimensions['B'].width = 40

    # Save
    output_file = "/Users/khangnhq/Desktop/WorkGalaxy/social-listening/MOCKUP_VS_IMPLEMENTATION_FINAL.xlsx"
    wb.save(output_file)

    print(f"✅ File Excel đã tạo: {output_file}")
    print(f"\n📊 Tổng kết:")
    print(f"   • Mockup: {total_mockup} modules")
    print(f"   • Implementation: {total_impl} modules")
    print(f"   • Extra modules: {total_extra}")
    print(f"   • Fully implemented: {impl_ready} ({impl_ready/total_impl*100:.0f}%)")
    print(f"   • Code ready (need data): {len(code_ready)} ({len(code_ready)/total_impl*100:.0f}%)")
    print(f"\n📋 Chi tiết:")
    for screen_name, screen_data in data.items():
        print(f"   • {screen_name}: {len(screen_data['mockup'])} (mockup) → {len(screen_data['implementation'])} (implementation)")

if __name__ == "__main__":
    create_final_excel()
