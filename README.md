# مطبعة / Matbaa

Fills fixed Arabic print templates from Excel or manual entry and renders
print-ready PDFs. Built around a real client template: the Infath/Aayan auction
catalogue (`كتيب حضوري` and `كتيب الهجين`).

The design is never re-implemented. The designer's own `.ai` export *is* the
template — variable regions are cleared from it once, and data is composited back
onto the original artwork. See [`docs/engine-decision.md`](docs/engine-decision.md)
for the measurements behind that choice.

---

## Quick start

### Docker (the target)

```bash
cp .env.example .env        # set SECRET_KEY before anything but local dev
docker compose up --build
docker compose exec api python scripts/seed.py
```

- API — http://localhost:8000 (docs at `/docs`)
- Web — http://localhost:3000

Migrations run on API start; `seed.py` loads categories, accounts and the built
templates. Every published host port is overridable, because a machine that
already runs Postgres or a dev server on 3000 would otherwise fail to start:

```bash
DB_PORT=55432 API_PORT=8000 WEB_PORT=3100 docker compose up -d
```

Verified: both images build, the three containers come up healthy, and a
four-lot booklet generates and downloads as a 20-page PDF through the
containerised API.

### Running the API on the host

**Postgres is the only supported database, in development and in production.**
There is no SQLite fallback. Start the database from compose, then run the API
against it:

```bash
docker compose up -d db                 # publishes 55432 by default

cd backend
pip install -r requirements-dev.txt
python -m alembic upgrade head
python scripts/build_infath_templates.py            # once per design revision
python scripts/seed.py
python -m uvicorn app.main:app --reload

cd ../frontend
npm install
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev
```

`DATABASE_URL` defaults to `postgresql+psycopg://matbaa:matbaa@localhost:55432/matbaa`,
which matches the compose default. Point it anywhere else with the env var.

Seeded accounts (password `matbaa1234`):

| Email | Role |
|---|---|
| `khalid@matbaa.sa` | admin |
| `sara@matbaa.sa` | operator |
| `noura@fahd-group.sa` | client |

---

## How a booklet gets made

```
designer's .ai ──page map──▶ build ──▶ background.pdf + template.json
                                              │
  builder ──▶ page plan ──┐                   │
  Excel import ──────────▶ DataRecord ──▶ compose ──▶ overlay ──▶ PDF
```

1. **Ingest the design.** Upload the `.ai`/`.pdf` from `/admin/templates` (or run
   `scripts/build_infath_templates.py`, which builds the three auction booklets
   from a checked-in page map in `scripts/pagemaps/`). It reads Illustrator files
   directly,
   derives every text run's geometry, auto-names fields whose printed label
   matches a controlled vocabulary, and recovers the summary table's columns and
   row pitch. **Nothing is baked yet** — the original is kept intact and the
   artwork is only cleared at publish, once an admin has confirmed in the visual
   editor which regions are variable. Unclaimed regions stay as click-to-add
   suggestions rather than becoming fields.
2. **Ingest the data.** Excel or CSV in, one `DataRecord` per lot. Merged header
   cells, blank spacer rows, Arabic headers and numbers-stored-as-text are all
   handled.
3. **Map.** Spreadsheet columns are matched to template fields automatically;
   the operator adjusts, and validation blocks generation while a required field
   is unmapped.
4. **Compose.** Fixed sections + a paginating summary table + *N* × the
   two-page lot block.
5. **Render.** Values are composited onto the baked background and the job
   returns a PDF. Every problem carries its row, field and a readable cause.

---

## Layout

```
backend/
  app/rendering/     the PDF engine — see below
  app/services/      ingest, mapping, storage, jobs, generation, templates
  app/api/v1/        auth · catalog · projects · builder · jobs · assets · dashboard
  app/models/        SQLAlchemy tables
  migrations/        Alembic
  scripts/           build_infath_templates.py · pagemaps/ · generate_booklet.py · seed.py
  tests/             214 tests, run against the real artwork where present
frontend/src/
  app/               App Router pages (RTL, light only)
  components/        shell + design-system primitives
  lib/               typed API client
docs/                engine-decision.md
```

### The rendering module

| File | Responsibility |
|---|---|
| `shaping.py` | `calibrated_htmlbox` — the only sanctioned way to draw text |
| `fonts.py` | brand font registry, embedding validation |
| `derive.py` | propose field regions from a sample export (geometry only) |
| `autokey.py` | name a field by matching its printed label to a vocabulary |
| `tables.py` | recover a repeating table's columns, pitch and blocks |
| `bake.py` | clear the sample content, keep the design |
| `compose.py` | section plan + records → an ordered page list |
| `overlay.py` | the one `Renderer` implementation |

---

## Where the files live

Everything the application writes lives under **one directory**. The database
stores paths and storage keys, never file contents.

```
var/
  templates/<slug>/
    background.pdf    the baked artwork — sample data cleared, design intact
    source.pdf        the unbaked original, so publish and suggestions work
    template.json     page roles, sections, field rectangles
  storage/
    outputs/<project-id>/<hex>_<name>.pdf    finished booklets
    uploads/<project-id>/<hex>_<name>.xlsx   imported spreadsheets
    assets/<client-id>/<hex>_<name>.jpg      photographs, shared per client
```

`VAR_ROOT` moves all of it; `TEMPLATES_ROOT` and `STORAGE_ROOT` override one
half each. The random hex prefix is why two uploads of `photo.jpg` cannot
collide.

**Development — Windows, local.** Nothing to configure: it defaults to
`backend/var`, and compose bind-mounts that same directory. The dev server, the
build script and the container therefore all see one set of files, so a
template built on the host is live in the container immediately.

