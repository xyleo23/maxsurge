"""Модели для email-онбординга.

Живут в отдельном файле (а не в db/models.py), чтобы не мешать параллельной
разработке основных моделей. Импорт этого модуля регистрирует классы в Base.metadata,
поэтому init_db() автоматически создаст таблицы при старте.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.models import Base


class EmailLog(Base):
    """Лог отправленных писем — для идемпотентности (не слать повторно)."""
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)
    email_type: Mapped[str] = mapped_column(String(64), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailPreferences(Base):
    """Настройки рассылок пользователя (отписка и т.д.)."""
    __tablename__ = "email_preferences"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), primary_key=True)
    unsubscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
