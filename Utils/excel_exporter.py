"""
Utils/excel_exporter.py
High-performance, professional Excel (.xlsx) export utility using openpyxl.
Formats multi-record operational reports with styled headers, auto-column widths,
currency/date formats, formula-based subtotals, and optional multi-sheet tab splitting.
"""
import io
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, date
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from Schema.ReportDatasetSchema import DatasetResult, ColumnDefinition


# Color palette: Enterprise Slate & Navy
COLOR_HEADER_BG = "1E293B"       # Dark Navy
COLOR_HEADER_TEXT = "FFFFFF"     # White
COLOR_GROUP_BG = "F1F5F9"        # Slate 100
COLOR_SUBTOTAL_BG = "E2E8F0"     # Slate 200
COLOR_TOTAL_BG = "CBD5E1"        # Slate 300
COLOR_ZEBRA_BG = "F8FAFC"        # Slate 50

# Reusable styles
FONT_TITLE = Font(name="Calibri", size=14, bold=True, color="0F172A")
FONT_SUBTITLE = Font(name="Calibri", size=11, bold=True, color="334155")
FONT_META = Font(name="Calibri", size=9, italic=True, color="64748B")
FONT_HEADER = Font(name="Calibri", size=10, bold=True, color=COLOR_HEADER_TEXT)
FONT_GROUP_HEADER = Font(name="Calibri", size=10, bold=True, color="1E293B")
FONT_SUBTOTAL = Font(name="Calibri", size=10, bold=True, color="0F172A")
FONT_GRAND_TOTAL = Font(name="Calibri", size=11, bold=True, color="0F172A")
FONT_DATA = Font(name="Calibri", size=10, color="0F172A")

FILL_HEADER = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
FILL_GROUP = PatternFill(start_color=COLOR_GROUP_BG, end_color=COLOR_GROUP_BG, fill_type="solid")
FILL_SUBTOTAL = PatternFill(start_color=COLOR_SUBTOTAL_BG, end_color=COLOR_SUBTOTAL_BG, fill_type="solid")
FILL_TOTAL = PatternFill(start_color=COLOR_TOTAL_BG, end_color=COLOR_TOTAL_BG, fill_type="solid")

BORDER_THIN_BOTTOM = Border(bottom=Side(style="thin", color="CBD5E1"))
BORDER_CELL = Border(
    left=Side(style="thin", color="E2E8F0"),
    right=Side(style="thin", color="E2E8F0"),
    top=Side(style="thin", color="E2E8F0"),
    bottom=Side(style="thin", color="E2E8F0"),
)
BORDER_SUBTOTAL = Border(
    top=Side(style="thin", color="94A3B8"),
    bottom=Side(style="double", color="475569")
)
BORDER_TOTAL = Border(
    top=Side(style="medium", color="1E293B"),
    bottom=Side(style="double", color="1E293B")
)

ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")


def _sanitize_sheet_title(name: str) -> str:
    """Removes invalid Excel worksheet characters and limits title to 31 chars."""
    clean = re.sub(r'[\:\\\/\?\*\[\]]', '_', str(name or "Sheet"))
    return clean[:31] if clean else "Sheet1"


def _format_cell_value(cell, val: Any, col_def: ColumnDefinition):
    """Sets cell value and proper Excel number/date formatting."""
    if val is None or val == "":
        cell.value = "—"
        cell.alignment = ALIGN_CENTER
        return

    data_type = col_def.data_type.lower()
    if data_type in ["number", "numeric"]:
        try:
            cell.value = float(val)
            cell.number_format = "#,##0.00" if (isinstance(val, float) or "." in str(val)) else "#,##0"
            cell.alignment = ALIGN_RIGHT
        except (ValueError, TypeError):
            cell.value = str(val)
            cell.alignment = ALIGN_LEFT
    elif data_type == "currency":
        try:
            cell.value = float(val)
            cell.number_format = "$#,##0.00"
            cell.alignment = ALIGN_RIGHT
        except (ValueError, TypeError):
            cell.value = str(val)
            cell.alignment = ALIGN_LEFT
    elif data_type == "date":
        if isinstance(val, (datetime, date)):
            cell.value = val.strftime("%Y-%m-%d")
        else:
            cell.value = str(val)
        cell.alignment = ALIGN_CENTER
    elif data_type == "boolean":
        cell.value = "YES" if bool(val) else "NO"
        cell.alignment = ALIGN_CENTER
    else:
        cell.value = str(val)
        cell.alignment = ALIGN_RIGHT if col_def.align == "right" else (ALIGN_CENTER if col_def.align == "center" else ALIGN_LEFT)


