"""Управление MAX аккаунтами через PyMax — QR login, token import, per-account proxy.

Architecture:
- Каждому MaxAccount соответствует PyMax MaxClient с изолированной work_dir.
- Сессия хранится в БД: (login_token, device_id) на аккаунт.
- Прокси per-account: берётся из MaxAccount.proxy или из MAX_PROXY_URL env fallback.
- QR login: генерирует QR, polls status, сохраняет token в БД.
- Token import: принимает готовый token+device_id, валидирует через sync, сохраняет.

Note: vkmax снят с поддержки потому что MAX отключил phone-auth через WS API (25.12.13+).
Рабочие методы: QR auth (web.max.ru flow) и token-based restore.
"""
import asyncio
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import qrcode
from loguru import logger
from sqlalchemy import select

from db.models import MaxAccount, AccountStatus, async_session_factory

from pymax import MaxClient, Opcode
from pymax.payloads import UserAgentPayload


# ── Константы ─────────────────────────────────────
SESSIONS_ROOT = Path("/root/max_leadfinder/sessions_pymax")
SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)

# Минимальная версия для QR login (PyMax требование)
MIN_APP_VERSION = "25.12.13"

# Глобальный дефолтный прокси (если у аккаунта нет своего)
DEFAULT_PROXY = os.getenv("MAX_PROXY_URL", "").strip() or None

# QR login активные сессии в памяти (phone → state)
_qr_sessions: dict[str, dict[str, Any]] = {}

# Rate limit cooldown: phone -> unix_ts_until_allowed
# Set when MAX returns login.flood, prevents restore retries for 30 min
_flood_cooldown: dict[str, float] = {}
FLOOD_COOLDOWN_SEC = 30 * 60  # 30 minutes


def _get_work_dir(phone: str) -> Path:
    """Отдельная work_dir для каждого аккаунта — изоляция sqlite session.db."""
    safe = phone.replace("+", "").replace(":", "_").replace("/", "_")
    d = SESSIONS_ROOT / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_user_agent(app_version: str = MIN_APP_VERSION) -> UserAgentPayload:
    """Randomized device fingerprint to reduce pattern-based bans.
    
    MAX Sheiker Manager v1.0.5 added this, and it's important for anti-ban:
    if all sessions have identical fingerprints, MAX can detect automation.
    """
    import random

    os_variants = [
        ("macOS", "Macintosh; Intel Mac OS X 10_15_7"),
        ("Windows 10", "Windows NT 10.0; Win64; x64"),
        ("Windows 11", "Windows NT 10.0; Win64; x64"),
        ("Linux", "X11; Linux x86_64"),
        ("ChromeOS", "X11; CrOS x86_64 14541.0.0"),
    ]
    device_names = ["Chrome", "Yandex", "Edge", "Opera", "Vivaldi", "Brave", "Arc"]
    chrome_versions = ["131.0.0.0", "130.0.0.0", "129.0.0.0", "128.0.0.0", "127.0.0.0", "132.0.0.0"]
    screens = ["1920x1080 1.0x", "1440x900 2.0x", "2560x1440 1.0x", "1366x768 1.0x", "1536x864 1.25x", "1680x1050 1.0x"]
    timezones = ["Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", "Asia/Novosibirsk", "Asia/Almaty"]

    os_name, os_ua = random.choice(os_variants)
    device = random.choice(device_names)
    chrome_ver = random.choice(chrome_versions)
    screen = random.choice(screens)
    tz = random.choice(timezones)

    return UserAgentPayload(
        device_type="WEB",
        app_version=app_version,
        os_version=os_name,
        device_name=device,
        device_locale="ru-RU",
        header_user_agent=(
            f"Mozilla/5.0 ({os_ua}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{chrome_ver} Safari/537.36"
        ),
        locale="ru_RU",
        screen=screen,
        timezone=tz,
    )


