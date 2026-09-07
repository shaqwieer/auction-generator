"""Categories, clients and templates."""

from __future__ import annotations

import uuid
import uuid as _uuid

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import DB, Admin, CurrentUser, Staff
from app.core.config import get_settings
from app.core.security import hash_password
from app.models import (
    Category,
    Client,
    Project,
    Role,
    Template,
    TemplateField,
    TemplateSection,
    TemplateStatus,
    User,
)
from app.schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ClientCreate,
    ClientOut,
    ClientUpdate,
    ClientUserCreate,
    PasswordReset,
    TemplateDetail,
    TemplateFieldUpdate,
    TemplateIngestOut,
    TemplateOut,
    TemplateSectionUpdate,
    UserOut,
)
from app.services import template_build
from app.services import templates as template_service
from app.services.template_build import BuildError

settings = get_settings()

router = APIRouter(tags=["catalog"])


# ------------------------------------------------------------- categories


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: DB, _: CurrentUser) -> list[CategoryOut]:
    counts = dict(
        db.execute(
            select(Template.category_id, func.count(Template.id)).group_by(
                Template.category_id
            )
        ).all()
    )
    rows = db.scalars(select(Category).order_by(Category.position, Category.name)).all()
    return [
        CategoryOut(
            **{
                k: getattr(row, k)
                for k in ("id", "name", "slug", "description")
            },
            template_count=counts.get(row.id, 0),
        )
        for row in rows
    ]


@router.post(
    "/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED
)
def create_category(payload: CategoryCreate, db: DB, _: Staff) -> CategoryOut:
    if db.scalar(select(Category).where(Category.slug == payload.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "المعرّف مستخدم بالفعل.")
    category = Category(**payload.model_dump())
    db.add(category)
    db.flush()
    return CategoryOut.model_validate(category)


@router.api_route(
    "/categories/{category_id}", methods=["PATCH", "POST"], response_model=CategoryOut
)
def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, db: DB, _: Staff
) -> CategoryOut:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التصنيف غير موجود.")
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, name, value)
    db.flush()
    return CategoryOut.model_validate(category)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: uuid.UUID, db: DB, _: Admin) -> None:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التصنيف غير موجود.")
    used = db.scalar(
        select(func.count()).select_from(Template).where(
            Template.category_id == category.id
        )
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"التصنيف مستخدم في {used} قالبًا — انقلها أولًا.",
        )
    db.delete(category)


# ---------------------------------------------------------------- clients


@router.get("/clients", response_model=list[ClientOut])
def list_clients(db: DB, _: Staff) -> list[ClientOut]:
    projects = dict(
        db.execute(
            select(Project.client_id, func.count(Project.id)).group_by(
                Project.client_id
            )
        ).all()
    )
    users = dict(
        db.execute(
            select(User.client_id, func.count(User.id))
            .where(User.client_id.is_not(None))
            .group_by(User.client_id)
        ).all()
    )
    rows = db.scalars(select(Client).order_by(Client.name)).all()
    return [
        ClientOut.model_validate(row).model_copy(
            update={
                "project_count": projects.get(row.id, 0),
                "user_count": users.get(row.id, 0),
            }
        )
        for row in rows
    ]


def _add_user(db, client: Client, payload: ClientUserCreate) -> User:
    """Create one sign-in attached to a client."""
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"البريد «{email}» مستخدم بالفعل لحساب آخر.",
        )
    user = User(
        email=email,
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        role=Role(payload.role),
        client_id=client.id,
    )
    db.add(user)
    db.flush()
    return user


@router.get("/clients/{client_id}/users", response_model=list[UserOut])
def list_client_users(client_id: uuid.UUID, db: DB, _: Staff) -> list[User]:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العميل غير موجود.")
    return list(
        db.scalars(
            select(User).where(User.client_id == client.id).order_by(User.created_at)
        ).all()
    )


@router.post(
    "/clients/{client_id}/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def create_client_user(
    client_id: uuid.UUID, payload: ClientUserCreate, db: DB, _: Admin
) -> User:
    """Add a sign-in so someone can actually use this client's account."""
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العميل غير موجود.")
    return _add_user(db, client, payload)