def _write_table_block(
    ws,
    columns: List[ColumnDefinition],
    records: List[Dict[str, Any]],
    start_row: int,
    show_subtotal: bool = False,
    subtotal_label: str = "Subtotal",
) -> int:
    """Writes header, rows, and optional subtotal block to worksheet. Returns next free row index."""
    curr_row = start_row

    # 1. Header Row
    for col_idx, col in enumerate(columns, 1):
        cell = ws.cell(row=curr_row, column=col_idx, value=col.label)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_RIGHT if col.align == "right" else (ALIGN_CENTER if col.align == "center" else ALIGN_LEFT)
        cell.border = BORDER_CELL
    ws.row_dimensions[curr_row].height = 24
    curr_row += 1

    first_data_row = curr_row

    # 2. Data Rows
    for r_idx, row_data in enumerate(records):
        for col_idx, col in enumerate(columns, 1):
            cell = ws.cell(row=curr_row, column=col_idx)
            val = row_data.get(col.key)
            _format_cell_value(cell, val, col)
            cell.font = FONT_DATA
            cell.border = BORDER_CELL
            if r_idx % 2 == 1:
                cell.fill = PatternFill(start_color=COLOR_ZEBRA_BG, end_color=COLOR_ZEBRA_BG, fill_type="solid")
        ws.row_dimensions[curr_row].height = 19
        curr_row += 1

    last_data_row = curr_row - 1

    # 3. Subtotal Row (if requested and we have data rows)
    if show_subtotal and records:
        for col_idx, col in enumerate(columns, 1):
            cell = ws.cell(row=curr_row, column=col_idx)
            cell.font = FONT_SUBTOTAL
            cell.fill = FILL_SUBTOTAL
            cell.border = BORDER_SUBTOTAL
            if col_idx == 1:
                cell.value = subtotal_label
                cell.alignment = ALIGN_LEFT
            elif col.aggregatable or col.is_numeric:
                col_letter = get_column_letter(col_idx)
                cell.value = f"=SUM({col_letter}{first_data_row}:{col_letter}{last_data_row})"
                cell.number_format = "$#,##0.00" if col.data_type == "currency" else "#,##0.00"
                cell.alignment = ALIGN_RIGHT
            else:
                cell.value = ""
        ws.row_dimensions[curr_row].height = 22
        curr_row += 1

    return curr_row


