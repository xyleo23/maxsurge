"""AI-модерация шаблонов рассылки.

Защищает от банов аккаунтов за нарушающий контент. Работает в два этапа:
1. AI-проверка (автоматически при создании): возвращает score 0.0-1.0 и feedback
   - score < 0.3 → APPROVED (безопасно)
   - score 0.3-0.7 → AI_REVIEWED (на ручную модерацию админом)
   - score >= 0.7 → REJECTED (явное нарушение)
2. Админ может override статус вручную через /app/admin/templates
"""
from datetime import datetime
from loguru import logger
from sqlalchemy import select

from db.models import (
    MessageTemplate, TemplateStatus, SiteUser, async_session_factory,
)
from max_client.ai_client import generate_ai_reply


SYSTEM_PROMPT = """Ты — модератор сервиса рассылок. Оцени шаблон сообщения
для массовой отправки в мессенджере. Определи:
1. Есть ли прямая реклама запрещённых товаров (казино, ставки, крипта, лекарства без рецепта, оружие, наркотики)?
2. Есть ли мошеннический контент (фишинг, скам, обещания лёгких денег)?
3. Есть ли агрессивный спам / многократные повторы?
4. Есть ли нарушения этики (оскорбления, дискриминация)?

Верни ТОЛЬКО JSON без пояснений:
{"score": 0.0-1.0, "reason": "короткое объяснение на русском", "fix": "что исправить"}

где score:
- 0.0-0.3 = чистый деловой текст, можно отправлять
- 0.3-0.7 = есть сомнительные моменты, требуется ручная проверка
- 0.7-1.0 = явное нарушение, отклонить"""


async def ai_review_template(template_id: int) -> dict:
    """Запустить AI-проверку шаблона. Обновляет статус/ai_score/ai_feedback."""
    async with async_session_factory() as s:
        tmpl = await s.get(MessageTemplate, template_id)
        if not tmpl:
            return {"error": "not found"}

        # AI ключи от владельца шаблона
        user = await s.get(SiteUser, tmpl.owner_id) if tmpl.owner_id else None
        user_keys = {
            "user_api_key": user.ai_api_key if user else None,
            "user_api_url": user.ai_api_url if user else None,
            "user_model": user.ai_model if user else None,
        }

    response = await generate_ai_reply(
        user_message=f"Шаблон для проверки:\n\n{tmpl.body}",
        knowledge_base=SYSTEM_PROMPT,
        max_tokens=200,
        **user_keys,
    )

    score = 0.0
    reason = "AI недоступен — отправлено на ручную модерацию"
    fix = ""

    if response:
        try:
            import json, re
            # Ищем JSON в ответе
            m = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                score = float(data.get("score", 0.5))
                reason = data.get("reason", "")[:500]
                fix = data.get("fix", "")[:500]
        except Exception as e:
            logger.warning("[template_mod] parse error: {} — raw: {}", e, response[:200])

    # Определяем статус
    if not response:
        new_status = TemplateStatus.AI_REVIEWED  # ручная модерация
    elif score < 0.3:
        new_status = TemplateStatus.APPROVED
    elif score >= 0.7:
        new_status = TemplateStatus.REJECTED
    else:
        new_status = TemplateStatus.AI_REVIEWED

    async with async_session_factory() as s:
        tmpl = await s.get(MessageTemplate, template_id)
        if not tmpl:
            return {"error": "not found"}
        tmpl.status = new_status
        tmpl.ai_score = score
        tmpl.ai_feedback = f"{reason}\n\nРекомендация: {fix}" if fix else reason
        tmpl.reviewed_at = datetime.utcnow()
        await s.commit()

    logger.info("[template_mod] #{} score={:.2f} → {}", template_id, score, new_status.value)
    return {
        "status": new_status.value,
        "score": score,
        "reason": reason,
        "fix": fix,
    }


async def admin_approve(template_id: int, admin_note: str = ""):
    async with async_session_factory() as s:
        tmpl = await s.get(MessageTemplate, template_id)
        if not tmpl:
            return False
        tmpl.status = TemplateStatus.APPROVED
        tmpl.admin_feedback = admin_note or "Одобрено администратором"
        tmpl.reviewed_at = datetime.utcnow()
        await s.commit()
    return True


async def admin_reject(template_id: int, admin_note: str = ""):
    async with async_session_factory() as s:
        tmpl = await s.get(MessageTemplate, template_id)
        if not tmpl:
            return False
        tmpl.status = TemplateStatus.REJECTED
        tmpl.admin_feedback = admin_note or "Отклонено администратором"
        tmpl.reviewed_at = datetime.utcnow()
        await s.commit()
    return True
