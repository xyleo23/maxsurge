"""Import chats into ChatCatalog from CSV/XLSX/TSV.

Expected columns (case-insensitive, rus/eng both accepted):
    - title / Название / Name                    → name
    - category / Категория                        → category
    - link / Ссылка / Ссылка на чат / invite_link → invite_link
    - members / subscribers / Подписчики          → members_count
    - description / Описание                      → description

Usage:
    ./venv/bin/python scripts/import_catalog.py path/to/file.csv \\
        [--owner-id N]    # None = public catalog (default)
        [--dedupe]        # skip if link already exists
        [--dry-run]       # parse and validate, don't write
        [--sheet NAME]    # for XLSX: sheet name (default: first)
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from sqlalchemy import select
from db.models import ChatCatalog, async_session_factory, init_db


FIELD_MAP = {
    # name
    "title": "name", "name": "name", "название": "name", "название чата": "name", "chat": "name",
    # category
    "category": "category", "категория": "category", "cat": "category",
    # link
    "link": "invite_link", "ссылка": "invite_link", "ссылка на чат": "invite_link",
    "invite_link": "invite_link", "url": "invite_link",
    # members
    "members": "members_count", "members_count": "members_count",
    "subscribers": "members_count", "подписчики": "members_count",
    "участники": "members_count",
    # description
    "description": "description", "описание": "description", "desc": "description",
}


def _normalize_header(h: str) -> str:
    return (h or "").strip().lower().lstrip("\ufeff")


def _parse_int(v) -> int | None:
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace(",", "").replace(" ", "")
    if not s or not re.search(r"\d", s):
        return None
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _is_channel(link: str | None) -> bool:
    if not link:
        return False
    return "/channel/" in link.lower()


def _read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        dialect = csv.Sniffer().sniff(f.read(4096), delimiters=",;\t")
        f.seek(0)
        reader = csv.DictReader(f, dialect=dialect)
        return [dict(r) for r in reader]


def _read_xlsx(path: str, sheet: str | None = None) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        print("ERROR: openpyxl not installed — pip install openpyxl", file=sys.stderr)
        sys.exit(1)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    # Find header row (first non-empty row)
    header_idx = 0
    for i, r in enumerate(rows):
        if any(c is not None and str(c).strip() for c in r):
            non_empty = sum(1 for c in r if c is not None and str(c).strip())
            if non_empty >= 2:
                header_idx = i
                break
    headers = [str(c or "").strip() for c in rows[header_idx]]
    out = []
    for r in rows[header_idx + 1:]:
        if not any(c is not None and str(c).strip() for c in r):
            continue
        out.append({headers[i]: r[i] if i < len(r) else None for i in range(len(headers))})
    return out


def _read_any(path: str, sheet: str | None = None) -> list[dict]:
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path, sheet)
    return _read_csv(path)


async def import_rows(rows: list[dict], owner_id: int | None, dedupe: bool, dry_run: bool) -> dict:
    stats = {"total": len(rows), "inserted": 0, "skipped_dupe": 0, "skipped_bad": 0}

    async with async_session_factory() as s:
        existing_links: set[str] = set()
        if dedupe:
            q = select(ChatCatalog.invite_link)
            if owner_id is None:
                q = q.where(ChatCatalog.owner_id.is_(None))
            else:
                q = q.where(ChatCatalog.owner_id == owner_id)
            existing_links = {l for l in (await s.execute(q)).scalars().all() if l}

        batch = []
        for raw in rows:
            norm = {}
            for k, v in raw.items():
                mapped = FIELD_MAP.get(_normalize_header(k))
                if mapped:
                    norm[mapped] = v

            name = (str(norm.get("name") or "")).strip()
            link = (str(norm.get("invite_link") or "")).strip() or None
            if not name:
                stats["skipped_bad"] += 1
                continue
            if dedupe and link and link in existing_links:
                stats["skipped_dupe"] += 1
                continue

            row = ChatCatalog(
                owner_id=owner_id,
                name=name[:512],
                description=(str(norm.get("description") or "")).strip()[:5000] or None,
                invite_link=link[:512] if link else None,
                category=(str(norm.get("category") or "")).strip()[:128] or None,
                members_count=_parse_int(norm.get("members_count")),
                is_channel=_is_channel(link),
            )
            batch.append(row)
            if link:
                existing_links.add(link)

        if dry_run:
            stats["inserted"] = len(batch)
            stats["dry_run"] = True
        else:
            s.add_all(batch)
            await s.commit()
            stats["inserted"] = len(batch)

    return stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="path to .csv/.tsv/.xlsx")
    parser.add_argument("--owner-id", type=int, default=None, help="user_id to attach; omit = public catalog")
    parser.add_argument("--dedupe", action="store_true", help="skip rows with invite_link already in DB")
    parser.add_argument("--dry-run", action="store_true", help="parse + validate, don't insert")
    parser.add_argument("--sheet", default=None, help="XLSX sheet name (default: active)")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    rows = _read_any(args.file, args.sheet)
    print(f"Parsed {len(rows)} rows from {args.file}")
    if not rows:
        sys.exit(0)

    await init_db()
    stats = await import_rows(rows, args.owner_id, args.dedupe, args.dry_run)
    print(f"\n=== IMPORT {'(DRY-RUN)' if args.dry_run else 'DONE'} ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
