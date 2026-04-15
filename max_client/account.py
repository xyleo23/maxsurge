"""Управление MAX аккаунтами — авторизация, хранение токенов."""
import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select

from db.models import MaxAccount, AccountStatus, async_session_factory

# ── vkmax WebSocket fix: MAX server requires Origin + User-Agent headers ──
# Without these headers the server rejects the WebSocket handshake with HTTP 403.
# Patch vkmax.client.MaxClient.connect to always pass them.
import websockets as _ws
import vkmax.client as _vkmax_client

_WS_HEADERS = {
    "Origin": "https://web.max.ru",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


async def _patched_connect(self):
    """Connect to MAX WebSocket with required headers and optional proxy.

    MAX rejects WS handshake with HTTP 403 if Origin header is missing.
    MAX also blocks authorization requests from datacenter IPs — use a
    residential proxy via MAX_PROXY_URL env var (socks5:// or http://).
    """
    import os
    if self._connection:
        raise Exception("Already connected")
    proxy_url = os.getenv("MAX_PROXY_URL", "").strip() or None
    kwargs = {"additional_headers": _WS_HEADERS}
    if proxy_url:
        kwargs["proxy"] = proxy_url
        logger.info("[vkmax] connecting via proxy {}", proxy_url)
    else:
        logger.debug("[vkmax] connecting directly (no MAX_PROXY_URL)")
    self._connection = await _ws.connect(_vkmax_client.WS_HOST, **kwargs)
    self._recv_task = asyncio.create_task(self._recv_loop())
    logger.debug("[vkmax] connected")
    return self._connection


_vkmax_client.MaxClient.connect = _patched_connect

from vkmax.client import MaxClient


class MaxAccountManager:
    """Менеджер MAX аккаунтов. Один экземпляр на приложение."""

    def __init__(self):
        # phone -> (client, login_token)
        self._clients: dict[str, tuple[MaxClient, str]] = {}

    # ------------------------------------------------------------------ #
    #  Шаг 1: запросить SMS-код                                           #
    # ------------------------------------------------------------------ #
    async def request_sms(self, phone: str) -> str:
        """Отправляет SMS и возвращает sms_token (хранить до verify_sms)."""
        client = MaxClient()
        await client.connect()
        sms_token = await client.send_code(phone)
        # Сохраняем client временно (ключ = phone)
        self._clients[f"pending_{phone}"] = (client, sms_token)
        logger.info("SMS отправлен на {}", phone)
        return sms_token

    # ------------------------------------------------------------------ #
    #  Шаг 2: подтвердить SMS-код → получить login_token                  #
    # ------------------------------------------------------------------ #
    async def verify_sms(self, phone: str, sms_code: str) -> dict:
        """
        Подтверждает SMS-код. Возвращает {'login_token': ..., 'profile': ...}.
        Сохраняет аккаунт в БД.
        """
        pending_key = f"pending_{phone}"
        if pending_key not in self._clients:
            raise ValueError(f"Нет ожидающего SMS для {phone}. Сначала вызови request_sms.")

        client, sms_token = self._clients.pop(pending_key)

        resp = await client.sign_in(sms_token, int(sms_code))
        payload = resp.get("payload", {})
        login_token = payload.get("tokenAttrs", {}).get("LOGIN", {}).get("token") or \
                      payload.get("token", "")
        profile = payload.get("profile", {})
        profile_name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
        max_user_id = profile.get("userId") or profile.get("id")

        # Сохраняем клиент как активный
        self._clients[phone] = (client, login_token)

        # Записываем/обновляем в БД
        async with async_session_factory() as session:
            existing = (await session.execute(
                select(MaxAccount).where(MaxAccount.phone == phone)
            )).scalar_one_or_none()

            if existing:
                existing.login_token = login_token
                existing.status = AccountStatus.ACTIVE
                existing.profile_name = profile_name
                existing.max_user_id = max_user_id
            else:
                acc = MaxAccount(
                    phone=phone,
                    login_token=login_token,
                    profile_name=profile_name,
                    max_user_id=max_user_id,
                    status=AccountStatus.ACTIVE,
                )
                session.add(acc)
            await session.commit()

        logger.info("Аккаунт {} авторизован: {} (max_id={})", phone, profile_name, max_user_id)
        return {"login_token": login_token, "profile_name": profile_name, "max_user_id": max_user_id}

# ------------------------------------------------------------------ #
    #  Добавить аккаунт по готовому login_token (без SMS)                #
    # ------------------------------------------------------------------ #
    async def add_by_token(self, login_token: str, phone: str | None = None) -> dict:
        """
        Авторизует клиент по готовому login_token и сохраняет в БД.
        Если phone не передан, берёт из профиля после логина.
        """
        client = MaxClient()
        await client.connect()
        resp = await client.login_by_token(login_token)
        payload = resp.get("payload", {})
        profile = payload.get("profile", {})

        profile_phone = profile.get("phone") or phone
        if not profile_phone:
            raise ValueError("Не удалось получить телефон из профиля. Укажите phone вручную.")
        profile_phone = str(profile_phone)

        profile_name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
        max_user_id = profile.get("userId") or profile.get("id")

        self._clients[profile_phone] = (client, login_token)

        async with async_session_factory() as session:
            existing = (await session.execute(
                select(MaxAccount).where(MaxAccount.phone == profile_phone)
            )).scalar_one_or_none()
            if existing:
                existing.login_token = login_token
                existing.status = AccountStatus.ACTIVE
                existing.profile_name = profile_name
                existing.max_user_id = max_user_id
            else:
                acc = MaxAccount(
                    phone=profile_phone,
                    login_token=login_token,
                    profile_name=profile_name,
                    max_user_id=max_user_id,
                    status=AccountStatus.ACTIVE,
                )
                session.add(acc)
            await session.commit()

        logger.info("Аккаунт {} добавлен по токену: {} (max_id={})", profile_phone, profile_name, max_user_id)
        return {"phone": profile_phone, "profile_name": profile_name, "max_user_id": max_user_id}

    # ------------------------------------------------------------------ #
    #  Восстановить сессию по сохранённому токену                         #
    # ------------------------------------------------------------------ #
    async def restore_session(self, phone: str, login_token: str) -> MaxClient | None:
        """Восстанавливает сессию из сохранённого login_token."""
        if phone in self._clients:
            return self._clients[phone][0]
        try:
            client = MaxClient()
            await client.connect()
            await client.login_by_token(login_token)
            self._clients[phone] = (client, login_token)
            logger.info("Сессия {} восстановлена", phone)
            return client
        except Exception as e:
            logger.warning("Не удалось восстановить сессию {}: {}", phone, e)
            return None

    # ------------------------------------------------------------------ #
    #  Получить активный клиент                                           #
    # ------------------------------------------------------------------ #
    async def get_client(self, phone: str) -> MaxClient | None:
        if phone in self._clients:
            return self._clients[phone][0]
        # Попробуем восстановить из БД
        async with async_session_factory() as session:
            acc = (await session.execute(
                select(MaxAccount).where(MaxAccount.phone == phone)
            )).scalar_one_or_none()
        if acc and acc.login_token:
            return await self.restore_session(phone, acc.login_token)
        return None

    async def get_all_active_clients(self) -> list[tuple[MaxAccount, MaxClient]]:
        """Возвращает список (account, client) для всех активных аккаунтов."""
        result = []
        async with async_session_factory() as session:
            accounts = (await session.execute(
                select(MaxAccount).where(MaxAccount.status == AccountStatus.ACTIVE)
            )).scalars().all()

        for acc in accounts:
            client = await self.get_client(acc.phone)
            if client:
                result.append((acc, client))
        return result

    async def mark_blocked(self, phone: str):
        async with async_session_factory() as session:
            acc = (await session.execute(
                select(MaxAccount).where(MaxAccount.phone == phone)
            )).scalar_one_or_none()
            if acc:
                acc.status = AccountStatus.BLOCKED
                await session.commit()
        if phone in self._clients:
            del self._clients[phone]

    async def delete_account(self, account_id: int):
        async with async_session_factory() as session:
            acc = await session.get(MaxAccount, account_id)
            if acc:
                if acc.phone in self._clients:
                    try:
                        await self._clients[acc.phone][0].disconnect()
                    except Exception:
                        pass
                    del self._clients[acc.phone]
                await session.delete(acc)
                await session.commit()

    async def restore_all(self):
        """Восстановить все сессии при старте приложения."""
        async with async_session_factory() as session:
            accounts = (await session.execute(
                select(MaxAccount).where(
                    MaxAccount.status == AccountStatus.ACTIVE,
                    MaxAccount.login_token.isnot(None),
                )
            )).scalars().all()

        for acc in accounts:
            await self.restore_session(acc.phone, acc.login_token)
        logger.info("Восстановлено {} MAX сессий", len(accounts))


# Глобальный синглтон
account_manager = MaxAccountManager()
