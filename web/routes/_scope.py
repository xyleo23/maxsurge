"""Хелперы для авторизации и изоляции данных по пользователю."""
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_request_user(request: Request):
    """Получить текущего пользователя из request.state (установлено AuthMiddleware)."""
    return getattr(request.state, "user", None)


def scope_query(query, model, user):
    """
    Применить фильтр по владельцу.
    - Суперадмин видит всё
    - Обычный пользователь — только свои записи
    """
    if user is None:
        # Нет юзера — ничего не показываем
        return query.where(model.owner_id == -1)
    if getattr(user, "is_superadmin", False):
        return query
    return query.where(model.owner_id == user.id)


async def count_user_rows(session: AsyncSession, model, user_id: int) -> int:
    """Посчитать количество записей, принадлежащих пользователю."""
    result = await session.execute(
        select(func.count(model.id)).where(model.owner_id == user_id)
    )
    return result.scalar() or 0
