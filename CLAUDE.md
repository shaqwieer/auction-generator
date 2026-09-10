# Project: مطبعة / Matbaa — print automation platform

## What this is
A FastAPI + Next.js platform that fills fixed print templates (booklets, forms,
banners, posters) with data from Excel or manual entry, and renders print-ready
PDFs. Content is Arabic (RTL) with some English. First real template is an
Infath/Aayan real-estate auction catalogue.

## Stack
- Backend: Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2
- Data: pandas, openpyxl · Images: Pillow · Codes: qrcode, python-barcode
- PDF engine: **PyMuPDF overlay** (see docs/engine-decision.md — this was decided
  on measured evidence, do not swap it casually)
- DB: PostgreSQL only — no SQLite fallback, in dev or in production
- Infra: Docker Compose

## Layout
backend/app/{api,core,models,schemas,services,rendering}
backend/{migrations,scripts,tests}
frontend/src/{app,components,lib,types}
docs/

Note: the Alembic directory is `migrations/`, not `alembic/` — a local
directory named `alembic` shadows the installed package.

## Commands
- Dev:            docker compose up
- Migrations:     cd backend && python -m alembic revision --autogenerate -m "..." && python -m alembic upgrade head
- Backend tests:  cd backend && python -m pytest
- Frontend dev:   cd frontend && npm run dev
- Typecheck:      cd frontend && npm run typecheck
- Lint:           ruff check backend && cd frontend && npm run lint
- Build templates: cd backend && python scripts/build_infath_templates.py
- Seed:           cd backend && python scripts/seed.py

## Rendering rules (these are correctness requirements, not style)
- **Never use arabic-reshaper or python-bidi.** The client's brand font
  (RuaqArabic, 301 glyphs) has no presentation-form cmap, so reshaping emits
  NUL glyphs. Shaping must come from OpenType GSUB via MuPDF's Story engine
  (`insert_htmlbox`). There is a lint test enforcing this.
- **Always place text through `calibrated_htmlbox()`.** A single-pass
  `insert_htmlbox` mis-positions by up to 158pt. The two-pass measure-and-shift
  lands on target to ±0.00pt.
- **`text-align` is logical to MuPDF's Story engine, so under `dir="rtl"` its
  two names come out swapped.** Measured: `right` laid every line of an Arabic
  paragraph against the box's *left* edge and `left` against its right. The
  engine reads the keyword as start/end, and start is the right edge in a
  right-to-left paragraph. `_RTL_ALIGN` swaps them, and only when `rtl` — the
  three Latin chips on تعريف وكيل البيع are `rtl=False` and there the keyword
  means what CSS says. A single line never showed it, because calibration pins
  a right-aligned field's rendered right edge onto its target; it is a
  paragraph that breaks, and نبذة عن وكيل البيع and نص الإعلان wrapped with
  their short last line hanging off the wrong side.
  `test_an_arabic_paragraph_starts_on_the_right` asserts the *rendered* line
  edges, not the CSS, so an upstream fix that stops needing the swap says so.
- **The designer's file is the template.** We overlay onto their artwork; we
  never re-implement a design in HTML or SVG.
- Baking a page redacts field spans with `images=PDF_REDACT_IMAGE_NONE` and
  `graphics=PDF_REDACT_LINE_ART_NONE`. Verified to leave 0 pixels changed
  outside the field rects.
- **Every value the client is asked for needs a name.** Where no label is
  printed to read — the برج page outlines its الحدود captions, both lot pages
  outline «الأطوال» — name it in `SWEEP_NAMES`, consumed in sweep order.
  An unnamed run reaches the form as «unnamed_6_3».
- **A page is named for what it is, not for its colour.** بيان العقارات and
  بيان عقود الإيجار each exist twice, once per identity colour; the colour is
  `layout`, and only the picker spells it out. Naming the variants listed the
  same page twice and read as a choice between two documents.
