"""Generate an auction booklet from a template and a set of lot records.

    python scripts/generate_booklet.py auction_infath_inperson data/hail.json out.pdf

This is the end-to-end path the API's generation job will call. It exists as a
script first so the pipeline can be exercised against the real artwork before any
HTTP or database code is written.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rendering import manifest
from app.rendering.base import RenderPlan
from app.rendering.compose import compose, page_count
from app.rendering.overlay import PyMuPDFOverlayRenderer


def load_assets(directory: Path | None) -> dict[str, bytes]:
    """Every image in ``directory``, keyed by filename.

    Mirrors the client's asset library: a record refers to a photo by name, and
    the renderer resolves it here.
    """
    if not directory or not directory.exists():
        return {}
    exts = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
    return {
        path.name: path.read_bytes()
        for path in sorted(directory.iterdir())
        if path.suffix.lower() in exts
    }


def generate(
    template_dir: Path,
    records: list[dict],
    static_values: dict,
    assets: dict[str, bytes],
    out_path: Path,
) -> dict:
    started = time.perf_counter()
    with manifest.load(template_dir) as template:
        pages = compose(
            template.sections, records, static_values=static_values
        )
        plan = RenderPlan(
            background=template.background,
            fields=template.fields,
            pages=pages,
            assets=assets,
            design_page_height=template.design_page_height,
        )
        result = PyMuPDFOverlayRenderer().render(plan)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(result.pdf)
    elapsed = time.perf_counter() - started

    errors = [i for i in result.issues if i.severity == "error"]
    return {
        "pages": result.page_count,
        "records": len(records),
        "bytes": len(result.pdf),
        "seconds": round(elapsed, 2),
        "issues": result.issues,
        "errors": len(errors),
        "warnings": len(result.issues) - len(errors),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", help="slug under var/templates/")
    parser.add_argument("data", type=Path, help="JSON: {static: {...}, records: [...]}")
    parser.add_argument("out", type=Path)
    parser.add_argument("--assets", type=Path, default=None)
    parser.add_argument("--templates-dir", type=Path, default=Path("var/templates"))
    args = parser.parse_args()

    payload = json.loads(args.data.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    static = payload.get("static", {})

    template_dir = args.templates_dir / args.template
    with manifest.load(template_dir) as template:
        predicted = page_count(template.sections, len(records))

    summary = generate(
        template_dir, records, static, load_assets(args.assets), args.out
    )

    print(f"template : {args.template}")
    print(f"records  : {summary['records']}")
    print(f"pages    : {summary['pages']} (predicted {predicted})")
    print(f"size     : {summary['bytes'] / 1e6:.2f} MB")
    print(f"time     : {summary['seconds']}s")
    print(f"issues   : {summary['errors']} errors, {summary['warnings']} warnings")
    for issue in summary["issues"][:15]:
        row = "-" if issue.row_index is None else f"{issue.row_index:>3}"
        field = issue.field_key or "-"
        print(f"   [{issue.severity:7}] row {row}  {field:<26} {issue.cause}")
    if len(summary["issues"]) > 15:
        print(f"   ... and {len(summary['issues']) - 15} more")
    print(f"written  : {args.out}")


if __name__ == "__main__":
    main()
