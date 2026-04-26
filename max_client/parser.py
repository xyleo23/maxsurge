"""Парсинг чатов MAX — вступление, сбор участников, резолв ссылок."""
import asyncio
import re
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import ParsedUser, ChatCatalog, async_session_factory
from max_client.account import account_manager
from max_client.ops import load_members, join_group as join_group_by_link, resolve_chat_by_link as resolve_group_by_link
from max_client.ops import join_channel, resolve_chat_by_link as resolve_channel_username
from max_client.ops import resolve_users
from max_client.webhook_dispatcher import dispatch_webhook

_parse_status: dict = {"running": False, "parsed": 0, "chats_done": 0, "total_chats": 0, "log": []}


def get_parse_status() -> dict:
    return dict(_parse_status)


def _extract_hash_from_link(link: str) -> str | None:
    """Извлечь hash из ссылки вида max.ru/join/XXXX или просто XXXX."""
    link = link.strip()
    m = re.search(r"join/([A-Za-z0-9_-]+)", link)
    if m:
        return m.group(1)
    m = re.search(r"max\.ru/([A-Za-z0-9_-]+)", link)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9_-]+$", link):
        return link
    return None


async def join_chat_by_link(client, link: str) -> dict | None:
    """Вступить в чат/канал по ссылке. Возвращает info о чате."""
    link = link.strip()
    try:
        # Пробуем как invite hash
        h = _extract_hash_from_link(link)
        if h:
            try:
                resp = await join_group_by_link(client, h)
                return resp
            except Exception:
                pass
            try:
                resp = await join_channel(client, h)
                return resp
            except Exception:
                pass
        # Пробуем как username
        if "/" in link:
            username = link.rstrip("/").split("/")[-1]
        else:
            username = link
        resp = await join_channel(client, username)
        return resp
    except Exception as e:
        logger.warning("Не удалось вступить в {}: {}", link, e)
        return None


async def resolve_chat(client, link: str) -> dict | None:
    """Резолв ссылки → информация о чате."""
    h = _extract_hash_from_link(link)
    try:
        if h:
            return await resolve_group_by_link(client, h)
        username = link.rstrip("/").split("/")[-1] if "/" in link else link
        return await resolve_channel_username(client, username)
    except Exception as e:
        logger.debug("Не удалось резолвить {}: {}", link, e)
        return None


async def parse_chat_members(client, chat_id: int, max_count: int = 5000) -> list[dict]:
    """Получить участников чата. Возвращает список {userId, firstName, ...}."""
    all_members = []
    marker: int | None = 0
    while len(all_members) < max_count:
        batch_size = min(200, max_count - len(all_members))
        # PyMax: load_members(client, chat_id, count, marker) -> (members_list, next_marker)
        members, next_marker = await load_members(client, chat_id, count=batch_size, marker=marker)
        if not members:
            break
        # Convert PyMax Member objects to vkmax-style dicts for backwards compat
        for m in members:
            all_members.append({
                "userId": getattr(m, "id", None) or getattr(m, "user_id", None),
                "firstName": getattr(m, "first_name", "") or "",
                "lastName": getattr(m, "last_name", "") or "",
                "phone": getattr(m, "phone", ""),
                "username": getattr(m, "username", ""),
            })
        if not next_marker:
            break
        marker = next_marker
        await asyncio.sleep(0.5)
    return all_members


async def mass_join_chats(links: list[str], phone: str | None = None) -> dict:
    """Массовое вступление в чаты."""
    global _parse_status
    _parse_status = {"running": True, "parsed": 0, "chats_done": 0, "total_chats": len(links), "log": []}

    try:
        if phone:
            client = await account_manager.get_client(phone)
            if not client:
                _parse_status["log"].append(f"Аккаунт {phone} не найден")
                return _parse_status
        else:
            pairs = await account_manager.get_all_active_clients()
            if not pairs:
                _parse_status["log"].append("Нет активных аккаунтов")
                return _parse_status
            _, client = pairs[0]

        for link in links:
            if not _parse_status["running"]:
                break
            result = await join_chat_by_link(client, link)
            if result:
                _parse_status["log"].append(f"[OK] Вступили: {link}")
                # Сохраняем в каталог
                payload = result.get("payload", {})
                chat = payload.get("chat", {})
                if chat:
                    async with async_session_factory() as s:
                        existing = (await s.execute(
                            select(ChatCatalog).where(ChatCatalog.chat_id == chat.get("id"))
                        )).scalar_one_or_none()
                        if not existing:
                            s.add(ChatCatalog(
                                chat_id=chat.get("id"),
                                name=chat.get("title", link),
                                invite_link=link,
                                members_count=chat.get("membersCount"),
                                is_channel=chat.get("chatType") == "CHANNEL",
                            ))
                            await s.commit()
            else:
                _parse_status["log"].append(f"[FAIL] {link}")
            _parse_status["chats_done"] += 1
            await asyncio.sleep(12)  # лимит: 10сек между вступлениями
    except Exception as e:
        _parse_status["log"].append(f"ОШИБКА: {e}")
    finally:
        _parse_status["running"] = False
    return _parse_status