- `derive.py` takes **geometry** from sample spans, never the string. Illustrator
  bakes presentation forms and scrambles extraction order. The one exception is
  `autokey.py`, which NFKC-normalises a printed label solely to look it up in a
  fixed vocabulary; an unrecognised label is left unnamed rather than guessed.
- **A drawn box is the field, not the words the designer put in it.** The
  معلومات إضافية box on the lot page, its continuation page and مميزات العقار
  are each one box the client fills with sections — «مميزات العقار:» over its
  points, «الملاحظات:» over its own. Taking only the sample paragraph left the
  heading and the «-1» «-2» markers baked in, and every property opened with
  someone else's writing in it. «ملاحظات» is content; the teal chip above the
  box is design.
- **A section title is a short line ending in a colon**, and it prints in the
  brand's Bold face — named explicitly, because `<b>` does nothing when every
  weight is registered as its own CSS family. Newlines become `<br>`: to an
  HTML engine a newline is whitespace, and the box came out one paragraph.
- Baking clears **only the regions a field will draw over**. Clearing every
  derived run also deletes the printed labels and the page comes out with values
  floating beside empty cells.
- A table is one field per block (`FieldType.TABLE` + `TableSpec`), not one field
  per printed cell. Row numbering continues across blocks **only where the
  blocks are one table drawn in halves**, as on the lease table. It does not on
  «بيان العقارات»: the guide's blank specimen numbers the teal block 01–08 and
  the navy block 01–08, both restarting, and its instruction for a long list is
  «فيتم تكرار الصفحة» — repeat the page. Those two blocks are colourways, built
  as two pages sharing `slot="lot_table"`, ten rows each.
- **A table is as tall as the auction is long.** This holds for both tables —
  «بيان العقارات» and «بيان عقود الإيجار» — and for both colourways of each,
  every one of the four read off its own page rather than copied from another:
  the lease block is ten columns to the summary's nine and nineteen rows to its
  ten, and its teal page is made by rewriting the colour its content stream
  asks for, so the geometry is shared and the ink is not. The artwork ships
  them ruled full because a printed page has to be drawn for some number; ten
  rows for four properties left six ruled empties and the numbered tab running
  past all of them. The build lifts the block's line art off the
  page -- the rules, the column dividers and the tab -- stores it on the field
  as `TableFrame`, and the renderer draws back as many rows as there are. Not a
  white patch over the surplus: the page is coloured, so a patch is a patch.
  Shortening is a *translation* of the designer's own points, never a rebuild --
  every point below a shape's own middle moves up by the distance between the
  rule the block was drawn to and the rule it now ends on -- because the tab is
  a notched shape with bezier corners and redrawing it as a rectangle is a
  different design. The rules are stored **as measured**, not as a pitch: the
  steps are 26.02pt apart except for two of 28.56, and a block rebuilt from an
  average rules the wrong places. `frame` keeps the PDF's own float ink rather
  than `#RRGGBB` — the tab's teal is 0.749 green, 190.995 of 255, and the byte
  that survives the round trip prints a step light. A full summary block must come out
  pixel-identical to the artwork it replaced; that is the check that makes every
  shorter one trustworthy, and `test_a_full_table_is_the_ruling_the_designer_drew`
  is where it lives.
- **A block's bottom edge is not always its last row.** The dividers and the tab
  run to `TableFrame.bottom`, and shortening measures from there. On «بيان
  العقارات» that is the last row's own rule, so a full block is its artwork
  exactly. On «بيان عقود الإيجار» the designer ruled *twenty* bands, numbered
  nineteen, and drew the tab to the twentieth — so the bottom edge sits a whole
  band below the last row a client can fill. That band is captured, erased and
  never redrawn: it is an empty row, which is the thing this is all for. A full
  lease table is therefore its artwork one band shorter, and every shorter one
  ends under its last lease. A rule falling in no row's band is the bottom edge;
  two of them means the block was misread and the build refuses rather than
  guessing, as it does when a rule misses the band of the row it would close.
