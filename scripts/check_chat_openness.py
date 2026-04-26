"""Backfill: проверить открытость списка участников для существующих ChatCatalog.

Идёт по записям где members_open IS NULL, пробует load_members через
первый активный аккаунт юзера (или owner-aware: для записей с owner_id —
через аккаунт владельца). Записывает результат в БД.

Usage:
    ./venv/bin/python scripts/check_chat_openness.py [--limit 100] [--dry-run]
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa
from db.models import ChatCatalog, MaxAccount, AccountStatus, async_session_factory, init_db  # noqa
from max_client.account import account_manager  # noqa
from max_client.ops import load_members  # noqa


async def main(limit: int, dry_run: bool, only_unchecked: bool) -> None:
    await init_db()
    await account_manager.restore_all()

    pairs = await account_manager.get_all_active_clients()
    if not pairs:
        print("ERROR: нет активных MAX-аккаунтов для проверки", file=sys.stderr)
        sys.exit(1)

    print(f"Используем {len(pairs)} аккаунт(а) для чека")

    async with async_session_factory() as s:
        q = select(ChatCatalog)
        if only_unchecked:
            q = q.where(ChatCatalog.members_open.is_(None))
        q = q.where(ChatCatalog.is_channel == False)  # каналы не парсятся
        q = q.limit(limit)
        rows = (await s.execute(q)).scalars().all()

    print(f"К проверке: {len(rows)} записей")
    print()

    open_count = 0
    closed_count = 0
    error_count = 0

    for i, row in enumerate(rows, 1):
        if not row.chat_id:
            print(f"[{i}/{len(rows)}] {row.name[:40]:40} skip (no chat_id)")
            error_count += 1
            continue

        # Берём аккаунт владельца если есть, иначе любой активный
        client = None
        if row.owner_id:
            async with async_session_factory() as s:
                acc = (await s.execute(
                    select(MaxAccount).where(
                        MaxAccount.owner_id == row.owner_id,
                        MaxAccount.status == AccountStatus.ACTIVE,
                    ).limit(1)
                )).scalar_one_or_none()
            if acc:
                client = await account_manager.get_client(acc.phone)
        if client is None:
            client = pairs[i % len(pairs)][1]

        try:
            members, _ = await load_members(client, row.chat_id, count=10)
            is_open = len(members) > 0
        except Exception as e:
            err = str(e)[:60]
            print(f"[{i}/{len(rows)}] {row.name[:40]:40} ERROR: {err}")
            error_count += 1
            if not dry_run:
                async with async_session_factory() as s:
                    r = await s.get(ChatCatalog, row.id)
                    if r:
                        r.members_open = False  # пометим как недоступный
                        r.last_checked_at = datetime.utcnow()
                        await s.commit()
            await asyncio.sleep(2)
            continue

        if is_open:
            open_count += 1
            mark = "✓ open"
        else:
            closed_count += 1
            mark = "✗ closed"

        print(f"[{i}/{len(rows)}] {row.name[:40]:40} {mark} ({len(members)} members)")

        if not dry_run:
            async with async_session_factory() as s:
                r = await s.get(ChatCatalog, row.id)
                if r:
                    r.members_open = is_open
                    r.last_checked_at = datetime.utcnow()
                    await s.commit()

        await asyncio.sleep(3)  # rate-limit safety

    print()
    print("=" * 50)
    print(f"Open:    {open_count}")
    print(f"Closed:  {closed_count}")
    print(f"Errors:  {error_count}")
    print(f"Total:   {len(rows)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true", help="включая уже проверенные")
    args = ap.parse_args()
    asyncio.run(main(args.limit, args.dry_run, only_unchecked=not args.all))
