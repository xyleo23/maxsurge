"""Конфигурация max_leadfinder."""
import json
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite+aiosqlite:///./max_leadfinder.db"

    # 2GIS
    DGIS_CITIES: str = "Москва"
    DGIS_QUERIES: str = "салон красоты,кафе,автосервис"
    DGIS_MAX_PAGES: int = 5
    DGIS_SCRAPE_DELAY_MIN: float = 2.0
    DGIS_SCRAPE_DELAY_MAX: float = 5.0

    # Рассылка
    SEND_DELAY_SEC: float = 15.0
    SEND_MAX_PER_ACCOUNT_DAY: int = 30

    # Веб-панель
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8090
    SECRET_KEY: str = "change-me-in-production"
    TG_API_ID: int = 0
    TG_API_HASH: str = ""
    ADMIN_EMAIL: str = "admin@maxsurge.ru"
    ADMIN_PASSWORD: str = "admin123"
    AI_API_URL: str = "https://api.openai.com/v1"
    AI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"
    YK_SHOP_ID: str = ""
    YK_SECRET_KEY: str = ""
    # Robokassa
    RB_MERCHANT_LOGIN: str = ""
    RB_PASSWORD_1: str = ""
    RB_PASSWORD_2: str = ""
    RB_IS_TEST: str = "1"  # "1" test mode, "0" production
    # Payment method preference: "yookassa" | "robokassa" | "both"
    PAYMENT_GATEWAY: str = "both"
    YK_RETURN_URL: str = "https://maxsurge.ru/app/billing/success"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "MaxSurge"
    SCRAPER_PROXY: str = ""
    OWNER_TG_BOT_TOKEN: str = ""
    OWNER_TG_CHAT_ID: str = ""

    @property
    def cities_list(self) -> list[str]:
        return [c.strip() for c in self.DGIS_CITIES.split(",") if c.strip()]

    @property
    def queries_list(self) -> list[str]:
        return [q.strip() for q in self.DGIS_QUERIES.split(",") if q.strip()]


def get_settings() -> Settings:
    return Settings()
