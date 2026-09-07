# PDF engine decision

**Decision:** overlay variable data onto the designer's own artwork using PyMuPDF,
with text placed through MuPDF's Story engine (`insert_htmlbox`).

**Status:** decided, implemented in `backend/app/rendering/`.

All figures below were measured on the client's real files — the two auction
booklet exports, the six cover `.ai` files, and the licensed brand fonts — not
estimated.

## The constraint that actually decided it

The brief expected Arabic shaping to be the deciding factor. It was not. Two
different measurements settled the question before shaping was even reached.

### 1. The classic Python stack is disqualified by the client's own fonts

`arabic-reshaper` converts logical Arabic into Unicode **presentation forms**
(U+FB50–U+FEFF) and `python-bidi` reorders them. That only works if the font maps
those codepoints. `RuaqArabic-Medium` carries **301 glyphs** and maps none of the
relevant ones:

| letter | logical | mapped | presentation form | mapped |
|---|---|---|---|---|
| م | U+0645 | yes | U+FEE3 | yes |
| ز | U+0632 | yes | U+FEAF | **no** |
| د | U+062F | yes | U+FEA9 | **no** |
| أ | U+0623 | yes | U+FE84 | yes |

Rendering `مزاد أعيان حائل` through reshaper + ReportLab produced
`ﻣﺰ\x00\x00 \x00ﻋﻴﺎ\x00 ﺣﺎﺋﻞ` — NUL glyphs where the font had no presentation
form. The font expects shaping to come from its OpenType **GSUB** tables.

`tests/test_guards.py` fails the build if anything under `app/rendering/` imports
either library.

### 2. The HTML route would destroy the design

An HTML/Chromium renderer needs the artwork as a background. Illustrator's SVG
export **outlines the Arabic**: `Artboard 17.svg` contains 115 `<path>` elements,
3 `<text>` elements and zero `font-family` references. `Artboard 1.svg` is 5.3 MB
for a single A4 page. So the SVG background route loses live text and bloats;
the alternative — rebuilding 16 pages of Illustrator artwork in HTML/CSS — is
days of work that would never match, and would have to be redone on every design
revision.

Rasterising the pages instead would turn the static body copy (the Infath and
Aayan boilerplate) into pixels.

### 3. The colour argument that would have favoured overlay does not apply

Worth recording because it is counter-intuitive: the client's "print-ready" files
are **DeviceRGB throughout**. Scanning every object in both booklets found 0 ×
`DeviceCMYK`, 0 × `Separation`, 0 × `DeviceN`, and no `OutputIntent`. Page boxes
are `media = crop = trim = bleed = exact A4` — there is no bleed either.

So CMYK fidelity did *not* decide this. The mockups expose CMYK and 3 mm bleed as
output toggles; they are built as optional post-processing, defaulted off, because
enabling them would alter colours the client has already approved.

## Why overlay works

| Property | Measurement |
|---|---|
| Arabic shaping | `مزاد أعيان حائل` → `ﻣﺰاد أﻋﻴﺎن ﺣﺎﺋﻞ`, correct joining and bidi; mixed `رقم الصك 542104012563` keeps the digits LTR inside the RTL line |
| Font embedding | brand font embedded as `Ruaq Arabic Medium`, `Identity-H` — live vector text, not outlines |
| Design preservation | baking every field region on the real lot page changed **0 pixels outside those regions** at 150 dpi, and cost 1 of 141 vector drawings (the redacted cell fill) |
| Colour | `#0E2A3A`, `#D6006F`, `#FFFFFF` all round-trip exactly |
| Ingest | `.ai` files open directly as PDF — no export step for the designer |
| Output size | 119.8 MB source → 12.2 MB background → **2.0 MB for a 28-page, 8-lot booklet** |
| Speed | 28 pages in ~6 s single-threaded |

## The two things that needed solving

**Placement.** `insert_htmlbox` does not honour the box origin. Measured errors on
the real artwork were −14.3 pt for a table value and −157.9 pt for a sentence — a
naive implementation looks visibly broken. `shaping.calibrated_htmlbox` renders
once to measure the glyph bbox, shifts the box by the observed delta, and renders
again. That lands on target to **±0.00 pt** for right, left and centre alignment,
for 90°/270° rotated labels, and — importantly — still lands after the text has
been auto-shrunk to fit. `test_guards.py` forbids calling `insert_htmlbox`
directly anywhere else.

**Knowing what to clear.** Baking must remove only what a field will draw over.
An early version redacted every derived text run and produced pages where values
floated beside empty cells, because the printed labels (`النوع`, `رقم الصك`, the
white chip captions) had been cleared too. Bake now takes explicit field regions,
and field boxes are trimmed so they never overlap neighbouring text.

## What this does not settle

The renderer sits behind `rendering/base.Renderer`. If a future template arrives
as loose assets rather than a finished design — where there is no artwork to
overlay — a second implementation can be added without touching the callers.
Nothing above argues that overlay is the right engine for *every* job; it argues
it is the right engine for filling a fixed, finished design, which is what this
product does.