async def parse_chat(chat_id: int, chat_name: str = "", phone: str | None = None) -> int:
    """Спарсить участников одного чата, сохранить в БД. Вернуть кол-во."""
    global _parse_status

    if phone:
        client = await account_manager.get_client(phone)
    else:
        pairs = await account_manager.get_all_active_clients()
        if not pairs:
            return 0
        _, client = pairs[0]

    if not client:
        return 0

    members = await parse_chat_members(client, chat_id)
    saved = 0

    async with async_session_factory() as s:
        for m in members:
            uid = m.get("userId")
            if not uid:
                continue
            existing = (await s.execute(
                select(ParsedUser).where(
                    ParsedUser.max_user_id == uid,
                    ParsedUser.source_chat_id == chat_id,
                )
            )).scalar_one_or_none()
            if existing:
                continue
            s.add(ParsedUser(
                max_user_id=uid,
                first_name=m.get("firstName"),
                last_name=m.get("lastName"),
                username=m.get("username"),
                source_chat_id=chat_id,
                source_chat_name=chat_name,
            ))
            saved += 1
        await s.commit()

        # Обновить или создать запись в публичном каталоге MaxSurge.
        # Парсинг прошёл успешно (>=1 участник) → список открыт → шарим.
        cat = (await s.execute(
            select(ChatCatalog).where(ChatCatalog.chat_id == chat_id)
        )).scalar_one_or_none()
        if cat:
            cat.parsed_count += 1
            cat.last_parsed_at = datetime.utcnow()
            cat.members_count = len(members)
            if len(members) > 0:
                cat.members_open = True
                cat.last_checked_at = datetime.utcnow()
            await s.commit()
        elif len(members) > 0:
            # Auto-discovery: добавляем в общую базу (owner_id=NULL)
            s.add(ChatCatalog(
                owner_id=None,
                chat_id=chat_id,
                name=(chat_name or f"Chat {chat_id}")[:512],
                members_count=len(members),
                is_channel=False,
                parsed_count=1,
                last_parsed_at=datetime.utcnow(),
                members_open=True,
                last_checked_at=datetime.utcnow(),
            ))
            await s.commit()

    _parse_status["parsed"] += saved
    _parse_status["log"].append(f"[PARSE] {chat_name or chat_id}: {saved} новых из {len(members)}")

    # Webhook: lead_collected (парсинг участников)
    if saved > 0:
        asyncio.create_task(dispatch_webhook(0, "lead_collected", {
            "source": "chat_members",
            "chat_id": chat_id,
            "chat_name": chat_name,
            "new_leads": saved,
            "total_members": len(members),
        }))
    return saved


def stop_parsing():
    global _parse_status
    _parse_status["running"] = False


