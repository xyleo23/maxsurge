"""Снимает скриншоты защищённых /app/* страниц.
Запускается на сервере: /root/max_leadfinder/venv/bin/python screenshoter.py
Результат — WebP-файлы в /root/max_leadfinder/web/static/screenshots/
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "/root/max_leadfinder")
from config import get_settings

from playwright.async_api import async_playwright

OUT_DIR = Path("/root/max_leadfinder/web/static/screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Локальный URL (без traefik), чтобы не зависеть от DNS в контексте headless
BASE = "http://127.0.0.1:8090"

# Скрины: (slug, path, label)
PAGES = [
    ("dashboard",    "/app/",             "Главная панель"),
    ("sender",       "/app/sender",       "Создание рассылки"),
    ("scraper",      "/app/scraper",      "Парсинг из карт"),
    ("parser",       "/app/parser",       "Парсинг чатов"),
    ("autoresponder","/app/autoresponder","AI автоответчик"),
    ("analytics",    "/app/analytics",    "Аналитика"),
]

# CSS, который инжектится перед скриншотом: блюрит заведомо чувствительное
SAFE_CSS = """
/* Скрываем/блюрим всё, что может содержать PII клиентов */
[data-sensitive], .pii-hide, .email-cell, .phone-cell, .user-id-cell { filter: blur(6px) !important; }
/* В таблицах с лидами блюрим всё содержимое tbody td */
table.leads-table tbody td, table.accounts-table tbody td { filter: blur(5px) !important; }
/* Прячем верхний баннер с именем/email пользователя если он есть */
.user-menu, .current-user-email { filter: blur(5px) !important; }
"""


async def login(page, email: str, password: str) -> bool:
    await page.goto(BASE + "/login", wait_until="domcontentloaded")
    await page.fill('input[name="email"]', email)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    try:
        await page.wait_for_url("**/app/**", timeout=8000)
    except Exception:
        pass
    url = page.url
    print(f"  post-login url: {url}")
    if "/login-2fa" in url:
        print("!!! 2FA enabled for admin — cannot proceed via Playwright")
        return False
    if "/app/" in url:
        return True
    return False


async def snap(ctx, slug: str, url_path: str):
    page = await ctx.new_page()
    try:
        await page.goto(BASE + url_path, wait_until="networkidle", timeout=20000)
    except Exception as e:
        print(f"  [{slug}] goto soft-fail: {e}")
        await page.wait_for_timeout(1000)
    await page.add_style_tag(content=SAFE_CSS)
    await page.wait_for_timeout(800)

    png = OUT_DIR / f"{slug}.png"
    await page.screenshot(path=str(png), full_page=False)
    print(f"  [{slug}] saved {png.name} ({png.stat().st_size}B)")
    await page.close()


async def main():
    settings = get_settings()
    email = settings.ADMIN_EMAIL
    password = settings.ADMIN_PASSWORD
    if not email or not password:
        print("ADMIN_EMAIL/ADMIN_PASSWORD not set"); return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 860},
            device_scale_factor=2,
            ignore_https_errors=True,
        )
        page = await ctx.new_page()
        ok = await login(page, email, password)
        if not ok:
            print("login failed — aborting")
            await browser.close(); return
        await page.close()

        for slug, path, _label in PAGES:
            await snap(ctx, slug, path)

        await browser.close()

    # Convert PNG -> WebP (smaller, same quality)
    try:
        from PIL import Image
        for slug, *_ in PAGES:
            png = OUT_DIR / f"{slug}.png"
            webp = OUT_DIR / f"{slug}.webp"
            if png.exists():
                im = Image.open(png)
                im.save(webp, "webp", quality=85, method=6)
                print(f"  {slug}.webp {webp.stat().st_size}B (was png {png.stat().st_size}B)")
                png.unlink()
    except ImportError:
        print("Pillow not installed — keeping PNG only")


if __name__ == "__main__":
    asyncio.run(main())
