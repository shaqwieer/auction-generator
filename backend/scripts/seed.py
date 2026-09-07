"""Populate a fresh database with categories, accounts and the built templates.

    python scripts/seed.py

Idempotent: running it twice re-imports the templates (bumping their version) and
leaves the accounts alone.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Category, Client, Role, User
from app.services.templates import import_template

CATEGORIES = [
    ("booklet", "كتيّبات", "كتيّبات المزادات والكتالوجات متعدّدة الصفحات"),
    ("form", "نماذج ثابتة", "نماذج بصفحة واحدة بحقول ثابتة"),
    ("banner", "لافتات طبع", "لافتات ومقاسات كبيرة"),
    ("poster", "ملصقات", "ملصقات دعائية بصفحة واحدة"),
]

ACCOUNTS = [
    ("khalid@matbaa.sa", "خالد العتيبي", Role.ADMIN, None),
    ("sara@matbaa.sa", "سارة القحطاني", Role.OPERATOR, None),
    ("noura@fahd-group.sa", "نورة الحربي", Role.CLIENT, "AAYAN"),
]

DEFAULT_PASSWORD = "matbaa1234"


def main() -> None:
    settings = get_settings()
    session = SessionLocal()
    try:
        for slug, name, description in CATEGORIES:
            if not session.scalar(select(Category).where(Category.slug == slug)):
                session.add(
                    Category(
                        slug=slug,
                        name=name,
                        description=description,
                        position=len(CATEGORIES),
                    )
                )
        session.flush()

        client = session.scalar(select(Client).where(Client.code == "AAYAN"))
        if client is None:
            client = Client(
                name="شركة أعيان العقارية",
                code="AAYAN",
                contact_email="info@aayan.sa",
                contact_phone="0555405658",
            )
            session.add(client)
            session.flush()

        for email, name, role, client_code in ACCOUNTS:
            if session.scalar(select(User).where(User.email == email)):
                continue
            session.add(
                User(
                    email=email,
                    name=name,
                    password_hash=hash_password(DEFAULT_PASSWORD),
                    role=role,
                    client_id=client.id if client_code else None,
                )
            )
        session.flush()

        imported = []
        for directory in sorted(settings.templates_root.iterdir()):
            manifest_path = directory / "template.json"
            if not manifest_path.exists():
                continue
            # A built template names itself. Older manifests predate that, so
            # fall back to the slug rather than guessing from the directory.
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            name = manifest.get("name") or directory.name
            template = import_template(session, directory, name=name)
            imported.append((template.slug, template.page_count, len(template.fields)))

        session.commit()

        print("seeded:")
        print(f"  categories : {len(CATEGORIES)}")
        print(f"  client     : {client.name} ({client.code})")
        print(f"  accounts   : {', '.join(a[0] for a in ACCOUNTS)}")
        print(f"  password   : {DEFAULT_PASSWORD}")
        for slug, pages, fields in imported:
            print(f"  template   : {slug} — {pages} pages, {fields} fields")
        if not imported:
            print("  template   : none found; run scripts/build_infath_templates.py")
    finally:
        session.close()


if __name__ == "__main__":
    main()
