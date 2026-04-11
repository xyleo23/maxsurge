"""AI клиент для чат-бота. Использует OpenAI-совместимый API.
Поддерживает per-user API ключи (приоритет над глобальным)."""
import os
from typing import Optional

import httpx
from loguru import logger

from config import get_settings

settings = get_settings()


async def generate_ai_reply(
    user_message: str,
    knowledge_base: str = "",
    history: list[dict] | None = None,
    max_tokens: int = 300,
    # Per-user overrides
    user_api_key: str | None = None,
    user_api_url: str | None = None,
    user_model: str | None = None,
) -> Optional[str]:
    """
    Генерация ответа через OpenAI-совместимый API.
    Если переданы user_api_key/url/model — используются они (приоритет),
    иначе fallback на глобальные из .env.
    """
    # Приоритет: user settings → env → defaults
    api_key = (
        user_api_key
        or getattr(settings, "AI_API_KEY", "")
        or os.getenv("AI_API_KEY", "")
    )
    api_url = (
        user_api_url
        or getattr(settings, "AI_API_URL", "")
        or os.getenv("AI_API_URL", "https://api.openai.com/v1")
    )
    model_name = (
        user_model
        or getattr(settings, "AI_MODEL", "")
        or os.getenv("AI_MODEL", "")
        or "gpt-4o-mini"
    )

    if not api_key:
        logger.warning("AI_API_KEY не установлен, AI автоответ пропускается")
        return None

    system_prompt = (
        "Ты — дружелюбный ассистент службы поддержки. Отвечай кратко (1-3 предложения), по делу, на русском. "
        "Не придумывай информацию, которой нет в базе знаний. "
        "Если вопрос не по теме или требует оператора — предложи связаться с менеджером."
    )
    if knowledge_base:
        system_prompt += f"\n\nБаза знаний:\n{knowledge_base}"

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_message})

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{api_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_name,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            reply = data["choices"][0]["message"]["content"].strip()
            logger.info("AI ответ сгенерирован ({} симв, model={})", len(reply), model_name)
            return reply
    except Exception as e:
        logger.error("Ошибка AI API: {}", e)
        return None
