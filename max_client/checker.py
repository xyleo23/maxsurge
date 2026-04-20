"""Упрощённая версия + расширенный Max-чекер: batch по произвольному списку.

Старый API (run_phone_checker, check_phone_batch) оставлен для совместимости.
Новый API (run_bulk_checker) — по списку номеров/User ID с настройкой пауз и
распределением по нескольким аккаунтам.
"""
import asyncio
import random
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import Lead, async_session_factory
from max_client.account import account_manager

# ── Legacy API (не трогаем) ─────────────────────────────────
_check_status: dict = {"running": False, "found": 0, "not_found": 0, "total": 0, "log": []}


def get_check_status() -> dict:
    return dict(_check_status)


def _normalize_phone(phone: str) -> str:
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if p.startswith("+"):
        p = p[1:]
    if p.startswith("8") and len(p) == 11:
        p = "7" + p[1:]
    return p


async def check_phone_batch(client, phones: list[str]) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for phone in phones:
        norm = _normalize_phone(phone)
        try:
            resp = await client.invoke_method(
                opcode=34,
                payload={"phone": norm, "action": "ADD"},
            )
            payload = resp.get("payload", {})
            user_id = payload.get("userId") or payload.get("contactId") or payload.get("id")
            result[phone] = int(user_id) if user_id else None
        except Exception as e:
            logger.debug("Чек {} не удался: {}", phone, e)
            result[phone] = None
        await asyncio.sleep(3)
    return result


async def run_phone_checker(limit: int = 20, phone: str | None = None):
    """Легаси: проверяет Lead.phone без max_user_id, пишет результат в Lead."""
    global _check_status
    _check_status = {"running": True, "found": 0, "not_found": 0, "total": 0, "log": []}
    try:
        if phone:
            client = await account_manager.get_client(phone)
        else:
            pairs = await account_manager.get_all_active_clients()
            if not pairs:
                _check_status["log"].append("Нет активных аккаунтов")
                return
            _, client = pairs[0]
        if not client:
            _check_status["log"].append("Клиент не найден")
            return

        async with async_session_factory() as s:
            leads = (await s.execute(
                select(Lead).where(
                    Lead.phone.isnot(None),
                    Lead.phone != "",
                    Lead.max_user_id.is_(None),
                ).limit(limit)
            )).scalars().all()

        _check_status["total"] = len(leads)
        if not leads:
            _check_status["log"].append("Нет лидов для проверки")
            return

        for lead in leads:
            if not _check_status["running"]:
                break
            norm = _normalize_phone(lead.phone)
            try:
                resp = await client.invoke_method(opcode=34, payload={"phone": norm, "action": "ADD"})
                payload = resp.get("payload", {})
                user_id = payload.get("userId") or payload.get("contactId") or payload.get("id")
                if user_id:
                    uid = int(user_id)
                    async with async_session_factory() as s:
                        db_lead = await s.get(Lead, lead.id)
                        if db_lead:
                            db_lead.max_user_id = uid
                            db_lead.updated_at = datetime.utcnow()
                            await s.commit()
                    _check_status["found"] += 1
                    _check_status["log"].append(f"[OK] {lead.name} ({lead.phone}) → MAX ID: {uid}")
                else:
                    _check_status["not_found"] += 1
                    _check_status["log"].append(f"[—] {lead.name} ({lead.phone}) — не найден")
            except Exception as e:
                _check_status["not_found"] += 1
                _check_status["log"].append(f"[ERR] {lead.name} ({lead.phone}): {str(e)[:60]}")
            await asyncio.sleep(5)
    except Exception as e:
        _check_status["log"].append(f"ОШИБКА: {e}")
    finally:
        _check_status["running"] = False
        logger.info("Чекер: found={} not_found={}", _check_status["found"], _check_status["not_found"])


def stop_checker():
    global _check_status
    _check_status["running"] = False


# ═══════════════════════════════════════════════════════════════════════
#  NEW API: Bulk checker — free-form list, multi-account, 2 modes
# ═══════════════════════════════════════════════════════════════════════

_bulk_status: dict = {
    "running": False,
    "mode": "",            # 'soft' | 'mass' | 'userid'
    "total": 0,
    "processed": 0,
    "found": 0,
    "not_found": 0,
    "results": [],          # [{input, status, user_id, account, error}]
    "started_at": None,
    "finished_at": None,
}


def get_bulk_status() -> dict:
    return dict(_bulk_status)


def stop_bulk_checker():
    global _bulk_status
    _bulk_status["running"] = False


async def _check_one_phone(client, phone: str, action: str = "ADD") -> tuple[int | None, str | None]:
    """Return (user_id_or_None, error_or_None)."""
    norm = _normalize_phone(phone)
    try:
        resp = await client.invoke_method(opcode=34, payload={"phone": norm, "action": action})
        payload = resp.get("payload", {})
        uid = payload.get("userId") or payload.get("contactId") or payload.get("id")
        return (int(uid) if uid else None, None)
    except Exception as e:
        return (None, str(e)[:80])


