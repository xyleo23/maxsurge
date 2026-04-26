"""Lightweight liveness check для ChatCatalog: resolve без join.

Идёт по записям где members_open IS NULL.
Через resolve_group_by_link получает chat_id (= чат жив).
Не делает join — это значило бы засорять наш аккаунт сотнями чатов.

Логика:
- resolve OK → members_open=True (оптимистично, чат жив, скорее всего открыт)
- resolve fails 'not.found' → members_open=False (мёртвая ссылка)
- любая другая ошибка → оставить NULL для повтора

Реальную openness узнаем когда юзер впервые парсит этот чат
(см. parser.py: success → True, access denied → False).

Usage:
    ./venv/bin/python scripts/check_chat_openness.py [--limit 100] [--dry-run]
"""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa
from db.models import ChatCatalog, async_session_factory, init_db  # noqa
from max_client.account import account_manager  # noqa


async def _resolve_one(client, link: str) -> tuple[str, int | None]:
    """Returns (status, chat_id). status: 'alive' | 'dead' | 'error'."""
    try:
        chat = await client.resolve_group_by_link(link)
        if chat and chat.id:
            return ("alive", chat.id)
        return ("dead", None)
    except Exception as e:
        err = str(e).lower()
        if "not.found" in err or "not found" in err or "finder" in err:
            return ("dead", None)
        return ("error", None)


async def main(limit: int, dry_run: bool, only_unchecked: bool) -> None:
    await init_db()
    await account_manager.restore_all()

    pairs = await account_manager.get_all_active_clients()
    if not pairs:
        print("ERROR: нет активных MAX-аккаунтов", file=sys.stderr)
        sys.exit(1)

    print(f"Используем {len(pairs)} аккаунт(а)")

    async with async_session_factory() as s:
        q = select(ChatCatalog).where(ChatCatalog.is_channel == False)
        if only_unchecked:
            q = q.where(ChatCatalog.members_open.is_(None))
        q = q.where(ChatCatalog.invite_link.isnot(None))
        q = q.order_by(ChatCatalog.members_count.desc().nullslast()).limit(limit)
        rows = (await s.execute(q)).scalars().all()

    if not rows:
        print("Нет записей для проверки.")
        return

    print(f"К проверке: {len(rows)} записей")
    print(f"Mode: {'DRY-RUN' if dry_run else 'LIVE'}")
    print()

    counters = {"alive": 0, "dead": 0, "error": 0}

    for i, row in enumerate(rows, 1):
        _acc, client = pairs[i % len(pairs)]
        try:
            status, chat_id = await _resolve_one(client, row.invite_link)
        except Exception as e:
            status, chat_id = "error", None
            print(f"[{i}/{len(rows)}] {row.name[:40]:40} CAUGHT: {str(e)[:50]}")

        counters[status] += 1
        marks = {"alive": "✓ alive", "dead":  "💀 dead", "error": "⚠ error"}
        chat_id_str = f"id={chat_id}" if chat_id else ""
        print(f"[{i}/{len(rows)}] {row.name[:40]:40} {marks[status]:10} {chat_id_str}")

        if not dry_run:
            async with async_session_factory() as s:
                r = await s.get(ChatCatalog, row.id)
                if r:
                    r.last_checked_at = datetime.utcnow()
                    if status == "alive":
                        r.members_open = True
                        if chat_id and not r.chat_id:
                            r.chat_id = chat_id
                    elif status == "dead":
                        r.members_open = False
                    # error: оставляем NULL для retry
                    await s.commit()

        # Rate-limit safety (resolve дешевле load_members, но всё равно бережно)
        await asyncio.sleep(1.5)

    print()
    print("=" * 50)
    for k, v in counters.items():
        print(f"  {k:<10} {v}")
    print(f"  total      {len(rows)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true", help="включая уже проверенные")
    args = ap.parse_args()
    asyncio.run(main(args.limit, args.dry_run, only_unchecked=not args.all))
