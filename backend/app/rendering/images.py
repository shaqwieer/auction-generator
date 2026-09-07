"""Prepare uploaded photographs for placement in a print PDF.

Two jobs: crop to the placement rectangle's aspect so the photo is not stretched,
and resample to the print resolution *for that rectangle*. The source material is
phone photography -- the auction booklet carries 4032x2268 and 8064x4536 frames
-- and embedding those untouched is what makes a generated booklet unshippable.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import fitz
from PIL import Image, ImageDraw

PRINT_DPI = 300
MIN_PRINT_DPI = 300  # the platform setting the admin screen exposes


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    width: int
    height: int
    effective_dpi: float
    below_min_dpi: bool
    #: A stencil the same size as ``data``, where the frame is not a rectangle.
    #: Kept apart from the photograph rather than baked into it as an alpha
    #: channel: a masked RGBA photograph has to be written as PNG, and a page of
    #: 4032x2268 phone photography is several megabytes that way and a few
    #: hundred kilobytes as JPEG.
    mask: bytes | None = None


def _stencil(
    clip: list[list[float]],
    size: tuple[int, int],
    holes: list[list[list[float]]] | None = None,
) -> bytes:
    """The frame's shape as a black-and-white mask over the placed image.

    Holes are the shapes the designer draws *over* the photograph — the property
    number's badge, the closing-time chip. A photograph is placed on top of the
    baked artwork, so without them it covers the very things printed over it.
    """
    width, height = size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([(x * width, y * height) for x, y in clip], fill=255)
    for hole in holes or []:
        if len(hole) >= 3:
            draw.polygon([(x * width, y * height) for x, y in hole], fill=0)
    buf = io.BytesIO()
    mask.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def prepare(
    raw: bytes,
    rect: fitz.Rect,
    *,
    dpi: int = PRINT_DPI,
    cover: bool = True,
    clip: list[list[float]] | None = None,
    holes: list[list[list[float]]] | None = None,
) -> PreparedImage:
    """Fit ``raw`` to ``rect`` and resample it to ``dpi``.

    ``cover`` crops to the box's aspect and fills it, which is what a photograph
    in a frame the designer drew should do. Without it the whole image is kept
    and scaled to fit inside instead — for a logo, where cropping loses part of
    the mark and stretching ruins it — and transparency is kept with it, so a
    mark on a dark page is not printed on a white tile.

    ``clip`` is the frame's real shape, where it is not a rectangle. The lot page
    cuts a corner out of its photo frame for the property number, and a
    photograph filling the bounding box printed a square corner over the badge.
    """
    with Image.open(io.BytesIO(raw)) as img:
        keep_alpha = not cover and img.mode in ("RGBA", "LA", "P")
        if keep_alpha:
            img = img.convert("RGBA")
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        src_w, src_h = img.size

        target_w = max(1, round(rect.width / 72.0 * dpi))
        target_h = max(1, round(rect.height / 72.0 * dpi))

        if cover:
            scale = max(target_w / src_w, target_h / src_h)
            crop_w = min(src_w, round(target_w / scale))
            crop_h = min(src_h, round(target_h / scale))
            left = (src_w - crop_w) // 2
            top = (src_h - crop_h) // 2
            img = img.crop((left, top, left + crop_w, top + crop_h))
            out_w, out_h = min(target_w, img.width), min(target_h, img.height)
        else:
            # Never upscale, so a small mark stays small and is reported.
            scale = min(target_w / src_w, target_h / src_h, 1.0)
            out_w = max(1, round(src_w * scale))
            out_h = max(1, round(src_h * scale))

        if (out_w, out_h) != img.size:
            img = img.resize((out_w, out_h), Image.LANCZOS)

        buf = io.BytesIO()
        if keep_alpha:
            img.save(buf, format="PNG", optimize=True)
        else:
            img.save(buf, format="JPEG", quality=88, optimize=True)
        data = buf.getvalue()
        effective = (img.width / (rect.width / 72.0)) if rect.width else 0.0
        return PreparedImage(
            data=data,
            width=img.width,
            height=img.height,
            effective_dpi=round(effective, 1),
            below_min_dpi=effective < MIN_PRINT_DPI - 1,
            mask=(
                _stencil(clip, img.size, holes)
                if clip and len(clip) >= 3
                else None
            ),
        )


def qr_png(
    value: str,
    *,
    box_size: int = 10,
    border: int = 1,
    colour: str = "#000000",
) -> bytes:
    """A QR code in the colour the page prints it in, on a transparent ground.

    Black on white is the default everywhere and wrong here: the booklet's codes
    are set in the brand teal, and a white tile behind one would sit on the page
    as a patch. Scanners read colour on light ground perfectly well — the code's
    own contrast is what matters, and teal on paper has plenty.
    """
    import qrcode

    qr = qrcode.QRCode(box_size=box_size, border=border)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color=colour, back_color="white").convert("RGBA")
    ink = tuple(int(colour.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    image.putdata(
        [
            (*ink, 255) if sum(abs(dot[c] - ink[c]) for c in range(3)) < 60
            else (255, 255, 255, 0)
            for dot in image.getdata()
        ]
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def barcode_png(value: str, *, symbology: str = "code128") -> bytes:
    import barcode
    from barcode.writer import ImageWriter

    cls = barcode.get_barcode_class(symbology)
    buf = io.BytesIO()
    cls(value, writer=ImageWriter()).write(buf, {"write_text": False})
    return buf.getvalue()
