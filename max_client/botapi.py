"""MAX Bot API — обёртка над https://botapi.max.ru/

Токены выдаёт @MasterBot в MAX (аналог @BotFather в TG).
API совместим по философии с Telegram Bot API: long-polling updates,
send_message, inline keyboards.
"""
import httpx
from loguru import logger

BASE_URL = "https://botapi.max.ru"


class MaxBotAPI:
    def __init__(self, token: str, timeout: float = 35.0):
        self.token = token
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self.client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.token
        try:
            r = await self.client.get(f"{BASE_URL}{path}", params=params)
            return r.json() if r.content else {}
        except Exception as e:
            logger.error("[maxbotapi] GET {} error: {}", path, e)
            return {"error": str(e)}

    async def _post(self, path: str, json_body: dict, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.token
        try:
            r = await self.client.post(f"{BASE_URL}{path}", params=params, json=json_body)
            return r.json() if r.content else {}
        except Exception as e:
            logger.error("[maxbotapi] POST {} error: {}", path, e)
            return {"error": str(e)}

    # ── Методы ──────────────────────────────
    async def get_me(self) -> dict:
        return await self._get("/me")

    async def get_updates(self, marker: int = 0, limit: int = 50, timeout: int = 30) -> dict:
        params = {"limit": limit, "timeout": timeout}
        if marker:
            params["marker"] = marker
        return await self._get("/updates", params)

    async def send_message(
        self,
        chat_id: int | None = None,
        user_id: int | None = None,
        text: str = "",
        keyboard: list[list[dict]] | None = None,
    ) -> dict:
        """Отправка сообщения в чат или приват по user_id."""
        body = {"text": text}
        if keyboard:
            body["attachments"] = [{
                "type": "inline_keyboard",
                "payload": {"buttons": keyboard},
            }]
        params = {}
        if chat_id is not None:
            params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = user_id
        return await self._post("/messages", body, params)

    async def answer_callback(self, callback_id: str, notification: str = "") -> dict:
        body = {"notification": notification}
        return await self._post("/answers", body, {"callback_id": callback_id})
