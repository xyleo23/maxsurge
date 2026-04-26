"""Импорт публичных чатов из max-catalog24.ru → ChatCatalog.

Этическая позиция: берём только факты о публичных сообществах
(название, ссылка max.ru/join, число участников, категория).
Description не копируем — это их редакторский текст.
members_open=NULL — наш checker проверит открытость списков отдельно.

Usage:
    ./venv/bin/python scripts/seed_from_max_catalog24.py
    ./venv/bin/python scripts/seed_from_max_catalog24.py --dry-run
    ./venv/bin/python scripts/seed_from_max_catalog24.py --update-existing
"""
import argparse
import asyncio
import base64
import sys
import urllib.parse
import urllib.request
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa
from db.models import ChatCatalog, async_session_factory, init_db  # noqa


SOURCE_URL = (
    "https://gist.githubusercontent.com/Sheikerok/"
    "ff8e219307efda3d8bf7fcb007a1e551/raw/"
    "8d19417a0b02a0dbfcfa7a9ad9ef9e92a5fe2084/gistfile1.txt"
)
ENCRYPTION_KEY = "max-chats-2025-secure-key-12345"


def fetch_and_decrypt() -> list:
    """Скачать → base64 → XOR → JSON list."""
    print(f"⤓ fetching {SOURCE_URL[:80]}...")
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "MaxSurge-seed/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        encrypted = r.read().decode("utf-8").strip()
    print(f"  encrypted: {len(encrypted):,} bytes")

    decoded = base64.b64decode(encrypted)
    print(f"  base64-decoded: {len(decoded):,} bytes")

    chars = []
    for i, b in enumerate(decoded):
        chars.append(chr(b ^ ord(ENCRYPTION_KEY[i % len(ENCRYPTION_KEY)])))
    plain = urllib.parse.unquote("".join(chars))
    print(f"  plaintext: {len(plain):,} chars")

    data = json.loads(plain)
    print(f"  parsed: {len(data):,} entries")
    return data


def looks_like_channel(invite_link: str | None) -> bool:
    """В каталоге max-catalog24 нет явного флага канал/чат.
    Эвристика: max.ru/channel/... → канал, max.ru/join/... → чат.
    """
    if not invite_link:
        return False
    return "/channel/" in invite_link.lower()


def normalize_link(link: str | None) -> str | None:
    """Нормализуем ссылки для дедупа: убираем query/fragment, lowercase host."""
    if not link:
        return None
    link = link.strip()
    if not link.startswith(("http://", "https://")):
        return None
    # Уберём query и trailing slash
    link = link.split("?")[0].split("#")[0].rstrip("/")
    return link


async def import_data(rows: list, dry_run: bool, update_existing: bool) -> dict:
    """Импортирует записи в ChatCatalog. Returns stats."""
    stats = {
        "total": len(rows),
        "inserted": 0,
        "updated": 0,
        "skipped_dupe": 0,
        "skipped_bad": 0,
        "skipped_channels": 0,
    }

    await init_db()

    async with async_session_factory() as s:
        # Загрузим существующие invite_links для дедупа
        existing_q = select(ChatCatalog.invite_link, ChatCatalog.id).where(
            ChatCatalog.invite_link.isnot(None)
        )
        existing_map = {
            l: cid for l, cid in (await s.execute(existing_q)).all() if l
        }
        print(f"  existing in DB: {len(existing_map):,} entries with invite_link")
        print()

        new_records = []

        for row in rows:
            # Структура: [id, name, category, invite_link, members_count, description]
            if not isinstance(row, list) or len(row) < 4:
                stats["skipped_bad"] += 1
                continue

            name = (row[1] or "").strip() if len(row) > 1 else ""
            category = (row[2] or "").strip() if len(row) > 2 else None
            invite_link = normalize_link(row[3] if len(row) > 3 else None)
            members_count = row[4] if len(row) > 4 else None

            # Только записи с валидной ссылкой и именем
            if not name or not invite_link:
                stats["skipped_bad"] += 1
                continue

            # Каналы пропускаем (для парсинга нужны чаты)
            if looks_like_channel(invite_link):
                stats["skipped_channels"] += 1
                continue

            # Парсим число участников: может быть int, str с числом
            try:
                members_count = int(members_count) if members_count not in (None, "") else None
            except (ValueError, TypeError):
                members_count = None

            # Дедуп по invite_link
            if invite_link in existing_map:
                if update_existing:
                    if not dry_run:
                        cat_id = existing_map[invite_link]
                        existing = await s.get(ChatCatalog, cat_id)
                        if existing:
                            if members_count is not None:
                                existing.members_count = members_count
                            if category and not existing.category:
                                existing.category = category[:128]
                            await s.commit()
                    stats["updated"] += 1
                else:
                    stats["skipped_dupe"] += 1
                continue

            # New record
            new_records.append(ChatCatalog(
                owner_id=None,  # общая база MaxSurge
                chat_id=None,   # узнаем при первом парсинге
                name=name[:512],
                description=None,  # НЕ копируем их текст
                invite_link=invite_link[:512],
                category=category[:128] if category else None,
                members_count=members_count,
                is_channel=False,
                parsed_count=0,
                last_parsed_at=None,
                members_open=None,        # ещё не проверено
                last_checked_at=None,
            ))
            stats["inserted"] += 1
            existing_map[invite_link] = -1  # отметим что уже в batch

        if dry_run:
            print(f"\n[DRY-RUN] would insert {stats['inserted']:,} new records")
        else:
            # Bulk insert
            if new_records:
                s.add_all(new_records)
                await s.commit()
                print(f"\n✓ inserted {len(new_records):,} new records")

    return stats


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--update-existing", action="store_true",
                    help="обновить members_count и category для уже существующих записей")
    args = ap.parse_args()

    print("=" * 60)
    print("Seed ChatCatalog from max-catalog24.ru")
    print("=" * 60)
    print()

    try:
        data = fetch_and_decrypt()
    except Exception as e:
        print(f"ERROR fetching/decrypting: {e}", file=sys.stderr)
        sys.exit(1)

    print()
    stats = await import_data(data, args.dry_run, args.update_existing)

    print()
    print("=" * 60)
    print("Import summary:")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:<20} {v:>8,}")

    if not args.dry_run:
        print()
        print("Next steps:")
        print("  1. Запустите проверку открытости:")
        print("     ./venv/bin/python scripts/check_chat_openness.py --limit 50")
        print("  2. Или дождитесь ежедневного cron'а (0 4 * * *)")


if __name__ == "__main__":
    asyncio.run(main())
