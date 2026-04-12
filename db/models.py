"""Модели SQLAlchemy — v2.0 (полный набор)."""
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, Float, Enum as SQLEnum, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import get_settings

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ── Enums ──────────────────────────────────────────────
class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    IN_PROGRESS = "in_progress"
    WON = "won"
    LOST = "lost"
    SKIPPED = "skipped"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    WARMING = "warming"
    PENDING_AUTH = "pending_auth"


# ── Лиды ──────────────────────────────────────────────
class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512))
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    city: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    categories: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_query: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dgis_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, unique=True)
    max_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    max_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[LeadStatus] = mapped_column(SQLEnum(LeadStatus), default=LeadStatus.NEW, index=True)
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Аккаунты MAX ──────────────────────────────────────
class MaxAccount(Base):
    __tablename__ = "max_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    login_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    sms_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    max_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[AccountStatus] = mapped_column(SQLEnum(AccountStatus), default=AccountStatus.PENDING_AUTH)
    proxy: Mapped[str | None] = mapped_column(String(256), nullable=True)  # http://user:pass@host:port
    sent_today: Mapped[int] = mapped_column(Integer, default=0)
    sent_total: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Шаблоны ────────────────────────────────────────────
class TemplateStatus(str, Enum):
    PENDING = "pending"          # ждёт AI-проверку
    AI_REVIEWED = "ai_reviewed"  # AI проверил, ждёт ручное подтверждение если флаг
    APPROVED = "approved"        # готово к рассылке
    REJECTED = "rejected"        # запрещено
    DRAFT = "draft"              # черновик, не отправлялся


class MessageTemplate(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)   # поддерживает {name}, {city}, спинтакс {A|B|C}
    attachment_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status: Mapped[TemplateStatus] = mapped_column(SQLEnum(TemplateStatus), default=TemplateStatus.PENDING)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    public_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    copies_count: Mapped[int] = mapped_column(Integer, default=0)


# ── Лог отправок ────────────────────────────────────────
class SendLog(Base):
    __tablename__ = "send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("max_accounts.id"), index=True)
    template_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("templates.id"), nullable=True)
    target_type: Mapped[str] = mapped_column(String(16), default="user")  # user / chat
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # user_id или chat_id
    outgoing_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="sent")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ── Спарсенные пользователи ──────────────────────────────
class ParsedUser(Base):
    __tablename__ = "parsed_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    first_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    source_chat_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Каталог чатов MAX ──────────────────────────────────
class ChatCatalog(Base):
    __tablename__ = "chat_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    invite_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    members_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0)   # сколько раз парсили
    last_parsed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Задачи прогрева ──────────────────────────────────────
class WarmingLog(Base):
    __tablename__ = "warming_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("max_accounts.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))  # join_chat, send_message, read_channel, change_profile
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Задачи (универсальные) ─────────────────────────────
class TaskStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    INVITE = "invite"
    BROADCAST = "broadcast"
    PARSE = "parse"
    WARM = "warm"
    CHECK = "check"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    task_type: Mapped[TaskType] = mapped_column(SQLEnum(TaskType), index=True)
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus), default=TaskStatus.DRAFT, index=True)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON с параметрами
    progress_today: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    target_count: Mapped[int] = mapped_column(Integer, default=0)  # сколько всего целей
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array лога
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    broadcast_config: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Хранилище файлов ────────────────────────────────────
class FileType(str, Enum):
    IDS = "ids"
    PHONES = "phones"
    LINKS = "links"
    OTHER = "other"


