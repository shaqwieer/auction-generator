"""Read lot data out of a spreadsheet the client uploaded.

Never trust the file. Real workbooks from this client's world arrive with merged
header cells, blank spacer rows, deed numbers stored as text so the leading zero
survives, Arabic headers with stray tatweel, and a stray total row at the bottom.
All of that is handled here so the rest of the system sees a clean list of dicts.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 5_000  # matches the admin settings screen
PREVIEW_ROWS = 5

_TATWEEL = "ـ"
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")


class IngestError(ValueError):
    """The upload cannot be read at all. Anything softer becomes a warning."""


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA. The mapping screen prints these."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def clean_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace(_TATWEEL, "")
    return " ".join(text.split()).strip()


def clean_cell(value: Any) -> str:
    """Normalise one cell to the string the renderer will draw.

    Numbers keep their spreadsheet appearance rather than Python's repr: a deed
    number must not become ``5.42104012563e+11`` and an integer must not gain a
    trailing ``.0``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10g}"
    return " ".join(str(value).split()).strip()


def looks_numeric(text: str) -> bool:
    if not text:
        return False
    candidate = text.translate(_ARABIC_DIGITS).replace(",", "").replace(" ", "")
    return bool(re.fullmatch(r"[-+]?\d*\.?\d+", candidate))


@dataclass
class Column:
    index: int
    name: str
    letter: str
    sample: str = ""
    kind: str = "text"        # text | number | date | empty
    non_empty: int = 0

    @property
    def tag(self) -> str:
        """Short label the mapping screen shows next to the column name."""
        return {"number": "رقم", "date": "تاريخ", "empty": "فارغ"}.get(
            self.kind, "نص"
        )


@dataclass
class Dataset:
    columns: list[Column]
    rows: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)
    sheet: str = ""

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def preview(self) -> list[dict[str, str]]:
        return self.rows[:PREVIEW_ROWS]


def read(data: bytes, filename: str, *, sheet: str | None = None) -> Dataset:
    """Parse an uploaded spreadsheet into columns and rows."""
    if not data:
        raise IngestError("الملف فارغ.")
    if len(data) > MAX_BYTES:
        raise IngestError(
            f"حجم الملف {len(data) / 1e6:.1f} ميجابايت — الحدّ الأقصى 25 ميجابايت."
        )

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "csv":
        grid, sheet_name = _read_csv(data), "CSV"
    elif suffix in {"xlsx", "xlsm"}:
        grid, sheet_name = _read_xlsx(data, sheet)
    elif suffix == "xls":
        raise IngestError(
            "صيغة .xls القديمة غير مدعومة — احفظ الملف بصيغة .xlsx ثم أعد الرفع."
        )
    else:
        raise IngestError(f"صيغة غير مدعومة: .{suffix or '?'} — استخدم .xlsx أو .csv")

    return _to_dataset(grid, sheet_name)


def _read_csv(data: bytes) -> list[list[Any]]:
    # utf-8-sig strips the BOM Excel writes; without it every Arabic header in
    # the first column arrives with a leading zero-width character.
    for encoding in ("utf-8-sig", "utf-8", "cp1256"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise IngestError("تعذّر تحديد ترميز الملف — احفظه بترميز UTF-8.")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _read_xlsx(data: bytes, sheet: str | None) -> tuple[list[list[Any]], str]:
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    except Exception as exc:
        raise IngestError(f"تعذّرت قراءة الملف: {exc}") from exc

    worksheet = book[sheet] if sheet and sheet in book.sheetnames else book.active
    grid = [list(row) for row in worksheet.iter_rows(values_only=True)]

    # A merged header spills its value into the top-left cell only; every other
    # cell in the range reads as None. Fill the range so the header survives.
    for merged in worksheet.merged_cells.ranges:
        top, left = merged.min_row - 1, merged.min_col - 1
        if top >= len(grid) or left >= len(grid[top]):
            continue
        value = grid[top][left]
        if value is None:
            continue
        for r in range(merged.min_row - 1, merged.max_row):
            for c in range(merged.min_col - 1, merged.max_col):
                if r < len(grid) and c < len(grid[r]) and grid[r][c] is None:
                    grid[r][c] = value

    book.close()
    return grid, worksheet.title


def _to_dataset(grid: list[list[Any]], sheet_name: str) -> Dataset:
    warnings: list[str] = []

    # A workbook usually opens with a title row, so prefer the first row that
    # looks like a header (two or more filled cells). A genuinely single-column
    # file -- one field on a banner, say -- has no such row and falls back to the
    # first row with anything in it at all.
    filled = [sum(1 for cell in row if clean_header(cell)) for row in grid]
    header_index = next((i for i, n in enumerate(filled) if n >= 2), None)
    if header_index is None:
        header_index = next((i for i, n in enumerate(filled) if n >= 1), None)
    if header_index is None:
        raise IngestError("لم يُعثر على صفّ عناوين في الملف.")
    if header_index > 0:
        warnings.append(
            f"تجاهلنا {header_index} صفًّا قبل صفّ العناوين."
        )

    raw_headers = grid[header_index]
    columns: list[Column] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(raw_headers):
        name = clean_header(raw)
        if not name:
            name = f"عمود {column_letter(index)}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
            warnings.append(f"تكرّر اسم العمود «{clean_header(raw)}» — أعدنا تسميته.")
        else:
            seen[name] = 1
        columns.append(Column(index=index, name=name, letter=column_letter(index)))

    rows: list[dict[str, str]] = []
    truncated = False
    for raw_row in grid[header_index + 1 :]:
        values = {
            column.name: clean_cell(
                raw_row[column.index] if column.index < len(raw_row) else None
            )
            for column in columns
        }
        if not any(values.values()):
            continue  # blank spacer row
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        rows.append(values)

    if truncated:
        warnings.append(
            f"الملف يتجاوز {MAX_ROWS} صفًّا — قرأنا الحدّ الأقصى فقط."
        )

    for column in columns:
        seen_values = [r[column.name] for r in rows if r[column.name]]
        column.non_empty = len(seen_values)
        column.sample = seen_values[0] if seen_values else ""
        if not seen_values:
            column.kind = "empty"
        elif all(looks_numeric(v) for v in seen_values):
            column.kind = "number"
        elif all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in seen_values):
            column.kind = "date"

    empty_columns = [c.name for c in columns if c.kind == "empty"]
    if empty_columns:
        warnings.append(
            f"{len(empty_columns)} عمودًا بلا بيانات: {'، '.join(empty_columns[:3])}"
        )
    if not rows:
        warnings.append("لا توجد صفوف بيانات بعد صفّ العناوين.")

    return Dataset(columns=columns, rows=rows, warnings=warnings, sheet=sheet_name)


def sheet_names(data: bytes, filename: str) -> list[str]:
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        return []
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True)
    names = list(book.sheetnames)
    book.close()
    return names
