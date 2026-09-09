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
  booklet does not contain is worse than no code.
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
