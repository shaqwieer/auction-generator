"""Human-readable causes for generation problems.

The product is Arabic-only and the error table is shown verbatim to the client,
so the strings live here rather than being assembled at the call site. Every
message names the field; the caller adds the row index.
"""

from __future__ import annotations

REQUIRED_EMPTY = "الحقل «{label}» إلزامي وقيمته فارغة — سيُرفض الصفّ."
IMAGE_MISSING = "الحقل «{label}» صورة مطلوبة ولم تُرفَق — سيظهر الموضع شاغرًا."
IMAGE_UNREADABLE = "تعذّرت قراءة صورة الحقل «{label}»: {detail}"
IMAGE_LOW_DPI = "صورة الحقل «{label}» بدقّة {dpi} فقط — أقل من 300 نقطة/بوصة المطلوبة للطبع."
TEXT_CLIPPED = "نص «{label}» أطول من الحقل بـ {chars} حرفًا — قُصّ ما لا يتّسع."
TEXT_SHRUNK = "نص «{label}» صُغّر إلى {pct}% ليتّسع داخل الحقل."
TEXT_OVERFLOW = "نص «{label}» يتجاوز حدود الحقل."
FONT_MISSING = "الخط المطلوب للحقل «{label}» غير مضمَّن في القالب: {detail}"
CODE_FAILED = "تعذّر توليد {kind} للحقل «{label}»: {detail}"
LINK_INVALID = "قيمة الرابط في الحقل «{label}» ليست رابطًا صالحًا: {value}"
TABLE_NOT_RENDERED = (
    "{rows} صفًّا في جدول الملخّص لا تتّسع لها الصفحة — "
    "زد عدد صفحات الجدول في القالب أو قلّل عدد السجلات."
)
