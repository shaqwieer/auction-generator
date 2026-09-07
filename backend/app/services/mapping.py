"""Match spreadsheet columns to template fields, then apply the mapping.

The mapping screen promises "أسماء الأعمدة لا يجب أن تتطابق حرفيًا — سنقترح الربط",
so a suggestion is made for every field we can recognise and the operator adjusts
the rest. Suggestions are never applied silently: an unconfirmed mapping still
has to pass validation before a job may start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.rendering.autokey import VOCABULARY, normalise
from app.rendering.base import FieldType
from app.services.ingest.excel import Column

# Field key -> the header spellings a client is likely to use. Built by inverting
# the printed-label vocabulary and adding the everyday synonyms.
_SYNONYMS: dict[str, set[str]] = {
    "deed_number": {"رقم الصك", "الصك", "رقم صك", "deed", "deed number"},
    "plan_number": {"رقم المخطط", "المخطط", "plan", "plan number"},
    "plot_number": {"رقم القطعة", "القطعة", "رقم قطعة", "plot", "plot number"},
    "execution_request_number": {"رقم طلب التنفيذ", "طلب التنفيذ", "رقم الطلب"},
    "area_sqm": {"المساحة", "المساحة م2", "المساحة م٢", "مساحة", "area"},
    "property_type": {"النوع", "نوع العقار", "نوع", "type"},
    "land_use": {"الاستخدام", "استخدام", "use"},
    "district": {"الحي", "حي", "district", "neighbourhood"},
    "city": {"المدينة", "مدينة", "city"},
    "entry_cheque": {"شيك الدخول", "الشيك", "شيك", "deposit"},
    "description": {"وصف العقار", "الوصف", "وصف", "description"},
    "notes": {"ملاحظات", "ملاحظة", "notes"},
    "boundary_north": {"شمالا", "الحد الشمالي", "شمال"},
    "boundary_south": {"جنوبا", "الحد الجنوبي", "جنوب"},
    "boundary_east": {"شرقا", "الحد الشرقي", "شرق"},
    "boundary_west": {"غربا", "الحد الغربي", "غرب"},
    "main_photo": {"صورة العقار", "الصورة", "صورة", "photo", "image"},
    "lot_number": {"رقم العقار", "التسلسل", "م", "#"},
    "survey_link": {"الرفع المساحي", "رابط الرفع المساحي"},
    "extra_photos_link": {"صور إضافية", "رابط الصور"},
}

for _label, _key in VOCABULARY.items():
    _SYNONYMS.setdefault(_key, set()).add(_label)

_LOOKUP: dict[str, str] = {
    normalise(spelling).casefold(): key
    for key, spellings in _SYNONYMS.items()
    for spelling in spellings
}


@dataclass
class Suggestion:
    field_key: str
    column: str | None
    confidence: float
    reason: str


@dataclass
class Problem:
    field_key: str
    message: str
    severity: str = "error"


@dataclass
class MappingReport:
    suggestions: list[Suggestion] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def mapping(self) -> dict[str, str]:
        return {s.field_key: s.column for s in self.suggestions if s.column}

    @property
    def unmapped(self) -> list[str]:
        return [s.field_key for s in self.suggestions if not s.column]


def _match(header: str) -> str | None:
    folded = normalise(header).casefold()
    if folded in _LOOKUP:
        return _LOOKUP[folded]
    # Fall back to containment, longest spelling first so "رقم الصك" beats "رقم".
    for spelling in sorted(_LOOKUP, key=len, reverse=True):
        if len(spelling) >= 4 and spelling in folded:
            return _LOOKUP[spelling]
    return None


def suggest(columns: list[Column], field_keys: list[str]) -> MappingReport:
    """Propose a column for every template field key, best effort."""
    by_key: dict[str, list[Column]] = {}
    for column in columns:
        key = _match(column.name)
        if key:
            by_key.setdefault(key, []).append(column)

    report = MappingReport()
    taken: set[str] = set()
    for key in field_keys:
        candidates = [c for c in by_key.get(key, []) if c.name not in taken]
        if candidates:
            # Prefer the column that actually has data in it.
            best = max(candidates, key=lambda c: c.non_empty)
            taken.add(best.name)
            report.suggestions.append(
                Suggestion(key, best.name, 0.9, f"العمود «{best.name}»")
            )
        else:
            report.suggestions.append(
                Suggestion(key, None, 0.0, "لم نجد عمودًا مطابقًا")
            )
    return report


def validate(
    mapping: dict[str, str | None],
    columns: list[Column],
    required_keys: list[str],
) -> list[Problem]:
    """Everything that must be true before a generation job may be queued."""
    known = {c.name for c in columns}
    problems: list[Problem] = []

    for key in required_keys:
        target = mapping.get(key)
        if not target:
            problems.append(
                Problem(key, f"حقل إلزامي بلا عمود: «{key}» — لن يبدأ التوليد قبل ربطه.")
            )
        elif target not in known and not target.startswith("="):
            problems.append(
                Problem(key, f"العمود «{target}» غير موجود في الملف المرفوع.")
            )

    for key, target in mapping.items():
        if target and target not in known and not target.startswith("="):
            problems.append(
                Problem(
                    key,
                    f"العمود «{target}» غير موجود في الملف المرفوع.",
                    severity="warning",
                )
            )
    return problems


def apply(
    mapping: dict[str, str | None], rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Turn spreadsheet rows into records keyed by template field.

    A mapping value beginning with ``=`` is a static value applied to every row --
    the mapping screen offers that as an alternative to picking a column.
    """
    records: list[dict[str, str]] = []
    for row in rows:
        record: dict[str, str] = {}
        for key, target in mapping.items():
            if not target:
                continue
            if target.startswith("="):
                record[key] = target[1:]
            else:
                record[key] = row.get(target, "")
        records.append(record)
    return records


def rejected_rows(
    records: list[dict[str, str]], required_keys: list[str]
) -> dict[int, list[str]]:
    """Rows that cannot be generated, and which required field is missing.

    The review screen uses this to say "3 صفوف ستُستبعد قبل البدء" before the job
    starts, rather than surfacing the same failure once per record afterwards.
    """
    out: dict[int, list[str]] = {}
    for index, record in enumerate(records):
        missing = [k for k in required_keys if not str(record.get(k, "")).strip()]
        if missing:
            out[index] = missing
    return out


def required_keys_for(fields: list[Any]) -> list[str]:
    """Required keys that a data row can actually supply.

    Image fields are excluded: photographs come from the asset library, not from
    a spreadsheet column, so treating them as mapping failures would block every
    job that has not uploaded its pictures yet.
    """
    return sorted(
        {
            f.key
            for f in fields
            if f.is_required and f.type is not FieldType.IMAGE
        }
    )
