"""One page of a project, rendered on demand for the builder.

Synchronous, not a job. A property page carries around seventeen text fields and
every one of them goes through ``calibrated_htmlbox`` twice -- once to measure,
once to place -- so a page is a few hundred milliseconds. Queueing that, then
polling for it, would cost more than the render.

The cache key is the whole render input: template version, page, and the exact
values being drawn. A keystroke changes the key, so nothing is ever
invalidated -- entries simply stop being asked for and fall out of the LRU. That
also makes the key a good ETag: a viewer who redraws the same page twice gets a
304 rather than a second render.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from threading import Lock
from typing import Any

import fitz

from app.models import Project
from app.rendering.base import FieldSpec, PageInstance, RenderPlan
from app.rendering.overlay import PyMuPDFOverlayRenderer
from app.services import templates as template_service

#: Enough for a client to page back and forth through a booklet without
#: re-rendering, and small enough that the whole cache is a few megabytes.
MAX_ENTRIES = 96

MIN_DPI = 40
MAX_DPI = 150

_cache: OrderedDict[str, bytes] = OrderedDict()
_lock = Lock()


class PreviewError(RuntimeError):
    """The page cannot be drawn. Carries an Arabic message."""


def cache_key(
    project: Project,
    instance: PageInstance,
    dpi: int,
    assets: dict[str, bytes],
    omit: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "template": str(project.template_id),
            "version": project.template.version,
            "page": instance.template_page_index,
            "values": instance.values,
            # The holed page is a different raster of the same values: a field
            # that draws a default draws it whether or not a value was given,
            # so the hole cannot be inferred from the values alone.
            "omit": omit or "",
            "assets": sorted(assets),
            "dpi": dpi,
            # Two booklets can carry identical values and draw differently: a
            # link chip is a code on paper and a click target on screen. Without
            # this, switching the output served the raster from before it.
            "flavour": project.output_flavour,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _remember(key: str, png: bytes) -> None:
    with _lock:
        _cache[key] = png
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)


def cached(key: str) -> bytes | None:
    with _lock:
        png = _cache.get(key)
        if png is not None:
            _cache.move_to_end(key)
        return png


def clear() -> None:
    """Drop everything. Used by the tests; nothing in the app needs it."""
    with _lock:
        _cache.clear()


def render_page(
    project: Project,
    instance: PageInstance,
    *,
    dpi: int = 96,
    assets: dict[str, bytes] | None = None,
    omit: str | None = None,
) -> tuple[bytes, str, bool]:
    """Draw one page. Returns ``(png, key, was_cached)``.

    Goes through the same renderer as a real job, over the same baked artwork,
    so what the builder shows is what will print -- not a browser's idea of it.

    ``omit`` leaves one field off the page entirely -- the *field*, not merely
    its value. Dropping the value is not enough for a field that falls back to
    a ``default_value``: the auction's name is drawn on the cover whether or not
    the cover was typed on, so a page holed by clearing the value came back with
    the name still on it, and the box the client was typing into printed it a
    second time a few points away in a different font.
    """
    dpi = max(MIN_DPI, min(int(dpi), MAX_DPI))
    payload = assets or {}
    key = cache_key(project, instance, dpi, payload, omit)

    hit = cached(key)
    if hit is not None:
        return hit, key, True

    fields: list[FieldSpec]
    fields, _ = template_service.specs_for(project.template)
    fields = template_service.for_output(fields, project.output_flavour)
    if omit:
        fields = [f for f in fields if f.key != omit]
    background = template_service.open_background(project.template)
    try:
        if not 0 <= instance.template_page_index < background.page_count:
            raise PreviewError("الصفحة غير موجودة في القالب.")
        plan = RenderPlan(
            background=background,
            fields=fields,
            pages=[instance],
            assets=payload,
            design_page_height=project.template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)
    finally:
        background.close()

    with fitz.open("pdf", result.pdf) as doc:
        png = doc[0].get_pixmap(dpi=dpi).tobytes("png")

    _remember(key, png)
    return png, key, False


def issues_for(
    project: Project, instance: PageInstance, assets: dict[str, bytes] | None = None
) -> list[dict[str, Any]]:
    """What the renderer would complain about on this page, without rasterising.

    The builder shows these beside the page: a value that had to shrink, a photo
    below print resolution, a required field still empty.
    """
    fields, _ = template_service.specs_for(project.template)
    fields = template_service.for_output(fields, project.output_flavour)
    background = template_service.open_background(project.template)
    try:
        plan = RenderPlan(
            background=background,
            fields=fields,
            pages=[instance],
            assets=assets or {},
            design_page_height=project.template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)
    finally:
        background.close()
    return [
        {"field_key": issue.field_key, "cause": issue.cause, "severity": issue.severity}
        for issue in result.issues
    ]
