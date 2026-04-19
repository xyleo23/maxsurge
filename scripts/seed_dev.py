"""Dev fixtures: creates test users, leads, templates for local development.

Usage (только для dev/staging, НЕ в проде!):
    ENV=dev ./venv/bin/python scripts/seed_dev.py
    ENV=dev ./venv/bin/python scripts/seed_dev.py --wipe  # wipe first

Creates:
- 3 test users (trial / basic / pro)
- 10 leads with varied statuses
- 3 message templates
- 5 chats in catalog
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta

# Refuse to run in prod — basic safety
if os.environ.get("ENV", "").lower() not in ("dev", "staging", "test"):
    print("ERROR: seed_dev.py requires ENV=dev|staging|test. Refusing to run.", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from passlib.hash import bcrypt
from sqlalchemy import delete, select

from db.models import (
    async_session_factory,
    init_db,
    SiteUser, UserPlan,
    Lead, LeadStatus,
    MessageTemplate, TemplateStatus,
    ChatCatalog,
)


TEST_USERS = [
    ("dev-trial@test.local", "test12345", "Trial User", UserPlan.TRIAL, None),
    ("dev-basic@test.local", "test12345", "Basic User", UserPlan.BASIC, timedelta(days=25)),
    ("dev-pro@test.local", "test12345", "Pro User", UserPlan.PRO, timedelta(days=180)),
]

TEST_LEADS = [
    ("+79000000001", "Иван", "seed", LeadStatus.NEW),
    ("+79000000002", "Мария", "seed", LeadStatus.CONTACTED),
    ("+79000000003", "Пётр", "seed", LeadStatus.REPLIED),
    ("+79000000004", "Анна", "seed", LeadStatus.CONVERTED),
    ("+79000000005", "Сергей", "seed", LeadStatus.NEW),
    ("+79000000006", "Ольга", "seed", LeadStatus.NEW),
    ("+79000000007", "Дмитрий", "seed", LeadStatus.BLACKLISTED),
    ("+79000000008", "Елена", "seed", LeadStatus.NEW),
    ("+79000000009", "Алексей", "seed", LeadStatus.CONTACTED),
    ("+79000000010", "Наталья", "seed", LeadStatus.REPLIED),
]

TEST_TEMPLATES = [
    ("Приветствие", "Здравствуйте, {name}! {Пишу|Обращаюсь} по поводу ваших услуг. Интересно обсудить сотрудничество."),
    ("Follow-up", "{name}, добрый день! Напоминаю о нашем разговоре — есть ли время обсудить предложение?"),
    ("Акция", "{name}, для вас {персональная|эксклюзивная} скидка 20% до конца недели. Интересно?"),
]

TEST_CHATS = [
    ("Бизнес-чат Москва", "https://max.ru/join/abc001", "public"),
    ("Стартапы РФ", "https://max.ru/join/abc002", "public"),
    ("Маркетологи", "https://max.ru/join/abc003", "public"),
    ("SMM-комьюнити", "https://max.ru/join/abc004", "public"),
    ("Digital агентства", "https://max.ru/join/abc005", "public"),
]


async def wipe_seed_data(s):
    """Удалить данные, созданные сидером (по owner_id тестовых юзеров)."""
    test_emails = [e for e, _, _, _, _ in TEST_USERS]
    test_users = (await s.execute(select(SiteUser).where(SiteUser.email.in_(test_emails)))).scalars().all()
    ids = [u.id for u in test_users]
    if ids:
        await s.execute(delete(Lead).where(Lead.owner_id.in_(ids)))
        await s.execute(delete(MessageTemplate).where(MessageTemplate.owner_id.in_(ids)))
        await s.execute(delete(ChatCatalog).where(ChatCatalog.owner_id.in_(ids)))
        await s.execute(delete(SiteUser).where(SiteUser.id.in_(ids)))
        await s.commit()
        print(f"wiped {len(ids)} test users and their data")


async def seed(wipe: bool = False):
    await init_db()
    async with async_session_factory() as s:
        if wipe:
            await wipe_seed_data(s)

        now = datetime.utcnow()
        created_users = []
        for email, pw, name, plan, ttl in TEST_USERS:
            existing = (await s.execute(select(SiteUser).where(SiteUser.email == email))).scalar_one_or_none()
            if existing:
                created_users.append(existing)
                continue
            u = SiteUser(
                email=email,
                password_hash=bcrypt.using(rounds=12).hash(pw),
                name=name,
                plan=plan,
                plan_expires_at=(now + ttl) if ttl else None,
                is_active=True,
                is_superadmin=False,
            )
            s.add(u)
            created_users.append(u)
        await s.commit()
        for u in created_users:
            await s.refresh(u)

        # Attach sample data to Basic user
        owner = next((u for u in created_users if u.email == "dev-basic@test.local"), None)
        if not owner:
            print("skip: basic user not found")
            return

        has_leads = (await s.execute(select(Lead).where(Lead.owner_id == owner.id).limit(1))).first()
        if not has_leads:
            for phone, name, source, status in TEST_LEADS:
                s.add(Lead(owner_id=owner.id, phone=phone, name=name, source=source, status=status))
            print(f"added {len(TEST_LEADS)} leads")

        has_tpl = (await s.execute(select(MessageTemplate).where(MessageTemplate.owner_id == owner.id).limit(1))).first()
        if not has_tpl:
            for name, body in TEST_TEMPLATES:
                s.add(MessageTemplate(owner_id=owner.id, name=name, body=body, is_active=True))
            print(f"added {len(TEST_TEMPLATES)} templates")

        has_chats = (await s.execute(select(ChatCatalog).where(ChatCatalog.owner_id == owner.id).limit(1))).first()
        if not has_chats:
            for title, link, ctype in TEST_CHATS:
                s.add(ChatCatalog(owner_id=owner.id, title=title, link=link, chat_type=ctype))
            print(f"added {len(TEST_CHATS)} chats")

        await s.commit()

    print("\n=== SEED DONE ===")
    print("Login credentials:")
    for email, pw, _, plan, _ in TEST_USERS:
        print(f"  {email}  /  {pw}   ({plan.value})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true", help="delete existing seed data first")
    args = parser.parse_args()
    asyncio.run(seed(wipe=args.wipe))