@router.post("/users/{user_id}/password", response_model=UserOut)
def reset_password(
    user_id: uuid.UUID, payload: PasswordReset, db: DB, _: Admin
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود.")
    user.password_hash = hash_password(payload.password)
    db.flush()
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, db: DB, admin: Admin) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود.")
    if user.id == admin.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "لا يمكنك حذف حسابك الحالي."
        )
    db.delete(user)


@router.post("/clients", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, db: DB, _: Admin) -> ClientOut:
    """Create a client, and optionally its first sign-in in the same transaction.

    Doing both together matters: a client with no user is one nobody can log in
    to, and creating them as two calls leaves that state behind whenever the
    second one fails.
    """
    if db.scalar(select(Client).where(Client.code == payload.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "رمز العميل مستخدم بالفعل.")

    fields = payload.model_dump(exclude={"user"})
    client = Client(**fields)
    db.add(client)
    db.flush()

    users = 0
    if payload.user is not None:
        _add_user(db, client, payload.user)
        users = 1

    return ClientOut.model_validate(client).model_copy(
        update={"project_count": 0, "user_count": users}
    )


@router.api_route(
    "/clients/{client_id}", methods=["PATCH", "POST"], response_model=ClientOut
)
def update_client(
    client_id: uuid.UUID, payload: ClientUpdate, db: DB, _: Staff
) -> ClientOut:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العميل غير موجود.")
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, name, value)
    db.flush()
    return ClientOut.model_validate(client)


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: uuid.UUID, db: DB, _: Admin) -> None:
    """Deactivate rather than delete once a client owns work.

    Removing a client would cascade away every project and generated booklet,
    which is never what "remove from the list" means.
    """
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العميل غير موجود.")
    projects = db.scalar(
        select(func.count()).select_from(Project).where(Project.client_id == client.id)
    )
    if projects:
        client.is_active = False
        db.flush()
        return

    # Its sign-ins go with it. User.client_id is SET NULL on delete, which is
    # right for staff but would leave a client-role account attached to nothing —
    # able to log in and then refused at every screen.
    for user in db.scalars(
        select(User).where(User.client_id == client.id, User.role == Role.CLIENT)
    ).all():
        db.delete(user)
    db.flush()
    db.delete(client)


# -------------------------------------------------------------- templates


def _template_out(row: Template, field_count: int = 0) -> TemplateOut:
    return TemplateOut.model_validate(row).model_copy(
        update={"field_count": field_count}
    )


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(
    db: DB,
    user: CurrentUser,
    category_id: uuid.UUID | None = None,
) -> list[TemplateOut]:
    query = select(Template)
    if not user.is_staff:
        # A client sees shared templates plus any made for them.
        query = query.where(
            Template.status == TemplateStatus.PUBLISHED,
            (Template.client_id.is_(None)) | (Template.client_id == user.client_id),
        )
    if category_id is not None:
        query = query.where(Template.category_id == category_id)

    rows = db.scalars(query.order_by(Template.name)).all()
    counts = dict(
        db.execute(
            select(TemplateField.template_id, func.count(TemplateField.id)).group_by(
                TemplateField.template_id
            )
        ).all()
    )
    return [_template_out(row, counts.get(row.id, 0)) for row in rows]


def _get_template(db: DB, template_id: uuid.UUID) -> Template:
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "القالب غير موجود.")
    return template


@router.get("/templates/{template_id}", response_model=TemplateDetail)
def get_template(template_id: uuid.UUID, db: DB, _: CurrentUser) -> TemplateDetail:
    template = _get_template(db, template_id)
    detail = TemplateDetail.model_validate(template)
    detail.field_count = len(template.fields)
    detail.record_keys = template_service.record_keys(template)
    detail.static_keys = template_service.static_keys(template)
    detail.required_keys = template_service.required_record_keys(template)
    return detail