async def _check_one_userid(client, user_id: int) -> tuple[bool, str | None]:
    """Check existence of user by id. Return (exists, error)."""
    try:
        # PyMax exposes resolve / fetch-profile. Fall back to opcode if absent.
        profile = await client.get_user(user_id)
        return (profile is not None, None)
    except AttributeError:
        # Fall back to raw opcode (user lookup = 32 or 2 depending on PyMax version)
        try:
            resp = await client.invoke_method(opcode=32, payload={"contactIds": [user_id]})
            contacts = resp.get("payload", {}).get("contacts", [])
            return (bool(contacts), None)
        except Exception as e:
            return (False, str(e)[:80])
    except Exception as e:
        return (False, str(e)[:80])


async def run_bulk_checker(
    items: list[str],
    account_phones: list[str],
    mode: str = "soft",        # 'soft' | 'mass' | 'userid'
    pause_from: int = 20,
    pause_to: int = 30,
    limit_per_account: int = 50,
) -> None:
    """Parallelize items across accounts, aggregate results in _bulk_status.

    - soft: sequential, pauses pause_from..pause_to sec, cap limit_per_account
    - mass: batches of 100, shorter pauses, but overwrites contact names
    - userid: resolve user_ids (no contact add, no overwrites)
    """
    global _bulk_status
    _bulk_status = {
        "running": True,
        "mode": mode,
        "total": len(items),
        "processed": 0,
        "found": 0,
        "not_found": 0,
        "results": [],
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": None,
    }

    try:
        # Resolve clients
        clients: list = []
        for phone in account_phones:
            c = await account_manager.get_client(phone)
            if c:
                clients.append((phone, c))
        if not clients:
            _bulk_status["results"].append({"status": "error", "error": "нет активных аккаунтов"})
            return

        # Distribute items round-robin across clients, respecting limit_per_account for soft
        per_acc_counter = {p: 0 for p, _ in clients}
        queue = list(items)

        if mode == "mass":
            # Batches of 100 per account, then rotate
            batch_size = 100
            while queue and _bulk_status["running"]:
                for phone, client in clients:
                    if not queue or not _bulk_status["running"]:
                        break
                    batch = queue[:batch_size]
                    queue = queue[batch_size:]
                    for item in batch:
                        if not _bulk_status["running"]:
                            break
                        uid, err = await _check_one_phone(client, item, action="ADD")
                        _record_result(item, uid, err, phone)
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                    # Short pause between batches
                    await asyncio.sleep(random.uniform(pause_from, pause_to))

        elif mode == "userid":
            # Resolve user IDs, no contact changes
            for item in queue:
                if not _bulk_status["running"]:
                    break
                # Rotate account for each item
                phone, client = clients[_bulk_status["processed"] % len(clients)]
                try:
                    uid_int = int(item)
                except ValueError:
                    _record_result(item, None, "not_a_number", phone)
                    continue
                exists, err = await _check_one_userid(client, uid_int)
                _record_result(item, uid_int if exists else None, err, phone)
                await asyncio.sleep(random.uniform(pause_from, pause_to) / 10.0)  # UserID лимиты мягче

        else:  # soft
            for item in queue:
                if not _bulk_status["running"]:
                    break
                # Find account with quota left
                eligible = [(p, c) for p, c in clients if per_acc_counter[p] < limit_per_account]
                if not eligible:
                    _bulk_status["results"].append({
                        "input": item, "status": "skipped",
                        "error": f"все аккаунты достигли лимита {limit_per_account}",
                    })
                    _bulk_status["processed"] += 1
                    continue
                phone, client = eligible[_bulk_status["processed"] % len(eligible)]
                per_acc_counter[phone] += 1

                uid, err = await _check_one_phone(client, item, action="ADD")
                _record_result(item, uid, err, phone)
                await asyncio.sleep(random.uniform(pause_from, pause_to))

    except Exception as e:
        logger.exception("bulk checker failed: {}", e)
        _bulk_status["results"].append({"status": "error", "error": str(e)[:200]})
    finally:
        _bulk_status["running"] = False
        _bulk_status["finished_at"] = datetime.utcnow().isoformat() + "Z"
        logger.info("[bulk-checker] done: {} found / {} not found out of {}",
                    _bulk_status["found"], _bulk_status["not_found"], _bulk_status["total"])


def _record_result(item: str, uid: int | None, err: str | None, account: str) -> None:
    global _bulk_status
    if uid:
        status = "found"
        _bulk_status["found"] += 1
    elif err and "error" not in err.lower()[:10]:
        status = "error"
    else:
        status = "not_found"
        _bulk_status["not_found"] += 1
    _bulk_status["results"].append({
        "input": item,
        "status": status,
        "user_id": uid,
        "account": account,
        "error": err,
    })
    _bulk_status["processed"] += 1
    # Cap in-memory results to avoid OOM on huge jobs
    if len(_bulk_status["results"]) > 5000:
        _bulk_status["results"] = _bulk_status["results"][-5000:]