**Production — Linux VPS, compose only.** A bind mount to a host directory
outside the project, never a Docker named volume:

```bash
sudo mkdir -p /srv/matbaa/var/{templates,storage}
echo "MATBAA_VAR=/srv/matbaa/var" >> .env

docker compose up -d --build
docker compose exec api python scripts/build_infath_templates.py   # per design revision
docker compose exec api python scripts/seed.py                     # first deploy only
```

A bind mount is the point: the files outlive `docker compose down`, a rebuild
and a redeployment; `tar`, `rsync` and `restic` can reach them; and no
deployment step needs `docker compose cp`. Back up `/srv/matbaa/var` alongside
a `pg_dump` — restoring one without the other leaves rows pointing at files
that are not there.

### Migrating an existing deployment off the named volume

Deployments made before this used the `matbaa_api_var` named volume. Move them
once, with `scripts/migrate_storage.py`, which copies nothing it cannot verify
and overwrites nothing at all:

```bash
sudo mkdir -p /srv/matbaa/var
docker compose run --rm -v matbaa_api_var:/old:ro -v /srv/matbaa/var:/new   api python scripts/migrate_storage.py --from /old --to /new           # look
docker compose run --rm -v matbaa_api_var:/old:ro -v /srv/matbaa/var:/new   api python scripts/migrate_storage.py --from /old --to /new --apply   # move

echo "MATBAA_VAR=/srv/matbaa/var" >> .env
docker compose up -d
docker volume rm matbaa_api_var        # only once you have looked and backed up
```

Every file is read back and checksummed before it counts as copied, a file
already present with identical content is skipped, and one that differs is
reported as a conflict rather than overwritten — so a re-run is a no-op and a
partial copy is safe to resume. The old volume is never touched.

## Things that will bite you

These are load-bearing. Each is enforced by a test in `tests/test_guards.py`.

- **Never `arabic-reshaper` / `python-bidi`.** The client's brand font
  (RuaqArabic, 301 glyphs) has no presentation-form cmap, so reshaping emits NUL
  glyphs for ز, د and أ. Shaping comes from OpenType GSUB via MuPDF.
- **Never call `insert_htmlbox` directly.** One pass mis-positions by up to
  158pt. `calibrated_htmlbox` measures, shifts, and redraws — exact to ±0.00pt,
  including after auto-shrink.
- **Bake only what a field covers.** Clearing every derived run also deletes the
  printed labels (`النوع`, `رقم الصك`), and the page comes out with values
  floating beside empty cells.
- **`derive.py` takes geometry, not strings.** Illustrator bakes presentation
  forms and scrambles extraction order. The one exception is `autokey`, which
  NFKC-normalises a label purely to look it up in a fixed vocabulary.
- **Output is RGB with no bleed**, matching the client's approved files. The
  CMYK and bleed toggles exist in the UI, default off, and are not yet
  implemented as post-processing.
- **Postgres only.** JSON columns are `JSONB`, timestamps are `timestamptz`, and
  the code assumes both. There is no SQLite path to fall back to.

---

## Commands

```bash
docker compose up -d db                   # the API tests need it
cd backend && python -m pytest            # 114 tests
cd backend && python -m ruff check app scripts tests
cd frontend && npm run typecheck && npm run lint
cd backend && python -m alembic revision --autogenerate -m "..."
```

The 22 API tests create and drop a `matbaa_test` database on the same server and
**skip** with a clear message when Postgres is unreachable; the other 92 need no
database and run anywhere. Override the server with `TEST_DATABASE_URL`.

Regenerate a booklet from the command line:

```bash
cd backend
python scripts/generate_booklet.py auction_infath_inperson \
  var/demo/data/hail.json out.pdf --assets var/demo/assets
```

---

## Building a booklet

`/projects/new` picks a template and one of eight covers; `/projects/[id]/build`
is where the booklet is assembled page by page. Each property gets a layout
(قياسي or برج/عمارة) and whichever optional pages it needs, values are typed
straight onto a server-rendered page, and photographs are dropped onto the field
that will print them. Importing a spreadsheet is an action inside that screen —
it lays its rows out as pages — rather than a step before it.

The booklet lives on `Project.page_plan`; a project without one composes through
the template's section plan exactly as before, which is what the pre-builder
screens at `/projects/[id]/{data,mapping,manual}` still serve.

## Not built yet

- The إلكتروني booklet's معلومات المزاد and شروط الدخول pages carry the هجين
  artwork until `كتيب-إلكتروني.ai` arrives; both are flagged in the manifest
- مميزات العقار has its lease copy converted to outlines in the export, so it
  cannot be cleared and the builder does not offer it
- CMYK conversion and bleed/crop marks (toggles exist, no pipeline behind them)
- Writing production settings back from the admin settings screen (read-only)
- Social integrations and the freelancer marketplace — phase two, announced on
  `/admin/soon`, no logic behind it

## Local development notes

- `uvicorn --reload` misses changes on this Windows setup often enough to be
  misleading. If a new endpoint 404s, restart the API rather than debugging it.
- Never run `next build` while `next dev` is running: the production build
  overwrites `.next` and the dev server then fails with `Cannot find module
  './NNN.js'`. Stop dev, delete `.next`, restart.
- Some browsers refuse to send `PATCH` cross-origin even after a successful
  preflight. The update endpoints accept `POST` as well, and the web client
  uses it.
- Development and production never share files. Windows writes into the repo's
  `backend/var`; the VPS writes into `/srv/matbaa/var`. The storage *shape* is
  identical, which is what makes a template directory copyable between them —
  but nothing is mounted across.
