"""Spreadsheet parsing and column mapping -- the parts that break silently."""

from __future__ import annotations

import io
from datetime import datetime

import pytest
from openpyxl import Workbook

from app.services import mapping
from app.services.ingest import excel
from app.services.ingest.excel import IngestError


def workbook(rows: list[list], *, merges: list[str] | None = None) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "العقارات"
    for row in rows:
        sheet.append(row)
    for merge in merges or []:
        sheet.merge_cells(merge)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


HEADERS = ["رقم الصك", "نوع العقار", "المدينة", "الحي", "المساحة م٢", "شيك الدخول"]


def test_reads_arabic_headers_and_rows():
    data = workbook([HEADERS, ["542104012563", "فيلا", "حائل", "الخطة", 875, "10,000"]])
    result = excel.read(data, "lots.xlsx")
    assert [c.name for c in result.columns] == HEADERS
    assert [c.letter for c in result.columns[:3]] == ["A", "B", "C"]
    assert result.row_count == 1
    assert result.rows[0]["رقم الصك"] == "542104012563"
    assert result.sheet == "العقارات"


def test_deed_numbers_never_become_floats():
    """A 12-digit number must not come back as 5.42104012563e+11."""
    data = workbook([HEADERS, [542104012563, "فيلا", "حائل", "الخطة", 875.0, 10000]])
    result = excel.read(data, "lots.xlsx")
    assert result.rows[0]["رقم الصك"] == "542104012563"
    assert result.rows[0]["المساحة م٢"] == "875", "integral floats lose the .0"


def test_decimal_areas_keep_their_precision():
    data = workbook([HEADERS, ["1", "فيلا", "حائل", "الخطة", 1130.451, "1"]])
    assert excel.read(data, "lots.xlsx").rows[0]["المساحة م٢"] == "1130.451"


def test_blank_spacer_rows_are_dropped():
    data = workbook(
        [
            HEADERS,
            ["1", "فيلا", "حائل", "الخطة", 100, "1"],
            [None, None, None, None, None, None],
            ["", "", "", "", "", ""],
            ["2", "أرض", "حائل", "أركان", 200, "2"],
        ]
    )
    result = excel.read(data, "lots.xlsx")
    assert result.row_count == 2
    assert [r["رقم الصك"] for r in result.rows] == ["1", "2"]


def test_rows_above_the_header_are_skipped():
    data = workbook(
        [
            ["مزاد أعيان حائل", None, None, None, None, None],
            [None, None, None, None, None, None],
            HEADERS,
            ["1", "فيلا", "حائل", "الخطة", 100, "1"],
        ]
    )
    result = excel.read(data, "lots.xlsx")
    assert [c.name for c in result.columns] == HEADERS
    assert result.row_count == 1
    assert any("صفًّا قبل صفّ العناوين" in w for w in result.warnings)


def test_merged_header_cells_are_filled():
    data = workbook(
        [["بيانات العقار", None, "الموقع", None], ["1", "2", "3", "4"]],
        merges=["A1:B1", "C1:D1"],
    )
    result = excel.read(data, "lots.xlsx")
    assert [c.name for c in result.columns] == [
        "بيانات العقار",
        "بيانات العقار (2)",
        "الموقع",
        "الموقع (2)",
    ]
    assert any("تكرّر اسم العمود" in w for w in result.warnings)


def test_blank_headers_get_a_column_letter_name():
    data = workbook([["رقم الصك", None, "المدينة"], ["1", "x", "حائل"]])
    names = [c.name for c in excel.read(data, "lots.xlsx").columns]
    assert names[1] == "عمود B"


def test_column_types_and_samples_are_detected():
    data = workbook(
        [
            HEADERS,
            ["542104012563", "فيلا", "حائل", "الخطة", 875, "10,000"],
            ["942121002580", "أرض", "حائل", "أركان", 1130, "20,000"],
        ]
    )
    by_name = {c.name: c for c in excel.read(data, "lots.xlsx").columns}
    assert by_name["رقم الصك"].kind == "number"
    assert by_name["نوع العقار"].kind == "text"
    assert by_name["نوع العقار"].tag == "نص"
    assert by_name["رقم الصك"].sample == "542104012563"
    assert by_name["المدينة"].non_empty == 2


def test_empty_columns_are_flagged():
    data = workbook([HEADERS, ["1", "فيلا", "حائل", "الخطة", 100, None]])
    result = excel.read(data, "lots.xlsx")
    by_name = {c.name: c for c in result.columns}
    assert by_name["شيك الدخول"].kind == "empty"
    assert any("بلا بيانات" in w for w in result.warnings)


def test_dates_are_normalised():
    data = workbook([["التاريخ"], [datetime(2026, 7, 27, 10, 30)]])
    result = excel.read(data, "lots.xlsx")
    assert result.rows[0]["التاريخ"] == "2026-07-27"
    assert result.columns[0].kind == "date"


def test_csv_with_bom_keeps_the_first_arabic_header():
    body = "رقم الصك,المدينة\n542104012563,حائل\n"
    result = excel.read(body.encode("utf-8-sig"), "lots.csv")
    assert [c.name for c in result.columns] == ["رقم الصك", "المدينة"]
    assert result.rows[0]["المدينة"] == "حائل"