def build_excel_workbook(
    dataset: DatasetResult,
    sheet_per_group: bool = False,
) -> bytes:
    """
    Builds and styles an openpyxl Workbook from a DatasetResult object.
    Supports single sheet or multi-sheet splitting per group.
    """
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    columns = dataset.columns

    # ── CASE A: Multi-Sheet Mode (one tab per group) ─────────────────────────
    if sheet_per_group and dataset.is_grouped and dataset.groups:
        # Create a Master Summary Sheet first
        summary_ws = wb.create_sheet(title="Executive Summary")
        summary_ws.views.sheetView[0].showGridLines = True
        
        # Title block
        summary_ws.cell(row=1, column=1, value=dataset.org_name).font = FONT_TITLE
        summary_ws.cell(row=2, column=1, value=f"{dataset.report_title} — Group Summary").font = FONT_SUBTITLE
        summary_ws.cell(row=3, column=1, value=f"Generated: {dataset.generated_at} by {dataset.generated_by}").font = FONT_META
        
        # Write summary table across groups
        sum_row = 5
        sum_headers = ["#", "Group Name", "Total Records"]
        aggregatable_cols = [c for c in columns if c.aggregatable or c.is_numeric]
        for ac in aggregatable_cols:
            sum_headers.append(f"Total {ac.label}")
        
        for c_idx, h_text in enumerate(sum_headers, 1):
            c = summary_ws.cell(row=sum_row, column=c_idx, value=h_text)
            c.font = FONT_HEADER
            c.fill = FILL_HEADER
            c.alignment = ALIGN_CENTER if c_idx == 1 else ALIGN_LEFT
            c.border = BORDER_CELL
        sum_row += 1

        first_grp_row = sum_row
        for g_idx, grp in enumerate(dataset.groups, 1):
            summary_ws.cell(row=sum_row, column=1, value=g_idx).alignment = ALIGN_CENTER
            summary_ws.cell(row=sum_row, column=2, value=grp.group_label).alignment = ALIGN_LEFT
            summary_ws.cell(row=sum_row, column=3, value=grp.count).alignment = ALIGN_RIGHT
            
            c_offset = 4
            for ac in aggregatable_cols:
                sub_val = grp.subtotals.get(f"total_{ac.key}") or grp.subtotals.get(ac.key) or 0
                cell = summary_ws.cell(row=sum_row, column=c_offset, value=float(sub_val))
                cell.number_format = "$#,##0.00" if ac.data_type == "currency" else "#,##0.00"
                cell.alignment = ALIGN_RIGHT
                cell.border = BORDER_CELL
                c_offset += 1
            sum_row += 1

        # Summary Grand Total Row
        summary_ws.cell(row=sum_row, column=2, value="Grand Total").font = FONT_GRAND_TOTAL
        summary_ws.cell(row=sum_row, column=3, value=dataset.total_records).font = FONT_GRAND_TOTAL
        c_offset = 4
        for ac in aggregatable_cols:
            tot_val = dataset.grand_totals.get(f"total_{ac.key}") or dataset.grand_totals.get(ac.key) or 0
            cell = summary_ws.cell(row=sum_row, column=c_offset, value=float(tot_val))
            cell.font = FONT_GRAND_TOTAL
            cell.number_format = "$#,##0.00" if ac.data_type == "currency" else "#,##0.00"
            cell.alignment = ALIGN_RIGHT
            cell.border = BORDER_TOTAL
            c_offset += 1

        # Auto-fit Summary Columns
        for col in summary_ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            summary_ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

        # Now create one tab per group
        for grp in dataset.groups:
            sheet_title = _sanitize_sheet_title(grp.group_label)
            ws = wb.create_sheet(title=sheet_title)
            ws.views.sheetView[0].showGridLines = True

            # Sheet Title
            ws.cell(row=1, column=1, value=dataset.org_name).font = FONT_TITLE
            ws.cell(row=2, column=1, value=f"{dataset.report_title} — {grp.group_label}").font = FONT_SUBTITLE
            ws.cell(row=3, column=1, value=f"Records: {grp.count} | Generated: {dataset.generated_at}").font = FONT_META

            _write_table_block(
                ws=ws,
                columns=columns,
                records=grp.records,
                start_row=5,
                show_subtotal=True,
                subtotal_label=f"Total for {grp.group_label}"
            )

            # Auto-fit columns
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    # ── CASE B: Single Sheet Mode (Continuous or Grouped) ────────────────────
    else:
        ws = wb.create_sheet(title=_sanitize_sheet_title(dataset.report_title))
        ws.views.sheetView[0].showGridLines = True

        # 1. Title Block
        ws.cell(row=1, column=1, value=dataset.org_name).font = FONT_TITLE
        ws.cell(row=2, column=1, value=dataset.report_title).font = FONT_SUBTITLE

        # Filters line
        filter_parts = []
        for k, v in dataset.filters_applied.items():
            if v:
                filter_parts.append(f"{k.replace('_', ' ').title()}: {v}")
        filter_str = " | ".join(filter_parts) if filter_parts else "All Records"

        ws.cell(row=3, column=1, value=f"Filters: {filter_str}").font = FONT_META
        ws.cell(row=4, column=1, value=f"Generated: {dataset.generated_at} | By: {dataset.generated_by} | Total Records: {dataset.total_records}").font = FONT_META

        curr_row = 6

        if dataset.is_grouped and dataset.groups:
            # Render section by section
            for grp in dataset.groups:
                # Group Banner Header
                group_banner = ws.cell(row=curr_row, column=1, value=f"▶ {grp.group_label} ({grp.count} records)")
                group_banner.font = FONT_GROUP_HEADER
                group_banner.fill = FILL_GROUP
                ws.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=len(columns))
                ws.row_dimensions[curr_row].height = 24
                curr_row += 1

                curr_row = _write_table_block(
                    ws=ws,
                    columns=columns,
                    records=grp.records,
                    start_row=curr_row,
                    show_subtotal=True,
                    subtotal_label=f"Subtotal — {grp.group_label}"
                )
                curr_row += 1  # blank gap row between groups
        else:
            # Flat continuous table
            curr_row = _write_table_block(
                ws=ws,
                columns=columns,
                records=dataset.records,
                start_row=curr_row,
                show_subtotal=False
            )

        # Grand Total Row at the bottom
        for col_idx, col in enumerate(columns, 1):
            cell = ws.cell(row=curr_row, column=col_idx)
            cell.font = FONT_GRAND_TOTAL
            cell.fill = FILL_TOTAL
            cell.border = BORDER_TOTAL
            if col_idx == 1:
                cell.value = f"GRAND TOTAL ({dataset.total_records} Records)"
                cell.alignment = ALIGN_LEFT
            elif col.aggregatable or col.is_numeric:
                tot_val = dataset.grand_totals.get(f"total_{col.key}") or dataset.grand_totals.get(col.key)
                if tot_val is not None:
                    cell.value = float(tot_val)
                    cell.number_format = "$#,##0.00" if col.data_type == "currency" else "#,##0.00"
                    cell.alignment = ALIGN_RIGHT
            else:
                cell.value = ""
        ws.row_dimensions[curr_row].height = 24

        # Auto-fit Column Widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
