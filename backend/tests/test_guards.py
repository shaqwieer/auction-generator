"""Guards against the specific mistakes this codebase is prone to."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.rendering.fonts import REQUIRED_CODEPOINTS, FontError, brand_registry

RENDERING = Path(__file__).resolve().parent.parent / "app" / "rendering"
BANNED = {"arabic_reshaper", "bidi", "python_bidi"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("module", sorted(RENDERING.glob("*.py")), ids=lambda p: p.name)
def test_renderer_never_reshapes_arabic(module: Path):
    """RuaqArabic has no presentation-form cmap, so reshaping emits NUL glyphs.

    Shaping must come from OpenType GSUB via MuPDF. See docs/engine-decision.md.
    """
    offenders = _imports(module) & BANNED
    assert not offenders, (
        f"{module.name} imports {sorted(offenders)}; Arabic shaping must come "
        f"from the font's GSUB tables, not from presentation-form substitution"
    )


def test_no_direct_insert_htmlbox_outside_shaping():
    """One-pass insert_htmlbox mis-positions by up to 158pt on real artwork."""
    for module in RENDERING.glob("*.py"):
        if module.name == "shaping.py":
            continue
        source = module.read_text(encoding="utf-8")
        assert "insert_htmlbox" not in source, (
            f"{module.name} calls insert_htmlbox directly; use "
            f"shaping.calibrated_htmlbox so placement is calibrated"
        )


def test_every_brand_font_covers_arabic():
    registry = brand_registry()
    assert registry.faces, "no brand fonts shipped"
    for face in registry.faces:
        assert registry.validate(face) == [], f"{face.alias} fails validation"


def test_required_codepoints_are_all_assigned():
    """U+063B..U+063F are unassigned gaps; requiring them fails every good font."""
    assert not (set(REQUIRED_CODEPOINTS) & set(range(0x063B, 0x0640)))
    assert 0x0645 in REQUIRED_CODEPOINTS  # م
    assert 0x0632 in REQUIRED_CODEPOINTS  # ز


def test_missing_face_raises_rather_than_substituting():
    registry = brand_registry()
    with pytest.raises(FontError, match="font not embedded"):
        registry.face("Helvetica", "Bold")


def test_a_client_may_raster_only_a_template_they_could_use():
    """The cover chooser needs page images before a project exists.

    Widening that endpoint from staff-only is a permission change, so the
    predicate has to be the same one the catalogue listing already applies:
    published, and either shared or made for this client. A draft belongs to
    whoever is still working on it.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "catalog.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "template_page"
    )
    body = ast.unparse(handler)
    assert "user.is_staff" in body, "the handler must distinguish staff from clients"
    assert "TemplateStatus.PUBLISHED" in body, "a draft must stay staff-only"
    assert "user.client_id" in body, "another client's template must stay hidden"


@pytest.mark.parametrize("handler_name", ["publish", "unpublish"])
def test_moving_a_template_in_or_out_of_the_catalogue_is_admin_only(handler_name):
    """The permission matrix on /admin/settings promises this.

    Publishing bakes the artwork and is what puts a template in front of
    clients; an operator prepares one and an admin signs it off. Withdrawing it
    again is the same decision in reverse. The guard and the matrix drifted apart
    once already, and this test is the tie-breaker -- it also runs on a machine
    with no Postgres, where the API tests all skip.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "catalog.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    handler = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == handler_name
        ),
        None,
    )
    assert handler is not None, f"no {handler_name} handler in catalog.py"
    guards = {
        ast.unparse(argument.annotation)
        for argument in handler.args.args
        if argument.annotation is not None
    }
    assert "Admin" in guards, (
        f"{handler_name} depends on {sorted(guards)}; the permission matrix on "
        f"/admin/settings says only مدير النظام may publish a template"
    )
    assert "Staff" not in guards, (
        f"Staff on {handler_name} is what let an operator publish"
    )


# ------------------------------------------------------------------ storage


def test_one_variable_moves_everything_the_app_writes(monkeypatch, tmp_path):
    """VAR_ROOT is the whole storage configuration in production.

    The VPS bind-mounts a host directory at /app/var and sets nothing else. If
    either root stopped hanging off it, half the files would quietly land in
    the container's own filesystem and be gone at the next rebuild.
    """
    from app.core.config import Settings

    monkeypatch.setenv("VAR_ROOT", str(tmp_path / "srv"))
    settings = Settings()
    assert settings.storage_root == tmp_path / "srv" / "storage"
    assert settings.templates_root == tmp_path / "srv" / "templates"


def test_either_root_can_still_be_pinned_on_its_own(monkeypatch, tmp_path):
    from app.core.config import Settings

    monkeypatch.setenv("VAR_ROOT", str(tmp_path / "srv"))
    monkeypatch.setenv("TEMPLATES_ROOT", str(tmp_path / "elsewhere"))
    settings = Settings()
    assert settings.templates_root == tmp_path / "elsewhere"
    assert settings.storage_root == tmp_path / "srv" / "storage"


def test_development_writes_inside_the_repo(monkeypatch):
    """With nothing set, everything lands in backend/var.

    That is the same directory the dev server, the build script and the compose
    stack all use, so a template built on Windows is visible in the container
    without copying it anywhere.
    """
    from app.core.config import BACKEND_ROOT, Settings

    for name in ("VAR_ROOT", "STORAGE_ROOT", "TEMPLATES_ROOT"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.templates_root == BACKEND_ROOT / "var" / "templates"
    assert settings.storage_root == BACKEND_ROOT / "var" / "storage"


def test_the_api_image_does_not_bake_in_the_artwork():
    """var/ is mounted at run time, never copied into the image.

    Baking the templates in cost hundreds of megabytes and the mount hid them
    anyway, so the copy was pure weight -- and a stale one, since a rebuilt
    image would ship whatever artwork the build host happened to have.
    """
    from pathlib import Path

    ignore = Path(__file__).resolve().parent.parent / ".dockerignore"
    lines = {
        line.strip()
        for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert "var/" in lines, f".dockerignore must exclude var/: {sorted(lines)}"
