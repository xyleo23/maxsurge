"""Prodamus payment gateway — HMAC-SHA256 signed URLs + webhook.

Docs: https://help.prodamus.ru/payform/integracii/rest-api

Flow:
1. create_payment_url(amount, order_id, description, email) → redirect
2. Prodamus hosts payment page
3. Webhook POST to our /webhook-pd → verify_signature()
4. User returns to SuccessURL / FailURL
"""
import hashlib
import hmac
import urllib.parse
from dataclasses import dataclass

from loguru import logger

from config import get_settings

settings = get_settings()


@dataclass
class ProdamusConfig:
    shop: str              # subdomain, e.g. "maxsurge"
    secret_key: str        # HMAC key
    is_test: bool = True

    @classmethod
    def from_settings(cls) -> "ProdamusConfig":
        return cls(
            shop=getattr(settings, "PD_SHOP", "") or "",
            secret_key=getattr(settings, "PD_SECRET_KEY", "") or "",
            is_test=str(getattr(settings, "PD_IS_TEST", "1")) == "1",
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.shop and self.secret_key)

    @property
    def base_url(self) -> str:
        return f"https://{self.shop}.payform.ru/"


def _flatten(params: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested dict/list to list of (key, value) for signing."""
    out: list[tuple[str, str]] = []
    for k, v in params.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            out.extend(_flatten(v, key))
        elif isinstance(v, list):
            for i, item in enumerate(v):
                sub_key = f"{key}[{i}]"
                if isinstance(item, dict):
                    out.extend(_flatten(item, sub_key))
                else:
                    out.append((sub_key, str(item)))
        else:
            out.append((key, "" if v is None else str(v)))
    return out


def _sign(params: dict, secret: str) -> str:
    """HMAC-SHA256 signature over sorted flattened params (Prodamus spec)."""
    flat = _flatten(params)
    flat.sort(key=lambda p: p[0])
    payload = "&".join(f"{k}={v}" for k, v in flat)
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_payment_url(
    amount: float,
    order_id: int,
    description: str,
    email: str | None = None,
    phone: str | None = None,
    success_url: str | None = None,
    fail_url: str | None = None,
) -> str:
    """Build signed payment URL for Prodamus redirect."""
    cfg = ProdamusConfig.from_settings()
    if not cfg.is_configured:
        raise ValueError("Prodamus не настроена (PD_SHOP/PD_SECRET_KEY)")

    params: dict = {
        "order_id": str(order_id),
        "customer_extra": description[:100],
        "do": "pay",
        "urlReturn": success_url or "https://maxsurge.ru/app/billing/success-pd",
        "urlSuccess": success_url or "https://maxsurge.ru/app/billing/success-pd",
        "urlNotification": "https://maxsurge.ru/app/billing/webhook-pd",
        "sys": "maxsurge",
        "products": [{
            "name": description[:128],
            "price": f"{amount:.2f}",
            "quantity": "1",
            "tax": {
                "tax_type": 0,         # без НДС (УСН/НПД)
                "payment_method": 4,    # полный расчёт
                "payment_object": 4,    # услуга
            },
        }],
    }
    if email:
        params["customer_email"] = email
    if phone:
        params["customer_phone"] = phone
    if cfg.is_test:
        params["demo_mode"] = "1"

    params["signature"] = _sign(params, cfg.secret_key)

    flat = _flatten(params)
    return cfg.base_url + "?" + urllib.parse.urlencode(flat)


def verify_signature(form_data: dict, signature: str) -> bool:
    """Verify webhook signature. form_data = all POST fields EXCEPT signature."""
    cfg = ProdamusConfig.from_settings()
    if not cfg.is_configured:
        logger.warning("Prodamus not configured, cannot verify")
        return False
    data = {k: v for k, v in form_data.items() if k != "signature"}
    expected = _sign(data, cfg.secret_key)
    return hmac.compare_digest(expected.lower(), (signature or "").lower())