@router.post(
    "/templates",
    response_model=TemplateIngestOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_template(
    db: DB,
    _: Staff,
    file: UploadFile = File(...),
    name: str = Form(...),
    category_id: str | None = Form(None),
    client_id: str | None = Form(None),
) -> TemplateIngestOut:
    """Read a designer's .ai/.pdf and propose fields from its own geometry.

    Nothing is baked here: the original is kept intact and the artwork is only
    cleared at publish, once an admin has confirmed which regions are variable.
    """
    payload = await file.read()
    if len(payload) > settings.max_upload_bytes * 20:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "ملف التصميم أكبر من الحدّ المسموح.",
        )
    try:
        report = template_build.ingest(
            db,
            payload,
            file.filename or "design.pdf",
            name=name.strip() or "قالب بلا اسم",
            category_id=_uuid.UUID(category_id) if category_id else None,
            client_id=_uuid.UUID(client_id) if client_id else None,
        )
    except BuildError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    db.flush()
    db.refresh(report.template)
    return TemplateIngestOut(
        template=get_template(report.template.id, db, _),
        pages=report.pages,
        proposed_fields=report.proposed_fields,
        auto_named=report.auto_named,
        tables=report.tables,
    )


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: uuid.UUID, db: DB, _: Admin) -> None:
    template = _get_template(db, template_id)
    used = db.scalar(
        select(func.count()).select_from(Project).where(
            Project.template_id == template.id
        )
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"القالب مستخدم في {used} مشروعًا — لا يمكن حذفه.",
        )
    db.delete(template)


@router.get("/templates/{template_id}/pages/{page_index}.png")
def template_page(
    template_id: uuid.UUID,
    page_index: int,
    db: DB,
    user: CurrentUser,
    dpi: int = 96,
) -> Response:
    """A raster of one page, so a field box or a cover choice can be drawn over it.

    The editor is staff-only, but the builder's cover chooser runs before a
    project exists, so it has nothing but the template to show. A client may
    therefore raster a template they could already generate from -- published,
    and either shared or made for them -- and nothing else. A draft is still
    somebody's unfinished artwork.
    """
    template = _get_template(db, template_id)
    if not user.is_staff:
        visible = template.status == TemplateStatus.PUBLISHED and (
            template.client_id is None or template.client_id == user.client_id
        )
        if not visible:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "القالب غير موجود.")
    try:
        png = template_build.render_page(template, page_index, dpi=min(dpi, 200))
    except BuildError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.get("/templates/{template_id}/suggestions")
def template_suggestions(
    template_id: uuid.UUID, db: DB, _: Staff
) -> list[dict]:
    """Regions the design contains that are not yet fields, for click-to-add."""
    return template_build.suggestions(_get_template(db, template_id))


@router.put("/templates/{template_id}/sections", response_model=TemplateDetail)
def save_sections(
    template_id: uuid.UUID,
    payload: list[TemplateSectionUpdate],
    db: DB,
    _: Staff,
) -> TemplateDetail:
    """Replace the section plan. This is what makes a page block repeat."""
    template = _get_template(db, template_id)
    for section in payload:
        if section.last_page < section.first_page:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "نهاية القسم قبل بدايته.",
            )
        if section.first_page < 0 or section.last_page >= template.page_count:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"الصفحة {section.last_page + 1} خارج القالب "
                f"({template.page_count} صفحة).",
            )
        span = section.last_page - section.first_page + 1
        if section.kind == "per_record" and section.pages_per_item != span:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"القسم «{section.name}» يمتدّ على {span} صفحة، "
                f"وعدد الصفحات لكل سجلّ {section.pages_per_item}.",
            )

    for existing in list(template.sections):
        db.delete(existing)
    db.flush()
    for position, section in enumerate(payload):
        db.add(
            TemplateSection(
                template_id=template.id, position=position, **section.model_dump()
            )
        )
    db.flush()
    db.refresh(template)
    return get_template(template_id, db, _)


def _match(
    field: TemplateFieldUpdate,
    by_id: dict[uuid.UUID, TemplateField],
    by_name: dict[tuple[int, str], TemplateField],
    claimed: set[uuid.UUID],
) -> TemplateField | None:
    """The stored row a saved field is a new version of, if there is one.

    By id first: that survives a rename, and renaming keys is most of what the
    editor is for. By (page, key) second, which covers a client too old to send
    an id and an id that no longer exists -- after a template rebuild, say. Both
    skip a row another entry has already claimed, so a payload that names one
    row twice adds a field rather than quietly merging two.
    """
    if field.id is not None:
        row = by_id.get(field.id)
        if row is not None and row.id not in claimed:
            return row
    row = by_name.get((field.page_index, field.key))
    if row is not None and row.id not in claimed:
        return row
    return None


