"""Чекер номеров → MAX user_id. Привязка телефонов из 2GIS к аккаунтам MAX."""
import asyncio
from datetime import datetime

from loguru import logger
from sqlalchemy import select, update

from db.models import Lead, LeadStatus, async_session_factory
from max_client.account import account_manager
from max_client.ops import resolve_users, add_to_contacts

_check_status: dict = {"running": False, "found": 0, "not_found": 0, "total": 0, "log": []}


def get_check_status() -> dict:
    return dict(_check_status)


def _normalize_phone(phone: str) -> str:
    """Нормализовать телефон для MAX: +7... → 7..."""
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if p.startswith("+"):
        p = p[1:]
    if p.startswith("8") and len(p) == 11:
        p = "7" + p[1:]
    return p


async def check_phone_batch(client, phones: list[str]) -> dict[str, int | None]:
    """
    Проверяет список номеров через add_to_contacts + resolve.
    Возвращает {phone: user_id или None}.
    """
    result: dict[str, int | None] = {}

    for phone in phones:
        norm = _normalize_phone(phone)
        try:
            # Добавляем в контакты по номеру
            resp = await client.invoke_method(
                opcode=34,
                payload={
                    "phone": norm,
                    "action": "ADD",
                }
            )
            payload = resp.get("payload", {})
            user_id = payload.get("userId") or payload.get("contactId") or payload.get("id")
            if user_id:
                result[phone] = int(user_id)
            else:
                # Пробуем через другой формат
                result[phone] = None
        except Exception as e:
            logger.debug("Чек {} не удался: {}", phone, e)
            result[phone] = None
        await asyncio.sleep(3)  # лимит 10-20 чеков/день, осторожно!

    return result


async def run_phone_checker(limit: int = 20, phone: str | None = None):
    """
    Проверяет телефоны из лидов (у кого есть phone, но нет max_user_id).
    Привязывает найденные max_user_id.
    """
    global _check_status
    _check_status = {"running": True, "found": 0, "not_found": 0, "total": 0, "log": []}

    try:
        # Получаем клиент
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

        # Загружаем лиды с телефоном без MAX ID
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
                resp = await client.invoke_method(
                    opcode=34,
                    payload={"phone": norm, "action": "ADD"}
                )
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
                    _check_status["log"].append(f"[—] {lead.name} ({lead.phone}) — не найден в MAX")
            except Exception as e:
                _check_status["not_found"] += 1
                _check_status["log"].append(f"[ERR] {lead.name} ({lead.phone}): {str(e)[:60]}")

            await asyncio.sleep(5)  # осторожно — лимит 10-20/день!

    except Exception as e:
        _check_status["log"].append(f"ОШИБКА: {e}")
    finally:
        _check_status["running"] = False
        logger.info("Чекер: found={} not_found={}", _check_status["found"], _check_status["not_found"])


def stop_checker():
    global _check_status
    _check_status["running"] = False
