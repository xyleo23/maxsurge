"""Спинтакс — рандомизация текста для уникальности сообщений."""
import random
import re


def process_spintax(text: str) -> str:
    """
    Обрабатывает спинтакс: {вариант1|вариант2|вариант3} → случайный вариант.
    Поддерживает вложенность.

    Примеры:
        "{Привет|Здравствуйте|Добрый день}, {name}!" → "Здравствуйте, {name}!"
        "{Хочу|Могу} {предложить|показать}" → "Могу показать"
    """
    pattern = re.compile(r"\{([^{}]+)\}")

    # Повторяем до тех пор, пока есть спинтакс-конструкции
    max_iterations = 10
    for _ in range(max_iterations):
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split("|")
        replacement = random.choice(options).strip()
        text = text[:match.start()] + replacement + text[match.end():]

    return text


def render_template_with_spintax(body: str, lead=None) -> str:
    """Подставляет плейсхолдеры + спинтакс."""
    text = body
    if lead:
        text = (
            text
            .replace("{name}", getattr(lead, "name", "") or "")
            .replace("{city}", getattr(lead, "city", "") or "")
            .replace("{categories}", getattr(lead, "categories", "") or "")
            .replace("{phone}", getattr(lead, "phone", "") or "")
            .replace("{address}", getattr(lead, "address", "") or "")
        )
    return process_spintax(text)