# ── P4: Парсинг участников через историю сообщений ─────────
async def parse_users_from_messages(
    client,
    chat_id: int,
    owner_id: int | None = None,
    chat_name: str | None = None,
    max_messages: int = 2000,
    batch_size: int = 50,
) -> int:
    """Собрать уникальных авторов сообщений из истории чата.

    Работает через opcode=49 (getMessages) — забирает историю порциями
    по `batch_size` и извлекает senderId из каждого сообщения. Полезно
    когда список участников закрыт, но чат доступен для чтения.
    """
    global _parse_status
    from db.models import ParsedUser, async_session_factory
    from sqlalchemy import select

    _parse_status["log"].append(f"[MSG-PARSE] {chat_name or chat_id}: история ({max_messages} max)")

    seen_senders: dict[int, dict] = {}
    # Начинаем с сейчас и идём назад
    cid_marker = 2000000000000  # large cid = "start from newest"
    fetched = 0
    empty_rounds = 0

    while fetched < max_messages:
        try:
            resp = await client.invoke_method(
                opcode=49,
                payload={
                    "chatId": chat_id,
                    "from": cid_marker,
                    "forward": 0,
                    "backward": batch_size,
                    "getMessages": True,
                },
            )
        except Exception as e:
            logger.warning("[parser] history error: {}", e)
            break

        payload = (resp or {}).get("payload") or {}
        msgs = payload.get("messages") or payload.get("history") or []
        if not msgs:
            empty_rounds += 1
            if empty_rounds >= 2:
                break
            await asyncio.sleep(1)
            continue
        empty_rounds = 0

        oldest_cid = None
        for m in msgs:
            sender = m.get("sender") or m.get("senderId") or m.get("userId")
            if isinstance(sender, dict):
                sid = sender.get("userId") or sender.get("id")
                seen_senders.setdefault(sid, {
                    "first_name": sender.get("firstName") or sender.get("first_name"),
                    "last_name": sender.get("lastName") or sender.get("last_name"),
                    "username": sender.get("username"),
                })
            elif isinstance(sender, int):
                seen_senders.setdefault(sender, {})
            mcid = m.get("cid") or m.get("time") or m.get("id")
            if isinstance(mcid, (int, float)) and (oldest_cid is None or mcid < oldest_cid):
                oldest_cid = mcid

        fetched += len(msgs)
        if oldest_cid is None or oldest_cid >= cid_marker:
            # зациклились
            break
        cid_marker = oldest_cid - 1
        await asyncio.sleep(0.3)

    # Сохраняем в БД
    saved = 0
    async with async_session_factory() as s:
        for uid, meta in seen_senders.items():
            if not uid:
                continue
            existing = (await s.execute(
                select(ParsedUser).where(
                    ParsedUser.max_user_id == uid,
                    ParsedUser.source_chat_id == chat_id,
                )
            )).scalar_one_or_none()
            if existing:
                continue
            s.add(ParsedUser(
                owner_id=owner_id,
                max_user_id=uid,
                first_name=meta.get("first_name"),
                last_name=meta.get("last_name"),
                username=meta.get("username"),
                source_chat_id=chat_id,
                source_chat_name=chat_name,
            ))
            saved += 1
        await s.commit()

    _parse_status["parsed"] += saved
    _parse_status["log"].append(
        f"[MSG-PARSE] {chat_name or chat_id}: {saved} новых авторов (обработано {fetched} сообщений, уникальных {len(seen_senders)})"
    )

    # Webhook: lead_collected (парсинг по сообщениям)
    if saved > 0 and owner_id:
        asyncio.create_task(dispatch_webhook(owner_id, "lead_collected", {
            "source": "message_history",
            "chat_id": chat_id,
            "chat_name": chat_name,
            "new_leads": saved,
            "messages_processed": fetched,
        }))
    return saved


async def parse_by_messages_phones(
    phones: list[str],
    chat_ids: list[int],
    owner_id: int | None = None,
    max_messages: int = 2000,
) -> int:
    """Запустить парсинг по сообщениям для списка чатов через любой доступный аккаунт."""
    global _parse_status
    if _parse_status.get("running"):
        return 0

    _parse_status = {
        "running": True,
        "parsed": 0,
        "chats_done": 0,
        "total_chats": len(chat_ids),
        "log": [f"[START MSG-PARSE] Чатов: {len(chat_ids)}, макс сообщений: {max_messages}"],
    }

    total = 0
    try:
        for chat_id in chat_ids:
            if not _parse_status["running"]:
                break
            # Берём первый доступный клиент
            client = None
            for phone in phones:
                c = await account_manager.get_client(phone)
                if c:
                    client = c
                    break
            if not client:
                _parse_status["log"].append("[ERR] Нет активных аккаунтов")
                break
            added = await parse_users_from_messages(
                client,
                chat_id=chat_id,
                owner_id=owner_id,
                max_messages=max_messages,
            )
            total += added
            _parse_status["chats_done"] += 1
    finally:
        _parse_status["running"] = False
        _parse_status["log"].append(f"[DONE] Итого добавлено: {total}")
    return total
