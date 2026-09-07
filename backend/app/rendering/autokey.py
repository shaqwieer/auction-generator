"""Suggest field keys by pairing a printed label with the value beside it.

Illustrator bakes Arabic into presentation forms, so a raw extraction of the
label ``النوع`` comes back as ``اﻟﻨﻮع``. NFKC normalisation maps those forms back
to their base letters and recovers the term exactly, which lets us match against
a controlled vocabulary.

That is the *only* sanctioned use of extracted text. It never becomes a displayed
label or a default value -- it selects a key from the vocabulary below, and the
admin confirms it in the editor. Anything unrecognised is left unnamed rather
than guessed at.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .base import FieldType
from .derive import DerivedField

# Printed label (normalised) -> stable field key.
VOCABULARY: dict[str, str] = {
    "النوع": "property_type",
    "نوع العقار": "property_type",
    "رقم الصك": "deed_number",
    "رقم المخطط": "plan_number",
    "رقم القطعة": "plot_number",
    "رقم طلب التنفيذ": "execution_request_number",
    "المساحة": "area_sqm",
    "المساحة م": "area_sqm",
    "المساحة م٢": "area_sqm",
    "المساحة م2": "area_sqm",
    "الاستخدام": "land_use",
    "الحي": "district",
    "شيك الدخول": "entry_cheque",
    "المدينة": "city",
    "شمالا": "boundary_north",
    "جنوبا": "boundary_south",
    "شرقا": "boundary_east",
    "غربا": "boundary_west",
    "الحدود": "boundaries",
    "الأطوال": "lengths",
    "وصف العقار": "description",
    "ملاحظات": "notes",
    "ملاحظات :": "notes",
    "معلومات اضافية": "extra_info",
    "معلومات الإيجار": "rent_info",
    "الرفع المساحي": "survey_link",
    "صور إضافية": "extra_photos_link",
    "تاريخ المزاد": "auction_date",
    "الموقع": "location",
    "إسم المنصة": "platform_name",
}

# Colours the designer used for values rather than chrome. Derived from the real
# artwork: teal #1A9F9F is a label, the navies are values.
VALUE_COLORS = {"#0D3759", "#14385F", "#001447"}
LABEL_COLORS = {"#1A9F9F"}


def normalise(text: str) -> str:
    """Recover base Arabic letters from Illustrator's presentation forms."""
    folded = unicodedata.normalize("NFKC", text or "")
    # Drop combining marks; the extraction reorders tanween unpredictably.
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(stripped.split()).strip(" :،")


@dataclass
class Suggestion:
    field: DerivedField
    key: str
    label: str
    role: str  # "value" | "label" | "unknown"
    confidence: float


def _same_row(a: DerivedField, b: DerivedField, tol: float = 6.0) -> bool:
    ay = (a.rect_pt.y0 + a.rect_pt.y1) / 2
    return b.rect_pt.y0 - tol <= ay <= b.rect_pt.y1 + tol


def suggest(fields: list[DerivedField]) -> list[Suggestion]:
    """Pair each recognised label with the value immediately to its left.

    Arabic reads right-to-left, so a field's value sits to the *left* of its
    printed label on the same row.
    """
    out: list[Suggestion] = []
    labels: list[tuple[DerivedField, str, str]] = []

    for f in fields:
        if f.type is not FieldType.TEXT or f.color not in LABEL_COLORS:
            continue
        term = normalise(f.sample_text)
        key = VOCABULARY.get(term)
        if key:
            labels.append((f, key, term))

    claimed: set[int] = set()
    for label_field, key, term in labels:
        candidates = [
            f
            for f in fields
            if id(f) not in claimed
            and f.type is FieldType.TEXT
            and f.color in VALUE_COLORS
            and _same_row(f, label_field)
            and f.rect_pt.x1 <= label_field.rect_pt.x0 + 1
        ]
        if not candidates:
            out.append(
                Suggestion(label_field, key, term, role="label", confidence=0.5)
            )
            continue
        # Nearest to the label wins.
        value = max(candidates, key=lambda f: f.rect_pt.x1)
        claimed.add(id(value))
        out.append(Suggestion(value, key, term, role="value", confidence=0.9))
        out.append(Suggestion(label_field, key, term, role="label", confidence=0.9))

    return out


def suggested_keys(fields: list[DerivedField]) -> dict[int, Suggestion]:
    """Index suggestions by ``id()`` of the derived field, values only."""
    return {id(s.field): s for s in suggest(fields) if s.role == "value"}