def _make_client(
    phone: str,
    proxy: str | None = None,
    token: str | None = None,
    device_id: str | None = None,
    app_version: str = MIN_APP_VERSION,
) -> MaxClient:
    """Создаёт PyMax клиент с правильной конфигурацией.

    :param phone: телефон аккаунта (используется как ключ)
    :param proxy: per-account proxy URL (http:// or socks5://), fallback на DEFAULT_PROXY
    :param token: existing login_token (для восстановления сессии)
    :param device_id: existing device UUID (требуется вместе с token)
    :param app_version: версия клиента (>= 25.12.13)
    """
    work_dir = str(_get_work_dir(phone))
    ua = _make_user_agent(app_version)
    effective_proxy = proxy or DEFAULT_PROXY

    dev_id = None
    if device_id:
        try:
            dev_id = UUID(device_id)
        except (ValueError, TypeError):
            logger.warning("Invalid device_id {}, generating new", device_id)

    client = MaxClient(
        phone=phone,
        work_dir=work_dir,
        headers=ua,
        proxy=effective_proxy,
        token=token,
        device_id=dev_id,
        reconnect=True,  # PyMax auto-reconnect with backoff
    )
    return client


# ════════════════════════════════════════════════════════════════════
#  MaxAccountManager — главный менеджер
# ════════════════════════════════════════════════════════════════════
class MaxAccountManager:
    """Менеджер MAX аккаунтов. Один экземпляр на приложение."""

    def __init__(self):
        # phone → active PyMax client
        self._clients: dict[str, MaxClient] = {}

    # ─────────────────────────────────────────────────────────────
    #  QR LOGIN (self-service: юзер сканирует QR с телефона)
    # ─────────────────────────────────────────────────────────────

    async def start_qr_login(
        self,
        phone: str,
        proxy: str | None = None,
    ) -> dict[str, Any]:
        """
        Начинает QR login flow. Создаёт клиент, запрашивает QR у MAX.

        :return: {'qr_link', 'track_id', 'qr_png_path', 'expires_at', 'poll_interval'}
        """
        # Отмена старой сессии если была
        if phone in _qr_sessions:
            try:
                old = _qr_sessions.pop(phone)
                if old.get("client"):
                    await old["client"]._ws.close()
            except Exception:
                pass

        client = _make_client(phone, proxy=proxy)
        ua = _make_user_agent()
        await client.connect(user_agent=ua)
        logger.info("[qr] connected for {}", phone)

        qr_data = await client._request_qr_login()
        qr_link = qr_data["qrLink"]
        track_id = qr_data["trackId"]
        poll_interval = qr_data["pollingInterval"]
        expires_at = qr_data["expiresAt"]

        # Генерим QR PNG
        qr_dir = Path("/root/max_leadfinder/web/static/qr_login")
        qr_dir.mkdir(parents=True, exist_ok=True)
        fname = f"qr_{track_id}.png"
        img = qrcode.make(qr_link)
        img.save(qr_dir / fname)

        _qr_sessions[phone] = {
            "client": client,
            "track_id": track_id,
            "qr_link": qr_link,
            "qr_png": f"/static/qr_login/{fname}",
            "expires_at": expires_at,
            "poll_interval": poll_interval,
            "started_at": time.time(),
            "proxy": proxy,
            "status": "waiting",
        }
        logger.info("[qr] QR ready for {} (expires in {}s)", phone, int((expires_at/1000) - time.time()))

        return {
            "track_id": track_id,
            "qr_link": qr_link,
            "qr_png": f"/static/qr_login/{fname}",
            "expires_at": expires_at,
            "poll_interval": poll_interval,
        }

    async def poll_qr_login(self, phone: str) -> dict[str, Any]:
        """
        Проверяет статус QR login. Если подтверждён — получает токен и сохраняет в БД.

        :return: {'status': 'waiting'|'confirmed'|'expired', 'profile'?, 'token'?}
        """
        state = _qr_sessions.get(phone)
        if not state:
            return {"status": "not_started"}

        now_ms = time.time() * 1000
        if now_ms >= state["expires_at"]:
            state["status"] = "expired"
            return {"status": "expired"}

        client: MaxClient = state["client"]
        try:
            data = await client._send_and_wait(
                opcode=Opcode.GET_QR_STATUS,
                payload={"trackId": state["track_id"]},
            )
            payload = data.get("payload", {})
            status = payload.get("status", {})

            if status.get("loginAvailable"):
                # Получаем финальный токен
                login_data = await client._get_qr_login_data(state["track_id"])
                token = login_data.get("tokenAttrs", {}).get("LOGIN", {}).get("token")
                profile = login_data.get("profile", {})

                if not token:
                    return {"status": "error", "error": "no_token_in_response"}

                profile_phone = str(profile.get("phone") or phone)
                profile_name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
                max_user_id = profile.get("userId") or profile.get("id")
                device_id_str = str(client._device_id) if hasattr(client, '_device_id') and client._device_id else None

                # Fallback: after QR login, do sync and extract profile from client.me
                if not profile_name or not max_user_id:
                    try:
                        ua = _make_user_agent()
                        client._token = token  # ensure token is set
                        await client._sync(ua)
                        if client.me:
                            if not max_user_id:
                                max_user_id = client.me.id
                            if not profile_phone.lstrip("+"):
                                profile_phone = "+" + str(client.me.phone) if client.me.phone else profile_phone
                            if not profile_name and client.me.names:
                                n = client.me.names[0]
                                profile_name = f"{n.first_name or ''} {n.last_name or ''}".strip()
                    except Exception as _e:
                        logger.warning("[qr] post-login sync failed: {}", _e)

                # Сохраняем в БД
                await self._save_account(
                    phone=profile_phone,
                    login_token=token,
                    device_id=device_id_str,
                    profile_name=profile_name,
                    max_user_id=max_user_id,
                    proxy=state.get("proxy"),
                )

                # Сохраняем клиент как активный
                self._clients[profile_phone] = client

                # Убираем из pending
                _qr_sessions.pop(phone, None)

                logger.info("[qr] SUCCESS {} ({})", profile_phone, profile_name)
                return {
                    "status": "confirmed",
                    "profile": {
                        "phone": profile_phone,
                        "name": profile_name,
                        "user_id": max_user_id,
                    },
                }

            return {"status": "waiting"}

        except Exception as e:
            logger.exception("[qr] poll error for {}: {}", phone, e)
            return {"status": "error", "error": str(e)[:200]}

    async def cancel_qr_login(self, phone: str) -> None:
        """Отменяет активный QR login flow."""
        state = _qr_sessions.pop(phone, None)
        if state and state.get("client"):
            try:
                client = state["client"]
                if client._ws:
                    await client._ws.close()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    #  TOKEN IMPORT (для купленных аккаунтов)
    # ─────────────────────────────────────────────────────────────

    async def add_by_token(
        self,
        phone: str,
        login_token: str,
        device_id: str | None = None,
        proxy: str | None = None,
        app_version: str = MIN_APP_VERSION,
        owner_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Импортирует аккаунт по готовому токену (куплен на marketplace).

        :param phone: телефон
        :param login_token: PyMax auth token (JWT)
        :param device_id: UUID устройства (из session продавца)
        :param proxy: прокси для этого аккаунта
        :param app_version: версия клиента
        :param owner_id: id владельца (MaxSurge юзера)
        """
        if not device_id:
            # Генерим новый device_id — может работать, но есть риск что token привязан
            device_id = str(uuid.uuid4())
            logger.warning("add_by_token: device_id не указан, сгенерирован новый {}", device_id)

        # Создаём клиент с импортированными credentials
        client = _make_client(
            phone=phone,
            proxy=proxy,
            token=login_token,
            device_id=device_id,
            app_version=app_version,
        )

        # Подключаемся и делаем sync для валидации токена
        try:
            ua = _make_user_agent(app_version)
            await client.connect(user_agent=ua)
            await client._sync(ua)

            me = client.me
            profile_name = f"{me.first_name or ''} {me.last_name or ''}".strip() if me else phone
            max_user_id = me.id if me else None
            logger.info("[token_import] valid token for {} ({})", phone, profile_name)
        except Exception as e:
            try:
                if client._ws:
                    await client._ws.close()
            except Exception:
                pass
            raise ValueError(f"Token validation failed: {str(e)[:200]}")

        # Сохраняем
        await self._save_account(
            phone=phone,
            login_token=login_token,
            device_id=device_id,
            profile_name=profile_name,
            max_user_id=max_user_id,
            proxy=proxy,
            owner_id=owner_id,
            app_version=app_version,
        )
        self._clients[phone] = client

        return {
            "phone": phone,
            "profile_name": profile_name,
            "max_user_id": max_user_id,
        }

    # ─────────────────────────────────────────────────────────────
    #  SESSION FILE IMPORT (.db файл от Max Sheiker / PyMax)
    # ─────────────────────────────────────────────────────────────

    async def add_by_session_file(
        self,
        phone: str,
        session_db_bytes: bytes,
        proxy: str | None = None,
        owner_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Импортирует аккаунт из готового session.db файла.
        Парсит файл, извлекает token+device_id, валидирует и сохраняет.
        """
        import tempfile
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(session_db_bytes)
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            row = conn.execute("SELECT token, device_id FROM auth LIMIT 1").fetchone()
            conn.close()
            if not row or not row[0]:
                raise ValueError("Session file doesn't contain auth token")
            login_token, device_id = row[0], str(row[1]) if row[1] else None
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        return await self.add_by_token(
            phone=phone,
            login_token=login_token,
            device_id=device_id,
            proxy=proxy,
            owner_id=owner_id,
        )

    # ─────────────────────────────────────────────────────────────
    #  SAVE / RESTORE
    # ─────────────────────────────────────────────────────────────

    async def _save_account(
        self,
        phone: str,
        login_token: str,
        device_id: str | None,
        profile_name: str | None,
        max_user_id: int | None,
        proxy: str | None = None,
        owner_id: int | None = None,
        app_version: str = MIN_APP_VERSION,
    ):
        async with async_session_factory() as session:
            existing = (await session.execute(
                select(MaxAccount).where(MaxAccount.phone == phone)
            )).scalar_one_or_none()

            if existing:
                existing.login_token = login_token
                existing.device_id = device_id
                existing.profile_name = profile_name
                existing.max_user_id = max_user_id
                existing.status = AccountStatus.ACTIVE
                existing.app_version = app_version
                if proxy is not None:
                    existing.proxy = proxy
                if owner_id is not None:
                    existing.owner_id = owner_id
            else:
                acc = MaxAccount(
                    phone=phone,
                    login_token=login_token,
                    device_id=device_id,
                    profile_name=profile_name,
                    max_user_id=max_user_id,
                    status=AccountStatus.ACTIVE,
                    proxy=proxy,
                    owner_id=owner_id,
                    app_version=app_version,
                )
                session.add(acc)
            await session.commit()

    async def restore_session(self, phone: str) -> MaxClient | None:
        """Восстанавливает клиент из БД записи."""
        import time as _t
        if phone in self._clients:
            return self._clients[phone]

        # Check rate limit cooldown
        until = _flood_cooldown.get(phone, 0)
        if until and _t.time() < until:
            logger.debug("[restore] {} in cooldown for {}s more", phone, int(until - _t.time()))
            return None

        async with async_session_factory() as session:
            acc = (await session.execute(
                select(MaxAccount).where(MaxAccount.phone == phone)
            )).scalar_one_or_none()

        if not acc or not acc.login_token:
            return None

        try:
            client = _make_client(
                phone=phone,
                proxy=acc.proxy,
                token=acc.login_token,
                device_id=acc.device_id,
                app_version=acc.app_version or MIN_APP_VERSION,
            )
            ua = _make_user_agent(acc.app_version or MIN_APP_VERSION)
            await client.connect(user_agent=ua)
            await client._sync(ua)
            # CRITICAL: start keepalive + scheduled tasks so WS stays open
            await client._post_login_tasks(sync=False)
            self._clients[phone] = client
            _flood_cooldown.pop(phone, None)
            logger.info("[restore] {} OK (keepalive started)", phone)
            return client
        except Exception as e:
            err = str(e)[:200]
            logger.warning("[restore] {} FAILED: {}", phone, err)
            # Rate limit from MAX — cooldown to avoid hammering
            if "login.flood" in err or "rate limit" in err.lower():
                _flood_cooldown[phone] = _t.time() + FLOOD_COOLDOWN_SEC
                logger.warning("[restore] {} entering {}m cooldown", phone, FLOOD_COOLDOWN_SEC // 60)
            return None

    async def get_client(self, phone: str) -> MaxClient | None:
        # Return cached client if connected, else reconnect
        if phone in self._clients:
            client = self._clients[phone]
            # Check if WebSocket is still alive
            try:
                if client._ws and not getattr(client._ws, "closed", False) and getattr(client, "is_connected", True):
                    return client
            except Exception:
                pass
            # WS dead — drop cache and restore
            logger.info("[get_client] WS dead for {}, reconnecting", phone)
            try:
                if client._ws:
                    await client._ws.close()
            except Exception:
                pass
            del self._clients[phone]
        return await self.restore_session(phone)

    async def get_all_active_clients(self) -> list[tuple[MaxAccount, MaxClient]]:
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
            try:
                client = self._clients[phone]
                if client._ws:
                    await client._ws.close()
            except Exception:
                pass
            del self._clients[phone]

    async def delete_account(self, account_id: int):
        async with async_session_factory() as session:
            acc = await session.get(MaxAccount, account_id)
            if acc:
                phone = acc.phone
                if phone in self._clients:
                    try:
                        client = self._clients[phone]
                        if client._ws:
                            await client._ws.close()
                    except Exception:
                        pass
                    del self._clients[phone]
                # Удалить work_dir для чистоты
                work_dir = _get_work_dir(phone)
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                except Exception:
                    pass
                await session.delete(acc)
                await session.commit()

    async def disconnect_all(self):
        """Закрыть все активные клиенты (для graceful shutdown)."""
        for phone, client in list(self._clients.items()):
            try:
                if client._ws:
                    await client._ws.close()
            except Exception:
                pass
        self._clients.clear()

    async def restore_all(self):
        """Восстановить все активные сессии при старте приложения."""
        async with async_session_factory() as session:
            accounts = (await session.execute(
                select(MaxAccount).where(
                    MaxAccount.status == AccountStatus.ACTIVE,
                    MaxAccount.login_token.isnot(None),
                )
            )).scalars().all()

        count = 0
        for acc in accounts:
            client = await self.restore_session(acc.phone)
            if client:
                count += 1
        logger.info("Восстановлено {}/{} MAX сессий", count, len(accounts))

    # ─────────────────────────────────────────────────────────────
    #  LEGACY SMS methods (DEPRECATED — MAX отключил phone-auth)
    # ─────────────────────────────────────────────────────────────

    async def request_sms(self, phone: str) -> str:
        """DEPRECATED — MAX закрыл phone-auth (25.6.8+). Используйте start_qr_login."""
        raise NotImplementedError(
            "MAX отключил авторизацию по SMS. Используйте QR login или импорт по токену. "
            "См. /app/accounts → 'Добавить аккаунт' → QR или Token."
        )

    async def verify_sms(self, phone: str, sms_code: str) -> dict:
        """DEPRECATED — MAX закрыл phone-auth."""
        raise NotImplementedError(
            "MAX отключил авторизацию по SMS. Используйте QR login или импорт по токену."
        )


# Глобальный синглтон
account_manager = MaxAccountManager()
