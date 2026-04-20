"""SQLite → PostgreSQL миграция для MaxSurge.

Что делает:
1. Создаёт схему в целевой Postgres-БД (CREATE TABLE ...) через SQLAlchemy metadata
2. Копирует все строки из SQLite таблица-за-таблицей (в порядке FK)
3. Сбрасывает sequence для autoincrement-колонок чтобы следующий INSERT не упал
4. Печатает сверку rowcount до/после

Usage:
    # 1. Подготовка: поднять Postgres (см. docker-compose.prod.yml)
    # 2. Установить драйверы на сервере
    ./venv/bin/pip install asyncpg psycopg2-binary

    # 3. Прогнать миграцию
    SRC=sqlite+aiosqlite:///max_leadfinder.db \\
    DST=postgresql+asyncpg://maxsurge:PASS@localhost:5432/maxsurge \\
    ./venv/bin/python scripts/sqlite_to_postgres.py

    # 4. Смоук-тест: сравнить rowcount'ы перед переключением
    ./venv/bin/python scripts/sqlite_to_postgres.py --verify-only

    # 5. Переключить .env DATABASE_URL → systemctl restart maxsurge

Безопасно: НЕ пишет в SQLite, не удаляет целевые таблицы. Таргет должен быть
свежей пустой БД. При повторном запуске упадёт на уникальных ключах — это
ожидаемо, для повторного прогона сначала DROP DATABASE + CREATE DATABASE.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make project importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema

from db.models import Base  # noqa: E402


BATCH_SIZE = 1000


def _sync_url(async_url: str) -> str:
    """Convert async SQLAlchemy URL to sync for metadata ops."""
    return (
        async_url
        .replace("+aiosqlite", "")
        .replace("+asyncpg", "")
        .replace("+psycopg", "")
    )


def _table_order(metadata) -> list:
    """Topologically sorted list of tables (parents before children)."""
    return list(metadata.sorted_tables)


async def create_schema(dst_url: str) -> None:
    """Create all tables in destination via SQLAlchemy metadata."""
    sync_dst = _sync_url(dst_url)
    engine = create_engine(sync_dst)
    Base.metadata.create_all(engine)
    engine.dispose()
    print(f"✓ Schema created in {sync_dst.split('@')[-1]}")


def count_rows(url: str, tables: list[str]) -> dict[str, int]:
    """Row counts per table using sync engine (simpler for one-shot)."""
    engine = create_engine(_sync_url(url))
    out: dict[str, int] = {}
    with engine.connect() as conn:
        for t in tables:
            try:
                n = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
            except Exception:
                n = 0
            out[t] = n
    engine.dispose()
    return out


def copy_table(src_url: str, dst_url: str, table_name: str) -> int:
    """Copy all rows for one table. Returns row count copied."""
    src = create_engine(_sync_url(src_url))
    dst = create_engine(_sync_url(dst_url))
    copied = 0
    try:
        with src.connect() as src_conn, dst.begin() as dst_conn:
            # Read all columns
            rows = src_conn.execute(text(f'SELECT * FROM "{table_name}"')).mappings().all()
            if not rows:
                return 0
            cols = list(rows[0].keys())
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(f":{c}" for c in cols)
            sql = text(f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})')

            # Batch insert
            batch: list[dict] = []
            for r in rows:
                batch.append(dict(r))
                if len(batch) >= BATCH_SIZE:
                    dst_conn.execute(sql, batch)
                    copied += len(batch)
                    batch.clear()
            if batch:
                dst_conn.execute(sql, batch)
                copied += len(batch)
    finally:
        src.dispose()
        dst.dispose()
    return copied


def reset_sequences(dst_url: str, tables: list) -> None:
    """For each table with integer id column, set the sequence to max(id)+1.

    Postgres-only. Safe no-op on SQLite.
    """
    sync_dst = _sync_url(dst_url)
    if "postgresql" not in sync_dst and "postgres" not in sync_dst:
        return
    engine = create_engine(sync_dst)
    with engine.begin() as conn:
        for t in tables:
            tname = t.name
            # Find primary key column (usually 'id')
            pk_cols = [c.name for c in t.primary_key.columns]
            if len(pk_cols) != 1:
                continue
            pk = pk_cols[0]
            # Try both naming conventions Postgres uses
            seq_name = f"{tname}_{pk}_seq"
            try:
                max_id = conn.execute(text(f'SELECT COALESCE(MAX("{pk}"), 0) FROM "{tname}"')).scalar() or 0
                conn.execute(text(f"SELECT setval('{seq_name}', :v)"), {"v": max(max_id, 1)})
                print(f"  sequence {seq_name} → {max_id}")
            except Exception as e:
                # Column might not be SERIAL (e.g. composite PK or custom IDs)
                pass
    engine.dispose()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=os.environ.get("SRC", "sqlite+aiosqlite:///max_leadfinder.db"))
    ap.add_argument("--dst", default=os.environ.get("DST", ""))
    ap.add_argument("--verify-only", action="store_true", help="only compare row counts, no copy")
    ap.add_argument("--skip-schema", action="store_true", help="skip CREATE TABLE (if already done)")
    ap.add_argument("--tables", nargs="*", help="specific tables only (default: all)")
    args = ap.parse_args()

    if not args.dst:
        print("ERROR: --dst or DST env required (e.g. postgresql+asyncpg://user:pw@host/db)", file=sys.stderr)
        sys.exit(1)

    print(f"SRC: {args.src}")
    print(f"DST: {args.dst.split('@')[-1]}")
    print()

    all_tables = _table_order(Base.metadata)
    if args.tables:
        all_tables = [t for t in all_tables if t.name in args.tables]

    table_names = [t.name for t in all_tables]

    # VERIFY MODE
    if args.verify_only:
        src_counts = count_rows(args.src, table_names)
        dst_counts = count_rows(args.dst, table_names)
        print(f"{'TABLE':<30} {'SRC':>10} {'DST':>10}  MATCH")
        print("-" * 60)
        ok = True
        for name in table_names:
            s = src_counts.get(name, 0)
            d = dst_counts.get(name, 0)
            m = "✓" if s == d else "✗"
            if s != d:
                ok = False
            print(f"{name:<30} {s:>10} {d:>10}  {m}")
        sys.exit(0 if ok else 1)

    # CREATE SCHEMA
    if not args.skip_schema:
        asyncio.run(create_schema(args.dst))

    # COPY DATA
    print("\nCopying rows (batch size {}):".format(BATCH_SIZE))
    src_counts = count_rows(args.src, table_names)
    total = 0
    for table in all_tables:
        name = table.name
        n_src = src_counts.get(name, 0)
        if n_src == 0:
            print(f"  {name:<30}  empty, skip")
            continue
        n_copied = copy_table(args.src, args.dst, name)
        total += n_copied
        status = "✓" if n_copied == n_src else "✗"
        print(f"  {name:<30}  {n_src:>6} → {n_copied:>6}  {status}")

    # RESET SEQUENCES
    print("\nResetting Postgres sequences:")
    reset_sequences(args.dst, all_tables)

    # VERIFY
    print("\nFinal verification:")
    dst_counts = count_rows(args.dst, table_names)
    mismatches = [(n, src_counts[n], dst_counts[n]) for n in table_names if src_counts[n] != dst_counts[n]]
    if mismatches:
        print("❌ MISMATCH in these tables:")
        for name, s, d in mismatches:
            print(f"  {name}: src={s}, dst={d}")
        sys.exit(1)

    print(f"\n✅ Migration complete. {total} rows copied across {len(all_tables)} tables.")
    print("\nNext steps:")
    print("  1. Update .env: DATABASE_URL=postgresql+asyncpg://...")
    print("  2. systemctl restart maxsurge")
    print("  3. Monitor: journalctl -u maxsurge -f")
    print("  4. Rollback plan: DATABASE_URL=sqlite+aiosqlite:///max_leadfinder.db && systemctl restart maxsurge")


if __name__ == "__main__":
    main()
