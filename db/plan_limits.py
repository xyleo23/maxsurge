"""Лимиты по тарифам пользователей."""
from db.models import UserPlan


# Лимиты на каждый план
PLAN_LIMITS: dict[UserPlan, dict] = {
    UserPlan.TRIAL: {
        "max_accounts": 2,
        "max_tasks": 3,
        "max_leads": 500,
        "max_templates": 5,
        "max_files": 10,
        "broadcasts_per_day": 100,
        "parsing_enabled": True,
        "ai_enabled": True,
        "forwarder_enabled": False,
        "analytics_enabled": True,
    },
    UserPlan.START: {
        "max_accounts": 5,
        "max_tasks": 5,
        "max_leads": 2000,
        "max_templates": 20,
        "max_files": 50,
        "broadcasts_per_day": 500,
        "parsing_enabled": True,
        "ai_enabled": True,
        "forwarder_enabled": False,
        "analytics_enabled": True,
    },
    UserPlan.BASIC: {
        "max_accounts": 15,
        "max_tasks": 10,
        "max_leads": 10000,
        "max_templates": 50,
        "max_files": 200,
        "broadcasts_per_day": 2000,
        "parsing_enabled": True,
        "ai_enabled": True,
        "forwarder_enabled": True,
        "analytics_enabled": True,
    },
    UserPlan.PRO: {
        "max_accounts": 50,
        "max_tasks": 25,
        "max_leads": 100000,
        "max_templates": 200,
        "max_files": 1000,
        "broadcasts_per_day": 10000,
        "parsing_enabled": True,
        "ai_enabled": True,
        "forwarder_enabled": True,
        "analytics_enabled": True,
    },
    UserPlan.LIFETIME: {
        "max_accounts": 999999,
        "max_tasks": 999999,
        "max_leads": 999999,
        "max_templates": 999999,
        "max_files": 999999,
        "broadcasts_per_day": 999999,
        "parsing_enabled": True,
        "ai_enabled": True,
        "forwarder_enabled": True,
        "analytics_enabled": True,
    },
}


def get_limits(plan: UserPlan) -> dict:
    """Получить лимиты для тарифа."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS[UserPlan.TRIAL])


def get_limit(plan: UserPlan, key: str, default=0):
    return get_limits(plan).get(key, default)


def is_superadmin(user) -> bool:
    return user is not None and getattr(user, "is_superadmin", False)


async def check_limit(session, user, model, limit_key: str) -> tuple[bool, int, int]:
    """
    Проверить можно ли создать новую запись.
    Возвращает (can_create, current_count, limit).
    Суперадмин — без лимитов.
    """
    if is_superadmin(user):
        return True, 0, 999999

    from sqlalchemy import func, select
    result = await session.execute(
        select(func.count(model.id)).where(model.owner_id == user.id)
    )
    current = result.scalar() or 0
    limit = get_limit(user.plan, limit_key)
    return current < limit, current, limit


def feature_enabled(user, feature_key: str) -> bool:
    """Проверить доступна ли фича для тарифа."""
    if is_superadmin(user):
        return True
    if not user:
        return False
    return bool(get_limit(user.plan, feature_key, False))