- **The lease table reaches `_uniform_table`, not the derived path**, because
  its column headers are outlined and `derive_tables` never sees it. That
  changes how the block is *found* — from its printed row numbers — not what it
  is, so it gets its frame the same way, through `_lift_frame`.
- **Removing a stroke needs its region measured by hand.** `_erase_frame` takes
  the frame off the artwork with one redaction over the union of its shapes, and
  the union cannot be built with `|=`: a rule is a stroke, its rect is
  degenerate, and `Rect.__or__` ignores an empty rect. Unioned, the region came
  out as the tab alone — the tab was lifted and all seventeen rules stayed, so
  the redraw landed on top of the original and every line printed a third too
  dark. The build now checks that erasing took exactly the shapes it captured
  and nothing else, which is what makes the removal safe to keep.
- **Every page a template keeps needs a rule set.** Baking clears only what a
  field will draw over, so a page that is kept but not described keeps the
  designer's sample data printed into the background. `scripts/pagemaps/` says
  what each page is; `test_build_map.py` is the regression net.
- **A caption can be part design and part data.** خطوات المشاركة is the guide's
  own sentence with three of this booklet's words in it, so the fixed wording
  rides on the field (`prefix`/`suffix`) and the client is asked only for the
  words that change — «اسم المنصة», «اسم المزاد», «قابلة للإسترداد». Asking for
  the whole caption invited them to mistype the design; asking for nothing left
  the page blank, because baking clears whatever a field will draw over. The
  caption is drawn as **one box**, which is how it still wraps and centres the
  way the designer drew it: carving out only the middle strands the fixed halves
  when the value changes length. `default_value` is what prints untyped, and
  `{key}` in it takes one of the booklet's own facts (`compose.booklet_facts` →
  `overlay.DEFAULTS_KEY`) — the auction and the platform are named on the
  auction-info page, and naming them again here would be asking twice for one
  fact. Resolved at draw time, never copied, so a title corrected on the cover
  corrects this page too.
- **A fact the booklet says twice is asked for once.** Every field that names
  one of `compose.BOOKLET_KEYS` — the auction, the platform, the date, the
  time, the venue — carries `default_value: "{its own key}"`, so it falls back
  to wherever in the booklet that fact was actually typed. معلومات المزاد and
  معلومات التواصل print the same four facts, and asking on both was asking
  twice and letting the answers disagree. Nothing is hidden: the field still
  stands on every page that prints it and shows the inherited value as its
  placeholder, so one page can still say something different if the design
  wants it. `auction_date_block` keeps its own key and inherits `{auction_date}`
  — the key stays separate because a project-level `auction_date` must not
  print itself onto the cover.
- **The brackets in «إختيار مزاد (إسم المزاد)» are the guide marking a place to
  be filled**, exactly as «شعار وكيل البيع» marks one — not punctuation. The
  export fills its own sample in between them, so printing them left every
  booklet reading «إختيار مزاد ( أعيان حائل )». Step 3 keeps its brackets:
  «(قابلة للإسترداد)» is a parenthetical the guide actually writes.
- **A caption does not say one word twice across its join.** The fixed wording
  and the value are one sentence, and «إختيار مزاد » in front of «مزاد أعيان
  حائل» printed the word twice. The designer's sample avoided it by writing the
  bare name; a fallback cannot, because the name it falls back to is the whole
  title. `overlay._joined` folds a repeat of the prefix's last whole word, and
  only across the join.
- **A mark beside a value belongs to that value** (`FieldSpec.ornament`).
  معلومات التواصل draws a handset for رقم التواصل and the WhatsApp bubble for
  واتساب; only the numbers were fields, so a seller with no WhatsApp printed a
  WhatsApp mark standing over nothing. Each mark is lifted at build time
  (`_lift_marks`), erased from the bake, and redrawn only when its value draws
  — the same act as `_erase_frame`, verified the same way: the redaction must
  take exactly the shapes captured. `row_group` names the centred row they sit
  in, and whatever is left of a row re-centres on the extent the designer gave
  it, so a full row moves not at all. That last part is the check that makes
  this safe on every booklet: `test_a_full_row_is_the_page_the_designer_drew`.
