"""Font registry for the PDF renderer.

Fonts are loaded as bytes and handed to MuPDF through an in-memory
``fitz.Archive``. That matters for two reasons:

1. Shaping must come from the font's OpenType GSUB tables. The client's brand
   font (RuaqArabic) carries only 301 glyphs and has no legacy presentation-form
   cmap, so the ``arabic-reshaper`` approach emits NUL glyphs for ز, د and أ.
   See ``docs/engine-decision.md``.
2. MuPDF's CSS parser chokes on non-ASCII characters in ``url()`` paths. Serving
   the bytes from an archive under an ASCII alias sidesteps that entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import fitz

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Codepoints every Arabic text font in a template must cover. These are logical
# Arabic (U+06xx), not presentation forms -- if a font only covered presentation
# forms we would be back to the reshaper trap.
# U+063B..U+063F are unassigned gaps in the Arabic block -- excluded deliberately,
# as are the extended letters used only by non-Arabic languages.
REQUIRED_CODEPOINTS: tuple[int, ...] = (
    *range(0x0621, 0x063B),  # ء .. غ
    0x0640,                  # tatweel
    *range(0x0641, 0x064B),  # ف .. ي
    *range(0x064B, 0x0653),  # harakat: fathatan .. sukun
)


class FontError(RuntimeError):
    """Raised when a template references a font we cannot embed."""


@dataclass(frozen=True)
class FontFace:
    """One concrete font file: a family plus a weight."""

    family: str
    weight: str
    path: Path

    @property
    def alias(self) -> str:
        """ASCII name used inside the generated CSS and the archive."""
        return f"{self.family}-{self.weight}".lower()

    @property
    def css_family(self) -> str:
        return self.alias


class FontRegistry:
    """Holds the font faces available to a template and builds MuPDF inputs."""

    def __init__(self, faces: list[FontFace]) -> None:
        self._faces: dict[str, FontFace] = {f.alias: f for f in faces}
        self._bytes: dict[str, bytes] = {}

    @property
    def faces(self) -> list[FontFace]:
        return list(self._faces.values())

    def face(self, family: str, weight: str) -> FontFace:
        alias = f"{family}-{weight}".lower()
        try:
            return self._faces[alias]
        except KeyError:
            available = ", ".join(sorted(self._faces)) or "(none)"
            raise FontError(
                f"font not embedded: {family}-{weight}. Available: {available}"
            ) from None

    def data(self, face: FontFace) -> bytes:
        if face.alias not in self._bytes:
            self._bytes[face.alias] = face.path.read_bytes()
        return self._bytes[face.alias]

    def archive(self) -> fitz.Archive:
        """An in-memory archive MuPDF can resolve ``url(alias.font)`` against."""
        arch = fitz.Archive()
        for face in self._faces.values():
            arch.add(self.data(face), f"{face.alias}.font")
        return arch

    def css(self) -> str:
        """``@font-face`` rules covering every registered face."""
        return "".join(
            f"@font-face{{font-family:{f.css_family};src:url({f.alias}.font);}}"
            for f in self._faces.values()
        ) + "*{margin:0;padding:0;}"

    def validate(self, face: FontFace) -> list[str]:
        """Return the human-readable problems with this face, empty if fine.

        Called at template *publish* time, not render time -- the failure mode we
        are guarding against is the one in the ops screen:
        ``ERR font not embedded: IBMPlexSansArabic-SemiBold``.
        """
        problems: list[str] = []
        try:
            font = fitz.Font(fontbuffer=self.data(face))
        except Exception as exc:
            return [f"{face.alias}: cannot be parsed as a font ({exc})"]

        missing = [cp for cp in REQUIRED_CODEPOINTS if font.has_glyph(cp) == 0]
        if missing:
            sample = " ".join(f"U+{cp:04X}" for cp in missing[:8])
            problems.append(
                f"{face.alias}: missing {len(missing)} required Arabic codepoints "
                f"(e.g. {sample})"
            )
        return problems


@lru_cache(maxsize=1)
def brand_registry() -> FontRegistry:
    """The Infath/Aayan brand fonts shipped with the app."""
    faces: list[FontFace] = []
    for path in sorted(FONT_DIR.glob("*")):
        if path.suffix.lower() not in {".ttf", ".otf"}:
            continue
        stem = path.stem
        family, _, weight = stem.partition("-")
        faces.append(FontFace(family=family, weight=weight or "Regular", path=path))
    if not faces:
        raise FontError(f"no font files found in {FONT_DIR}")
    return FontRegistry(faces)