class UserFile(Base):
    __tablename__ = "user_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    original_filename: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_type: Mapped[FileType] = mapped_column(SQLEnum(FileType), default=FileType.OTHER, index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    lines_total: Mapped[int] = mapped_column(Integer, default=0)
    lines_used: Mapped[int] = mapped_column(Integer, default=0)
    folder: Mapped[str] = mapped_column(String(128), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Пользователи (авторизация) ────────────────────────
class UserPlan(str, Enum):
    TRIAL = "trial"
    START = "start"
    BASIC = "basic"
    PRO = "pro"
    LIFETIME = "lifetime"


class SiteUser(Base):
    __tablename__ = "site_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    plan: Mapped[UserPlan] = mapped_column(SQLEnum(UserPlan), default=UserPlan.TRIAL)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_days: Mapped[int] = mapped_column(Integer, default=7)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verify_token: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    password_reset_token: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ref_code: Mapped[str | None] = mapped_column(String(16), nullable=True, unique=True, index=True)
    referred_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    ref_balance: Mapped[float] = mapped_column(Float, default=0.0)
    ref_earned_total: Mapped[float] = mapped_column(Float, default=0.0)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_api_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ai_api_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    user_tg_bot_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notify_on_lead: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_payment: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_task_done: Mapped[bool] = mapped_column(Boolean, default=True)
    tg_chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


# ── Платежи ──────────────────────────────────────────
class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"
    WAITING_FOR_CAPTURE = "waiting_for_capture"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)
    yk_payment_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    plan: Mapped[UserPlan] = mapped_column(SQLEnum(UserPlan))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confirmation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ── Реферальные начисления ─────────────────────────