- **The two contact chips are واتساب on the right and رقم التواصل on the left.**
  Each icon sits to the *right* of its own number, so the handset at x=268
  belongs to the number ending at 254 and the WhatsApp bubble at 422 to the one
  ending at 309. Listed the other way round the splitter labelled each chip
  with its neighbour's name, the way «اسم المنصة» once was.
- **A mark's box is the one thing on a page a client may resize**
  (`overlay.SIZE_PREFIX`, «width×height» as percentages, keyed by page *and*
  field). The designer draws the agent's lockup at eighteen sizes through the
  booklet, sized to a sample mark, and a real one is rarely that shape. Only the
  box moves: `preserve_aspect` keeps the mark's own proportions inside it, so
  this cannot stretch a logo — which is why it is offered for a mark and not for
  a photograph, whose frame the designer drew and whose job is to fill it. The
  page is in the key because a property's values live on its record and every
  page of that property reads them.
- **A caption nobody edits is not a field.** «إستعراض المزادات» and «الفوز
  بالمزاد» are true of every auction, so they carry no field, are never cleared,
  and are the designer's own pixels — measured against the export they diff to
  zero. Making them fields would have them redrawn on every booklet for nothing.
- A derived box is the **ink** of the designer's line, and a line needs its side
  bearings too: +3pt horizontally, and the engine lays a line out from its
  ascender rather than its ink, so it also sits 1.44pt low. Both were measured
  against the export — the two untouched captions diff to zero, so any offset in
  the others is ours — and both are corrected on the rule (`pad_x`, `nudge_y`).
  Without them a line the designer set as one wraps into two.
- Spaces inside a bracket are places a line may break. «إختيار مزاد ( … )» put
  its closing bracket on a line of its own as soon as the auction's name was
  longer than the sample, so the brackets are bound with U+00A0; the name still
  breaks between its own words, which is where a break belongs.
