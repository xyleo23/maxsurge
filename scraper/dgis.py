"""2GIS Playwright scraper v2 — с извлечением телефонов, сайтов, TG."""
import asyncio
import json
import random
import re
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from loguru import logger
from playwright.async_api import async_playwright, Page

from config import get_settings

settings = get_settings()

CITY_SLUGS: dict[str, str] = {
    "москва": "moscow", "мск": "moscow",
    "санкт-петербург": "spb", "спб": "spb", "питер": "spb",
    "екатеринбург": "ekaterinburg",
    "казань": "kazan", "нижний новгород": "nnovgorod",
    "новосибирск": "novosibirsk", "самара": "samara",
    "ростов-на-дону": "rostov", "краснодар": "krasnodar",
    "воронеж": "voronezh", "уфа": "ufa", "пермь": "perm",
    "красноярск": "krasnoyarsk", "тюмень": "tyumen",
    "владивосток": "vladivostok", "барнаул": "barnaul",
    "челябинск": "chelyabinsk", "омск": "omsk",
    "волгоград": "volgograd", "тольятти": "tolyatti",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def _get_city_slug(city: str) -> str:
    return CITY_SLUGS.get(city.lower().strip(), city.lower().replace(" ", "_"))


def _clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith(("7", "8")):
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return None


async def _fetch_firm_details(page: Page, firm_url: str, item: dict) -> dict:
    """Зайти на страницу фирмы, собрать телефон, сайт, TG, VK."""
    contacts: dict[str, list[str]] = {"phones": [], "telegram": [], "vk": [], "websites": []}
    try:
        if not await _goto_with_retry(page, firm_url, timeout=30000):
            return item
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Телефоны
        tel_links = await page.locator('a[href^="tel:"]').all()
        for tel in tel_links:
            href = await tel.get_attribute("href")
            if href:
                ph = _clean_phone(href.replace("tel:", ""))
                if ph and ph not in contacts["phones"]:
                    contacts["phones"].append(ph)

        if contacts["phones"]:
            item["phone"] = contacts["phones"][0]

        # Кнопка "Показать телефон"
        if not contacts["phones"]:
            show_btns = await page.locator("text=Показать").all()
            for btn in show_btns[:1]:
                try:
                    await btn.click()
                    await asyncio.sleep(1.5)
                    tel_links2 = await page.locator('a[href^="tel:"]').all()
                    for tel in tel_links2:
                        href = await tel.get_attribute("href")
                        if href:
                            ph = _clean_phone(href.replace("tel:", ""))
                            if ph:
                                contacts["phones"].append(ph)
                                item["phone"] = ph
                                break
                except Exception:
                    pass

        # Адрес - обновить если нет
        if not item.get("address"):
            addr_sels = ['[class*="address"]', 'a[href*="/geo/"]', '[itemprop="address"]']
            for sel in addr_sels:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text()
                    if text and len(text) > 5:
                        item["address"] = text.strip()[:256]
                        break

        # Ссылки: TG, VK, сайты
        seen: set[str] = set()
        for link in await page.locator('a[href^="http"]').all():
            href = await link.get_attribute("href")
            if not href or href in seen:
                continue
            seen.add(href)
            hl = href.lower()
            if "t.me" in hl or "telegram.me" in hl:
                contacts["telegram"].append(href[:256])
            elif "vk.com" in hl:
                contacts["vk"].append(href[:256])
            elif "2gis" not in hl and "yandex" not in hl and "google" not in hl:
                contacts["websites"].append(href[:256])

        if contacts["websites"] and not item.get("website"):
            item["website"] = contacts["websites"][0]

        # raw_data
        raw = json.loads(item.get("raw_data") or "{}")
        raw["contacts"] = {k: v for k, v in contacts.items() if v}
        raw["url"] = firm_url
        item["raw_data"] = json.dumps(raw, ensure_ascii=False)[:4000]

    except Exception as e:
        logger.debug("Ошибка деталей {}: {}", firm_url, e)
    return item




def _parse_proxy(proxy_url: str | None) -> dict | None:
    """Преобразует URL прокси в формат Playwright."""
    if not proxy_url:
        return None
    try:
        parsed = urlparse(proxy_url.strip())
        if not parsed.hostname:
            return None
        server = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            server += f":{parsed.port}"
        cfg = {"server": server}
        if parsed.username:
            cfg["username"] = parsed.username
        if parsed.password:
            cfg["password"] = parsed.password
        return cfg
    except Exception:
        return None



async def _goto_with_retry(page, url: str, timeout: int = 60000, max_retries: int = 3) -> bool:
    """page.goto с автоматическим retry при сетевых ошибках."""
    for attempt in range(1, max_retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as e:
            err = str(e)
            if attempt >= max_retries:
                logger.warning("2GIS: goto failed after {} retries: {}", max_retries, err[:100])
                return False
            backoff = 2 ** attempt
            logger.info("2GIS: goto attempt {}/{} failed, retrying in {}s: {}", attempt, max_retries, backoff, err[:80])
            await asyncio.sleep(backoff)
    return False

async def scrape_city_query(city: str, query: str, max_pages: int = 5, fetch_details: bool = True, proxy: str | None = None) -> list[dict]:
    """Собирает лиды из 2GIS + заходит на страницу фирмы для телефонов."""
    slug = _get_city_slug(city)
    query_encoded = quote(query, safe="")
    all_items: list[dict] = []

    proxy_cfg = _parse_proxy(proxy or getattr(settings, "SCRAPER_PROXY", None))
    launch_kwargs = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
    }
    if proxy_cfg:
        launch_kwargs["proxy"] = proxy_cfg
        logger.info("2GIS: используется прокси {}", proxy_cfg.get("server"))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="ru-RU",
            viewport={"width": 1920, "height": 1080},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
        )
        page = await context.new_page()

        try:
            for page_num in range(1, max_pages + 1):
                if page_num == 1:
                    url = f"https://2gis.ru/{slug}/search/{query_encoded}"
                else:
                    url = f"https://2gis.ru/{slug}/search/{query_encoded}/page/{page_num}"

                logger.info("2GIS: {} стр.{}", f"{city}/{query}", page_num)
                if not await _goto_with_retry(page, url, timeout=60000):
                    break
                await asyncio.sleep(random.uniform(2.0, 4.0))

                firm_links = await page.locator('a[href*="/firm/"]').all()
                if not firm_links:
                    break

                seen_ids: set[str] = {item["dgis_id"] for item in all_items}
                page_items = 0

                for link in firm_links:
                    try:
                        href = await link.get_attribute("href")
                        if not href:
                            continue
                        m = re.search(r"/firm/(\d+)", href)
                        if not m:
                            continue
                        firm_id = m.group(1)
                        if firm_id in seen_ids:
                            continue
                        seen_ids.add(firm_id)

                        name = (await link.inner_text()).strip()
                        if not name or len(name) < 2:
                            continue

                        full_url = urljoin(url, href) if not href.startswith("http") else href

                        address = None
                        try:
                            for level in range(2, 6):
                                parent = link.locator(f"xpath=./ancestor::*[{level}]").first
                                if await parent.count() > 0:
                                    card_text = await parent.inner_text()
                                    if card_text and len(card_text) > 20:
                                        addr_match = re.search(
                                            r"(?:[^,\n]*(?:улица|ул\.|пр\.|проспект|переулок|бульвар|шоссе|набережная)[^,\n]*,\s*\d+[^,\n]*)",
                                            card_text, re.I,
                                        )
                                        if addr_match:
                                            address = addr_match.group(0).strip()[:256]
                                            break
                        except Exception:
                            pass

                        all_items.append({
                            "name": name,
                            "address": address,
                            "city": city,
                            "phone": "",
                            "website": "",
                            "categories": query,
                            "source_query": f"{city} | {query}",
                            "dgis_id": firm_id,
                            "raw_data": json.dumps({"url": full_url}),
                            "_firm_url": full_url,
                        })
                        page_items += 1
                    except Exception as e:
                        logger.debug("Ошибка карточки: {}", e)

                logger.info("2GIS: стр.{} - {} фирм", page_num, page_items)
                if page_items == 0:
                    break
                await asyncio.sleep(random.uniform(settings.DGIS_SCRAPE_DELAY_MIN, settings.DGIS_SCRAPE_DELAY_MAX))

            # Фаза 2: заходим на страницу каждой фирмы за телефоном
            if fetch_details:
                logger.info("2GIS: извлекаю детали для {} фирм...", len(all_items))
                for i, item in enumerate(all_items):
                    firm_url = item.pop("_firm_url", "")
                    if not firm_url:
                        continue
                    await _fetch_firm_details(page, firm_url, item)
                    if item.get("phone"):
                        logger.debug("  [{}] {} -> {}", i + 1, item["name"][:30], item["phone"])
                    await asyncio.sleep(random.uniform(1.0, 2.5))
            else:
                for item in all_items:
                    item.pop("_firm_url", None)

        except Exception as e:
            logger.error("Ошибка скрапинга {}/{}: {}", city, query, e)
        finally:
            await context.close()
            await browser.close()

    phones_found = sum(1 for i in all_items if i.get("phone"))
    logger.info("2GIS {}/{}: {} лидов, {} с телефоном", city, query, len(all_items), phones_found)
    return all_items


async def run_scrape(cities: list[str] | None = None, queries: list[str] | None = None,
                     fetch_details: bool = True, proxy: str | None = None) -> list[dict]:
    cities = cities or settings.cities_list
    queries = queries or settings.queries_list
    all_results = []
    for city in cities:
        for query in queries:
            leads = await scrape_city_query(city, query, settings.DGIS_MAX_PAGES, fetch_details, proxy)
            all_results.extend(leads)
            await asyncio.sleep(2)
    return all_results
