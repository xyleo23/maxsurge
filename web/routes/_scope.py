"""Хелперы для авторизации и изоляции данных по пользователю."""
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_request_user(request: Request):
    """Получить текущего пользователя из request.state (установлено AuthMiddleware)."""
    return getattr(request.state, "user", None)


def scope_query(query, model, user, admin_sees_all: bool = False):
    """
    Применить фильтр по владельцу.
    - Обычный пользователь — только свои записи
    - Суперадмин:
        * В /app/* — ТОЛЬКО свои (личный кабинет)
        * В /app/admin/* — все записи (передавать admin_sees_all=True)
    """
    if user is None:
        return query.where(model.owner_id == -1)
    if getattr(user, "is_superadmin", False) and admin_sees_all:
        return query
    return query.where(model.owner_id == user.id)


def admin_scope_query(query, model, user):
    """Shortcut for /app/admin/* routes — superadmin sees everything."""
    if user is None or not getattr(user, "is_superadmin", False):
        return query.where(model.owner_id == -1)
    return query


async def count_user_rows(session: AsyncSession, model, user_id: int) -> int:
    """Посчитать количество записей, принадлежащих пользователю."""
    result = await session.execute(
        select(func.count(model.id)).where(model.owner_id == user_id)
    )
    return result.scalar() or 0