- **A lot page is drawn twice, and which one prints is a fact about the
  output.** «تفاصيل العقار (نسخة الطباعة)» puts a code under each of the four
  link chips and stands them in a 2x2 block; «(نسخة إلكترونية)» has no codes —
  a chip on a screen is clicked — and stands them in a single column. Guide
  pages 14, 18 and 19; both drawings are in the exports, and an earlier reading
  pruned the screen ones as «duplicate samples». They are not duplicates.
  `SourceMap.flavours` declares them, they are appended to the built document
  **last** so no index a booklet already points at moves, they never appear in
  the builder, and `templates.pages_for_output` swaps them in at render time
  beside `for_output`. `_qr_slots` cannot find their chips — there are no codes
  — so `_column_link_fields` finds the bars instead, and the order they are
  stacked in (survey, photos, lease, map — *not* the block's order) is checked
  against the live captions where the export sets them as text and against the
  rank of the drawn caption widths where it outlines them.
- **A twin is only usable if it asks for exactly what the page it replaces
  asks for**, and the build refuses one that does not. The برج drawings pass.
  The قياسي one does not: it is a later revision whose «الأطوال» block is four
  labelled rows where the printed page has two combined runs, so «شرقاً» and
  «غرباً» are read twice and the vocabulary pairs المساحة and الاستخدام with
  the الحدود column beside them. Swapping it would print the area where the
  north boundary goes, so the printed drawing is used for both outputs and the
  build says so. Fixing it needs the four length rows keyed to match
  `lengths_1`/`lengths_2` — a question about how many fields الأطوال should ask
  for, on both drawings, not about the artwork — or a corrected export. Note
  while doing it that the قياسي screen drawing stands **three** chips, not
  four: the designer left معلومات الإيجار off it, where the برج screen drawing
  keeps all four. So a قياسي property in a screen booklet would lose that chip
  even once the twin is usable, and that is the designer's decision, not ours.
- **A chip that is not always printed is cut off the artwork**
  (`FieldSpec.part`). «معلومات الإيجار» leads to a page the guide only uses «في
  حال وجود عقود إيجارية للأصل», and a chip is a bar, a caption reversed out of
  it and an arrow — a raster, some type and a piece of line art, none of which
  an `ornament` can hold. So the region is cut onto a page of its own inside
  the background PDF and placed back with `show_pdf_page`, which reproduces all
  three exactly: measured at **0 differing bytes**. The bar is an *inlined*
  raster, so no `PDF_REDACT_IMAGE_*` mode removes it — what takes it off is the
  redaction's own fill, and a fill is a patch unless it is the colour that was
  already there, so `_chip_ground` samples the ring and the build refuses a
  chip whose ground it cannot name. Cutting happens **after** the bake, or the
  cutting drags the sample photograph with it and comes to 22MB.
- **`for_output` drops a link only where the chip has two halves.**
  «معلومات الإيجار» leads inside the booklet and is minted no code, so on paper
  it is a LINK and nothing else — dropped, nothing would know the chip existed
  and a printed booklet would carry the gap the build cut.
- **A printed label is design however it is coloured.** The colour-and-size pool
  `_span_columns` builds now skips `STATIC_HEADINGS` before it looks at size.
  The chip captions are white on teal, which is what a value looks like on a lot
  page, and on the screen drawing they are set at 9.8pt — inside the band the
  closing chip's own parts are matched by. Claimed, they were named «تاريخ إغلاق
  المزايدة», cleared by the bake, and the page came out with two blank bars.
- **`SourcePage.remove` is a region this variant's auction does not have.**
  معلومات التواصل is one drawing serving all three; an electronic auction is
  held nowhere, so its الموقع chip and its «قاعة المزاد» code come off the page
  before anything is derived. Nothing draws over them, so the bake would not
  clear them — the page would print a location pin over nothing and a code to a
  hall that does not exist.
- **Rebuilding a template writes the manifest; only `seed.py` puts it in the
  database.** A build without a reseed leaves the API serving the previous
  geometry, and the page renders subtly wrong — a caption wrapping where the
  corrected box would not.
- Some copy in the exports is converted to outlines. Redaction preserves line
  art, so it cannot be cleared — removing it takes the design with it. Flag the
  page (`needs_artwork`) and ask for a corrected export; do not widen the bake.
- Field geometry is stored in normalised coordinates. Never hardcode pixel sizes.
  `x` is the distance from the **left** edge, so it is placed with a physical
  `left`. `insetInlineStart` resolves to `right` under `dir="rtl"` and mirrors
  every box on the page.
- A cover is one of the six the brand guide draws. There is no seventh, no
  upload, and the export's own cover page (flagged `source_cover`) holds the
  slot without being offered.
- **No company's branding is baked into the artwork.** The build finds the
  selling agent's lockup by shape — the silhouette that *recurs* across the
  booklet, which no heading does — removes it (the one place line art is
  removed), and puts `company_logo` + `company_name` in its place. The values
  come from the signed-in account at compose time (`page_plan.branding`), never
  from the project, so a logo uploaded now shows on a booklet started this
  morning. There is no fallback: no logo prints the name, neither prints
  nothing.
- A full-bleed image field is the page's **backdrop**: the renderer inserts it
  under the artwork, because the designer draws the logos, scrim and title on
  top of the photograph. A logo field sets `preserve_aspect` — a photograph is
  cropped to its frame, a logo must never be.
- Shapes the designer draws **over** a photograph — the number's badge, the
  closing-time chip — are `clip_holes` on the image field. A photograph is
  placed on top of the baked artwork and would otherwise cover them.
- **A photo frame is not a rectangle.** Its drawn outline is stored on the field
  as `clip`, in 0..1 of the field's own box, and the renderer masks the
  photograph to it — JPEG plus a one-channel stencil, never RGBA, because phone
  photography as PNG is megabytes a page. A path can hold more than one shape
  (the قياسي frame also traces the sample property); split on the jump and keep
  the largest piece. `Rect.__or__` ignores an empty rect, so measure a polygon's
  extent by hand, not by unioning point-rects.
- Strip sample photos when baking backgrounds — an untreated page slice is 22 MB.

## Architecture rules
- The renderer, storage and job runner stay behind their interfaces in
  services/ and rendering/base.py. Call the interface, not the implementation.
- Generation errors always carry row index + field key + human-readable cause.
- No blocking work in request handlers. Long work goes to a job.
- Add a migration for every model change. Never edit a migration that has run.
- Type hints on all Python; strict TypeScript, no `any`.
- Build for extension, don't build the extension. Ask before adding a dependency.

## Database rules
- **Postgres everywhere.** JSON columns are `JSONB` and timestamps are
  `timestamptz`, so values come back timezone-aware; do not add naive-datetime
  shims. `DATABASE_URL` defaults to the compose database on port 55432.
- The API tests create and drop `matbaa_test` on the same server, and skip when
  it is unreachable. Start it with `docker compose up -d db`.

## Tooling traps
- `ruff --unsafe-fixes` is dangerous here. RUF005 reads `rect + (dx, dy, dx, dy)`
  — a fitz.Rect *translation* — as list concatenation and rewrites it to a
  tuple, silently changing geometry. The rule is disabled in pyproject.toml;
  keep it that way, and run the tests after any autofix pass.
- **No quotes around a compose `${VAR:-default}` default.** Compose is not a
  shell: it passes them through, so `CORS_ORIGINS` reached the container as
  `'["..."]'` and pydantic-settings aborted the boot with «error parsing value
  for field "cors_origins"» — the API restart-loops and nothing says why. The
  setting now parses JSON, quoted JSON and a plain comma-separated list, and
  owns its own decoding (`NoDecode`) because the built-in reader JSON-decodes
  before any validator runs.
- The Alembic directory is `migrations/`. A directory named `alembic/` shadows
  the installed package and every alembic command fails to import.

## The template editor
- **A save changes what it was asked to change, and nothing else.** The field
  set the editor sends is the field set the template ends up with, but a
  *column* it omits keeps whatever it had. Saving used to delete every row and
  rebuild from the payload, which made the editor responsible for round-tripping
  every column in the table — and it was not: `preserve_aspect`, `clip` and
  `clip_holes` have no control on that screen, so each save silently reset them
  and every photo frame in the booklet went back to being a rectangle, with the
  screen still showing exactly what the operator expected. `exclude_unset` is
  what makes the guarantee hold for a column added later, rather than until
  somebody forgets. Sending an explicit `null` still clears a value, so this is
  not «never change».
- **A field is the row, not its name.** A saved field is matched to its stored
  row by `id` first — renaming keys is most of what the editor is for — and by
  (page, key) second, which covers a client too old to send an id and an id a
  rebuild has replaced. Row ids are stable across a save now; they used to
  change on every one.

## API rules
- **The web client never sends PATCH.** It has twice been refused in the
  browser — «Method PATCH is not allowed by Access-Control-Allow-Methods» —
  against a server that answers the same preflight correctly to curl, so the
  cause is suspected to be a cached preflight rather than the live config.
  Mutating routes are `api_route(methods=["PATCH", "POST"])`; the client
  sends POST.
- Arabic filenames cannot go straight into a `Content-Disposition` header —
  use `app.api.http.content_disposition` (RFC 5987).
- Errors are Arabic and user-facing. Renderer causes live in
  `app/rendering/messages.py`; API errors are raised inline.

## UI rules
- **A preview reads only the photographs the page it is drawing needs.** The
  builder redraws a page per keystroke, and `assets_for_project` used to load
  every frame in the booklet before the preview cache was even consulted — a
  twenty-property issue is several hundred megabytes to draw one page.
  `generation.LazyAssets` knows the names (which is all the cache key and
  preflight need) and reads the bytes on demand. The renderer also takes an
  `image_dpi`: the builder's page is rastered at about 110dpi, so resampling a
  4032×2268 frame to 300 for it is thrown away a moment later. What the
  resolution is *judged* against does not move with it — `effective_dpi` and
  `below_min_dpi` stay measured against print, or every preview would claim the
  photograph is too coarse.
- The builder holds the shown page by **position** in the node, not by page
  index. Recolouring a table swaps the page underneath the same node, and
  resetting sent the designer back to the property's first page each time.
- A booklet is assembled in the builder (`/projects/[id]/build`), page by page.
  It fills the designer's layout in — it never moves or resizes a field, and
  never restyles one. `PageCanvas` deliberately has no drag.
- **Only one of the page and the box ever paints a value.** At rest the page
  does and the box is empty and invisible; a focused box asks for the page with
  that field omitted (`preview.png?omit=<key>`) and paints into the hole. Never
  draw the value in both — it prints twice, in two fonts, a few points apart.
- A page at rest carries no field outlines. The fields are listed in الحقول
  beside it, and hover reveals the one under the pointer.
- **Pages are switched off, not deleted.** A node keeps its place, its layout
  and everything typed on it, and prints nothing (`off: true`). A switched-off
  property leaves the summary table as well as the booklet — filter it in
  `ordered_rows` and in the page loop, or it is listed with no page to point at.
- **A keystroke is never dropped on the way to the server.** Values are held
  per key in a pending map until the save that carried them is acknowledged,
  and adopted server values are laid *under* whatever is still pending. A single
  dirty flag cannot express this: it has to be cleared when a save is sent, and
  the answer to that save — built from the values it carried — was then adopted
  over everything typed since. That was «اكتب كلمة تختفي»: measured, the box
  showed «سكني» and settled back to «سك», and «سك» is what reached the database.
  Every revision-bumping call also goes through one queue, values and lease rows
  together, because two of our own saves in flight at once carry the same
  revision and the server rightly refuses the second — which reloaded the
  builder mid-sentence. Leaving a page sends what it still holds rather than
  clearing it.
- A booklet starts with **no** properties and grows. Nothing asks for a count up
  front; a property added from anywhere lands where properties belong
  (`_lot_anchor`), not after whatever page happened to be open.
- The side panel is **tabbed, not stacked**. A property page offers a layout,
  five optional pages, the photographs, the section boxes and twenty-odd
  fields; down one column that is several screenfuls, and reaching الحقول meant
  scrolling past all of it. The tabs a node offers depend on what it is, so the
  open tab is held by name and falls back to the first when the new page does
  not offer it — الحقول leads and is the default, because the page and the list
  beside it are a pair.
- RTL by default. Light theme only. Right-hand sidebar.
- IBM Plex Sans Arabic for everything; IBM Plex Mono ONLY for technical values
  (filenames, page counters, row numbers, durations). Latin numerals always,
  wrapped in dir="ltr" + unicode-bidi:isolate.
- Hairline 1px borders (#E6E8EA), not shadows. Magenta #D6006F is for action only.
- Arrows and progress bars flow leftward.

## Printed links
- A code printed on paper cannot be edited, so it **never carries a
  destination**. It carries `{PUBLIC_BASE_URL}/r/{code}`, and a `ShortLink` row
  says where that leads today — move the file, change the row, the paper keeps
  working. Codes are minted once per (project, property, slot) and reused, so a
  regenerate reprints the codes already in circulation.
- Each link chip is **two fields**: `link_*` / `platform_link` / `venue_link`
  (LINK, the address a client gives) and `__qr_*` (QR, the minted address).
  `templates.for_output` drops one — paper keeps the code, screen keeps the
  click. The preview cache key includes the flavour, or switching serves the
  other one's raster.
- On screen the lease chip **jumps to that property's بيان عقود الإيجار** rather
  than out to the web; on paper the same chip's code still carries the permanent
  address, because a printed code cannot jump. Only the composer knows the
  destination — it is an output page number — and jumps are held to the end of
  the render, because MuPDF refuses a link to a page not yet made.
- The lease chip is drawn **only where the lease page is on**: «يتم استخدام
  الصفحة في حال وجود عقود إيجارية للأصل», and a code leading to a page the
  booklet does not contain is worse than no code. Since the chip is cut off the
  artwork rather than merely unfilled, that rule now holds on **both**
  composers, and on the older one it holds absolutely: a project with no page
  plan is composed from the template's sections, no section holds بيان عقود
  الإيجار, and so those booklets print no lease chip on any property at all.
  A change from when the chip was baked in and printed regardless of what the
  booklet contained, and pinned by a test rather than left to be rediscovered.
- A code prints in the colour the page uses (`spec.color`) on a transparent
  ground — the booklet's are teal and navy, and a white tile would be a patch.
- The LINK field's rect is the **whole chip**, code and caption together, so a
  screen reader has something visible to click. The caption bars are in no
  drawing list, so `_caption_near` reads them off the rendered page: outward to
  the first ink, then across it, bounded by `approach` and stopping at the next
  code. Ten codes per booklet: four per property page, one on الخطوات, one on
  التواصل.
- Set `PUBLIC_BASE_URL` before the first real print run. It is a deployment
  setting and never the request's host: the address on the paper has to keep
  working when the API is reached some other way.

## The lease table
- **A table too long for its page repeats the page.** «فيتم تكرار الصفحة» is
  the guide's answer for properties and it is the answer for contracts too. Each
  table paginates at *its own artwork's* capacity — ten for «بيان العقارات»,
  nineteen for «بيان عقود الإيجار» — and neither number is a guide to the other.
  The repeat carries the same full header and table artwork, `__row_offset__`
  carries the numbering across it (row 20 reads «20», not «01»), and the last
  page is ruled only for the rows it actually holds. `compose` needs the
  capacity to work this out and only the template knows it, so
  `page_plan.lease_rows_per_page` passes it in as a page→rows mapping; the same
  mapping feeds `page_count_plan`, or the review step promises a page count the
  booklet does not print. A lease page with nothing typed on it is still drawn
  once — switching it on is how the operator gets somewhere to type.
- **The builder previews the first of a repeat, not all of them.** A node's page
  switcher is built from `node.pages`, which holds template page indices, and a
  repeat is the same index twice. This is true of the summary table as well and
  always has been; the repeats are in the generated booklet.
- **بيان عقود الإيجار is typed, not derived.** بيان العقارات builds itself from
  the booklet's properties; nothing in the system knows what leases an asset
  carries, so the rows live on the lot node (`values["__lease__"]`) in the order
  they print. Its nine columns are declared in `LEASE_COLUMNS` because the
  printed headers are outlined — there is no text to read them from.
- The page is drawn in navy only. The other colour is offered by **rewriting the
  colour the content stream asks for** (`0 .212 .365` → teal), never by erasing
  the bar and drawing a new one: the headers are outlined art sitting *over* it
  and a substitution leaves them where they are. One choice per booklet
  (`Project.lease_colourway`), and changing it re-resolves every lot's pages,
  because the pages a property occupies are frozen on its node.
- A page copied before the bake needs its cells added to the bake's regions, or
  it prints the designer's sample rows under whatever the client typed.
- `optional_pages` returns one page per role: a page drawn in two colours is
  still one page of the booklet.

## Terminology
`Project` = one generation run (a booklet issue). The client's Arabic "مشروع"
means a *lot/property* — that is a `DataRecord`. Never conflate them.

## Not in scope yet
Social platform integrations and the freelancer module are phase two. The
`isSoon` screen announces them. Leave room in the data model; write no logic.