def test_csv_with_semicolons_is_sniffed():
    body = "رقم الصك;المدينة\n1;حائل\n"
    result = excel.read(body.encode("utf-8"), "lots.csv")
    assert [c.name for c in result.columns] == ["رقم الصك", "المدينة"]


def test_row_cap_is_enforced():
    rows = [HEADERS] + [[str(i), "فيلا", "حائل", "الخطة", 1, "1"] for i in range(20)]
    data = workbook(rows)
    original = excel.MAX_ROWS
    excel.MAX_ROWS = 10
    try:
        result = excel.read(data, "lots.xlsx")
    finally:
        excel.MAX_ROWS = original
    assert result.row_count == 10
    assert any("يتجاوز" in w for w in result.warnings)


@pytest.mark.parametrize(
    "payload,name,message",
    [
        (b"", "a.xlsx", "فارغ"),
        (b"x", "a.pdf", "صيغة غير مدعومة"),
        (b"x", "a.xls", "‎.xls".strip("‎")),
    ],
)
def test_bad_uploads_are_rejected_clearly(payload, name, message):
    with pytest.raises(IngestError) as exc:
        excel.read(payload, name)
    assert message in str(exc.value)


def test_oversized_upload_is_rejected():
    with pytest.raises(IngestError, match="الحدّ الأقصى"):
        excel.read(b"x" * (excel.MAX_BYTES + 1), "big.xlsx")


def test_header_only_file_warns_rather_than_crashing():
    result = excel.read(workbook([HEADERS]), "lots.xlsx")
    assert result.row_count == 0
    assert any("لا توجد صفوف" in w for w in result.warnings)


# --------------------------------------------------------------------------
# Mapping


FIELD_KEYS = [
    "deed_number", "property_type", "city", "district",
    "area_sqm", "entry_cheque", "description",
]


def columns_from(headers: list[str]) -> list[excel.Column]:
    return [
        excel.Column(i, name, excel.column_letter(i), sample="x", non_empty=3)
        for i, name in enumerate(headers)
    ]


def test_arabic_headers_auto_map_to_field_keys():
    report = mapping.suggest(columns_from(HEADERS), FIELD_KEYS)
    assert report.mapping["deed_number"] == "رقم الصك"
    assert report.mapping["property_type"] == "نوع العقار"
    assert report.mapping["area_sqm"] == "المساحة م٢"
    assert report.mapping["entry_cheque"] == "شيك الدخول"


def test_headers_need_not_match_literally():
    report = mapping.suggest(
        columns_from(["الصك", "نوع", "مدينة", "حي", "مساحة"]), FIELD_KEYS
    )
    assert report.mapping["deed_number"] == "الصك"
    assert report.mapping["city"] == "مدينة"


def test_english_headers_also_map():
    report = mapping.suggest(
        columns_from(["Deed Number", "Type", "City", "Area"]), FIELD_KEYS
    )
    assert report.mapping["deed_number"] == "Deed Number"
    assert report.mapping["city"] == "City"


def test_unmatched_fields_are_left_for_the_operator():
    report = mapping.suggest(columns_from(["رقم الصك"]), FIELD_KEYS)
    assert report.mapping == {"deed_number": "رقم الصك"}
    assert "description" in report.unmapped


def test_one_column_is_never_claimed_twice():
    report = mapping.suggest(columns_from(["النوع"]), ["property_type", "land_use"])
    assigned = [s.column for s in report.suggestions if s.column]
    assert len(assigned) == len(set(assigned))


def test_validation_blocks_an_unmapped_required_field():
    problems = mapping.validate(
        {"deed_number": "رقم الصك", "property_type": None},
        columns_from(HEADERS),
        ["deed_number", "property_type"],
    )
    assert [p.field_key for p in problems] == ["property_type"]
    assert problems[0].severity == "error"


def test_validation_rejects_a_column_that_is_not_in_the_file():
    problems = mapping.validate(
        {"deed_number": "عمود مفقود"}, columns_from(HEADERS), ["deed_number"]
    )
    assert any("غير موجود" in p.message for p in problems)


def test_static_values_satisfy_a_required_field():
    problems = mapping.validate(
        {"city": "=حائل"}, columns_from(HEADERS), ["city"]
    )
    assert problems == []


def test_apply_builds_records_keyed_by_field():
    rows = [{"رقم الصك": "1", "المدينة": "حائل"}, {"رقم الصك": "2", "المدينة": "بقعاء"}]
    records = mapping.apply(
        {"deed_number": "رقم الصك", "city": "المدينة", "country": "=السعودية"}, rows
    )
    assert records == [
        {"deed_number": "1", "city": "حائل", "country": "السعودية"},
        {"deed_number": "2", "city": "بقعاء", "country": "السعودية"},
    ]


def test_rejected_rows_name_the_row_and_the_field():
    records = [
        {"deed_number": "1", "city": "حائل"},
        {"deed_number": "", "city": "حائل"},
        {"deed_number": "3", "city": ""},
    ]
    rejected = mapping.rejected_rows(records, ["deed_number", "city"])
    assert rejected == {1: ["deed_number"], 2: ["city"]}


def test_required_keys_exclude_images(template_dir):
    from app.rendering import manifest

    with manifest.load(template_dir) as template:
        keys = mapping.required_keys_for(template.fields)
    assert "deed_number" in keys
    assert "main_photo" not in keys, "photos come from the asset library, not Excel"