@router.put("/templates/{template_id}/fields", response_model=TemplateDetail)
def save_fields(
    template_id: uuid.UUID,
    payload: list[TemplateFieldUpdate],
    db: DB,
    _: Staff,
) -> TemplateDetail:
    """Bulk save from the template editor.

    The field set the editor sends is the field set the template ends up with --
    but a *column* it does not send is a column it is not asking to change, and
    keeps whatever it had.

    This used to delete every row and rebuild from the payload, which made the
    editor responsible for round-tripping every column in the table. It was not:
    `preserve_aspect`, `clip` and `clip_holes` have no control on that screen and
    were never sent back, so each save quietly reset them. Those are how a
    photograph is masked to the frame the designer drew and held off the number
    badge on top of it -- so correcting one field's label turned every photo
    frame in the booklet back into a rectangle, silently, with the screen still
    showing exactly what the operator expected.

    A column added to the table in future is safe here by construction, rather
    than safe until somebody forgets.
    """
    template = _get_template(db, template_id)

    # A repeated key across pages is legitimate -- the same lot value prints on
    # both of its pages -- but a repeat on one page is a mistake.
    per_page: dict[tuple[int, str], int] = {}
    for field in payload:
        per_page[(field.page_index, field.key)] = (
            per_page.get((field.page_index, field.key), 0) + 1
        )
    clashes = [k for k, n in per_page.items() if n > 1]
    if clashes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"مفتاح مكرّر على نفس الصفحة: {clashes[0][1]} (صفحة {clashes[0][0] + 1})",
        )

    # A field is the row, not its name. Matched by id where the editor sends one,
    # so renaming a key -- which is most of what the editor is for -- moves the
    # row rather than replacing it with a blank one.
    by_id = {row.id: row for row in template.fields}
    by_name = {(row.page_index, row.key): row for row in template.fields}

    kept: set[uuid.UUID] = set()
    for field in payload:
        row = _match(field, by_id, by_name, kept)
        if row is None:
            # Genuinely new: the model's own defaults apply to what was omitted.
            row = TemplateField(
                template_id=template.id, **field.model_dump(exclude={"id"})
            )
            db.add(row)
            db.flush()
        else:
            # Only what was actually sent. Everything else is not the editor's
            # to have an opinion about, so it keeps what it had.
            for column, value in field.model_dump(
                exclude_unset=True, exclude={"id"}
            ).items():
                setattr(row, column, value)
        kept.add(row.id)

    for row in template.fields:
        if row.id not in kept:
            db.delete(row)

    template.version += 1
    db.flush()
    db.refresh(template)
    return get_template(template_id, db, _)


@router.post("/templates/{template_id}/publish", response_model=TemplateOut)
def publish(template_id: uuid.UUID, db: DB, _: Admin) -> TemplateOut:
    """Validate the fonts, bake the artwork against the confirmed fields, publish.

    Admin-only, unlike the rest of the template surface. An operator prepares a
    template -- uploads it, names its fields, fixes the section plan -- and an
    admin signs it off: publishing bakes the artwork and is what puts a template
    in front of clients. This is what the permission matrix on the settings
    screen has always promised; the guard used to say ``Staff`` and disagree.
    """
    template = _get_template(db, template_id)
    try:
        template_build.publish(db, template)
    except BuildError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _template_out(template, len(template.fields))


@router.post("/templates/{template_id}/unpublish", response_model=TemplateOut)
def unpublish(template_id: uuid.UUID, db: DB, _: Admin) -> TemplateOut:
    """Take a published template back out of the catalogue. Admin-only, like publish.

    A client stops seeing it in the listing, cannot raster its pages and cannot
    start a project from it; staff still can, which is what makes this the way to
    pull a template out of circulation while its fields are corrected. Projects
    already built from it keep their baked artwork and still generate.
    """
    template = _get_template(db, template_id)
    try:
        template_build.unpublish(db, template)
    except BuildError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _template_out(template, len(template.fields))
