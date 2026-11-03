"""Excel reports for a single processed batch; no OCR or extraction logic."""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

def write_export(batch, path):
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    summary.append(["Receipt filename", "Vendor", "Date", "Receipt total",
                    "Processing status", "Extraction method"])
    items = workbook.create_sheet("Items")
    items.append(["Receipt filename", "Vendor", "Date", "Item name", "Item price"])
    errors = None

    def append_text_safe(sheet, row):
        sheet.append([ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for v in row])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    for receipt in batch["receipts"]:
        data = receipt["data"] or {}
        append_text_safe(summary, [receipt["filename"], data.get("vendor"), data.get("date"),
                                  data.get("total"), receipt["status"], receipt["method"]])
        # Receipt data is authoritative. Do not rely on the separately flattened
        # UI list, which may be absent or incomplete when a report is generated.
        if receipt["status"] == "success":
            for item in data.get("items") or []:
                append_text_safe(items, [receipt["filename"], data.get("vendor"),
                                        data.get("date"), item.get("item_name"),
                                        item.get("price")])
        if receipt["status"] == "failed":
            if errors is None:
                errors = workbook.create_sheet("Errors")
                errors.append(["Filename", "Error message", "Processing status"])
            append_text_safe(errors, [receipt["filename"], receipt["error"], receipt["status"]])
    summary.append(["Combined grand total", None, None, batch["grand_total"]])
    for cell in summary[summary.max_row]:
        cell.font = Font(bold=True)
    for sheet in workbook:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(sheet.max_column)}{sheet.max_row - (1 if sheet == summary else 0)}"
        for cell in sheet[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="243B53")
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(65, max(16, max(len(str(c.value or "")) for c in column) + 2))
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        price_column = 4 if sheet == summary else 5 if sheet == items else None
        if price_column:
            for row in sheet.iter_rows(min_row=2, min_col=price_column, max_col=price_column):
                row[0].number_format = '"$"#,##0.00;[Red]("$"#,##0.00)'
    staging = path.with_suffix(".tmp")
    try:
        workbook.save(staging)
        staging.replace(path)
    finally:
        workbook.close()
        staging.unlink(missing_ok=True)