class RefCommission(Base):
    __tablename__ = "ref_commissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)
    referred_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)
    payment_id: Mapped[int] = mapped_column(Integer, ForeignKey("payments.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    percent: Mapped[float] = mapped_column(Float, default=20.0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Нейрочаттинг ─────────────────────────────────────
class NeuroCampaignStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class NeuroMode(str, Enum):
    KEYWORDS = "keywords"           # реагируем на ключевые фразы
    RESPOND_ALL = "respond_all"     # отвечаем на все сообщения
    SCRIPTED = "scripted"           # сценарный диалог (2 бота переписываются)


class NeuroStyle(str, Enum):
    CONVERSATIONAL = "conversational"
    BUSINESS = "business"
    FRIENDLY = "friendly"
    EXPERT = "expert"


class NeuroCampaign(Base):
    __tablename__ = "neuro_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    mode: Mapped[NeuroMode] = mapped_column(SQLEnum(NeuroMode), default=NeuroMode.KEYWORDS)
    status: Mapped[NeuroCampaignStatus] = mapped_column(SQLEnum(NeuroCampaignStatus), default=NeuroCampaignStatus.DRAFT)

    # Аккаунт-бот
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("max_accounts.id"), index=True)

    # Где работает — JSON-массив chat_id или "all"
    chat_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of int

    # Триггеры (для режима KEYWORDS)
    keywords: Mapped[str] = mapped_column(Text, default="")  # comma-separated

    # Поддерживать диалог?
    support_replies: Mapped[bool] = mapped_column(Boolean, default=True)

    # Что продвигаем
    product_description: Mapped[str] = mapped_column(Text, default="")

    # Стиль общения
    style: Mapped[NeuroStyle] = mapped_column(SQLEnum(NeuroStyle), default=NeuroStyle.CONVERSATIONAL)

    # Частота упоминания товара (каждое N-ое сообщение)
    mention_frequency: Mapped[int] = mapped_column(Integer, default=30)

    # AI модель
    ai_model: Mapped[str] = mapped_column(String(128), default="gpt-4o-mini")
    system_prompt: Mapped[str] = mapped_column(Text, default="")

    # Задержки
    delay_min_sec: Mapped[int] = mapped_column(Integer, default=30)
    delay_max_sec: Mapped[int] = mapped_column(Integer, default=120)
    daily_limit: Mapped[int] = mapped_column(Integer, default=50)

    # Счётчики
    messages_sent: Mapped[int] = mapped_column(Integer, default=0)
    messages_today: Mapped[int] = mapped_column(Integer, default=0)
    last_reset_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Owner
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NeuroChatMessage(Base):
    """История отправленных ботом сообщений (для анализа и избежания повторов)."""
    __tablename__ = "neuro_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("neuro_campaigns.id"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    trigger_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_sent: Mapped[str] = mapped_column(Text)
    mentioned_product: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ── MAX Bot API (Лид-боты и Бонус-боты) ──────────────
class MaxBotType(str, Enum):
    LEAD = "lead"      # собирает лиды (имя, телефон, email)
    BONUS = "bonus"    # раздаёт бонусы/промокоды
    SUPPORT = "support" # чат-поддержка с AI


class MaxBot(Base):
    __tablename__ = "max_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    bot_type: Mapped[MaxBotType] = mapped_column(SQLEnum(MaxBotType), default=MaxBotType.LEAD)

    # Токен от @MasterBot / @BotFather в MAX
    token: Mapped[str] = mapped_column(String(512))
    bot_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bot_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Welcome message, шаги диалога (JSON)
    welcome_text: Mapped[str] = mapped_column(Text, default="Привет! Оставьте свой номер телефона, мы перезвоним.")
    # Шаги диалога для LEAD: [{"key":"name","prompt":"Как вас зовут?"},{"key":"phone","prompt":"Ваш телефон?"}]
    steps: Mapped[str] = mapped_column(Text, default='[]')
    finish_text: Mapped[str] = mapped_column(Text, default="Спасибо! Мы свяжемся с вами в ближайшее время.")

    # Для BONUS бота
    bonus_code: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bonus_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bonus_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    bonus_issued: Mapped[int] = mapped_column(Integer, default=0)

    # Для SUPPORT бота
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    knowledge_base: Mapped[str | None] = mapped_column(Text, nullable=True)
    quick_replies: Mapped[str] = mapped_column(Text, default="[]")

    # Уведомления владельцу о новых лидах
    notify_owner_tg: Mapped[bool] = mapped_column(Boolean, default=True)

    # Состояние
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_update_id: Mapped[int] = mapped_column(BigInteger, default=0)

    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MaxBotLead(Base):
    """Собранные лиды от бота."""
    __tablename__ = "max_bot_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(Integer, ForeignKey("max_bots.id"), index=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    max_chat_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Собранные данные (JSON: {"name":"Иван","phone":"+7...","email":"..."})
    data: Mapped[str] = mapped_column(Text, default="{}")

    # Состояние диалога: индекс текущего шага
    dialog_step: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MaxBotBonusClaim(Base):
    """Запросы бонусов — кто получил."""
    __tablename__ = "max_bot_bonus_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(Integer, ForeignKey("max_bots.id"), index=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bonus_code_given: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Страж чата ───────────────────────────────────────
class GuardAction(str, Enum):
    DELETE = "delete"
    WARN = "warn"
    BAN = "ban"


class ChatGuard(Base):
    __tablename__ = "chat_guards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))

    # Аккаунт, от которого работает модерация (должен быть админом в чате)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("max_accounts.id"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)

    # Правила
    delete_links: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_mentions: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_forwards: Mapped[bool] = mapped_column(Boolean, default=False)

    stop_words: Mapped[str] = mapped_column(Text, default="")  # CSV
    stop_words_action: Mapped[GuardAction] = mapped_column(SQLEnum(GuardAction), default=GuardAction.DELETE)

    # Флуд-контроль: max N сообщений за interval_sec секунд
    flood_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = off
    flood_interval_sec: Mapped[int] = mapped_column(Integer, default=10)
    flood_action: Mapped[GuardAction] = mapped_column(SQLEnum(GuardAction), default=GuardAction.DELETE)

    # Whitelist (CSV user_id)
    whitelist_ids: Mapped[str] = mapped_column(Text, default="")

    # AI-модерация токсичности
    ai_moderation: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_toxicity_threshold: Mapped[float] = mapped_column(Float, default=0.8)

    # Приветствие новых участников
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_text: Mapped[str] = mapped_column(Text, default="Добро пожаловать! Ознакомьтесь с правилами чата.")

    # Правила чата (для /rules и welcome)
    rules_text: Mapped[str] = mapped_column(Text, default="")

    # Статистика
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    banned_count: Mapped[int] = mapped_column(Integer, default=0)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GuardEvent(Base):
    """Лог действий модератора."""
    __tablename__ = "guard_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guard_id: Mapped[int] = mapped_column(Integer, ForeignKey("chat_guards.id"), index=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[GuardAction] = mapped_column(SQLEnum(GuardAction))
    reason: Mapped[str] = mapped_column(String(512))
    message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ── Audit log (для superadmin действий) ──────────────
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("site_users.id"), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ── Error log ────────────────────────────────────────
class ErrorLog(Base):
    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ex_type: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    ex_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ── Блэклист ──────────────────────────────────────
class Blacklist(Base):
    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("site_users.id"), index=True)
    value: Mapped[str] = mapped_column(String(128), index=True)
    type: Mapped[str] = mapped_column(String(16), default="phone")  # phone / user_id / email
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
