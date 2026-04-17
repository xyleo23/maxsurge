"""Robokassa payment gateway — интеграция через подписанные URL-параметры.

Docs: https://docs.robokassa.ru/pay-interface/

Flow:
1. create_payment_url(amount, order_id, description) → redirect пользователя
2. Пользователь платит на странице Robokassa
3. Robokassa делает POST на ResultURL (webhook) → verify_result_signature()
4. Пользователь возвращается на SuccessURL / FailURL
"""
import hashlib
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from config import get_settings

settings = get_settings()


@dataclass
class RobokassaConfig:
    """Читает RB_* переменные из .env"""
    merchant_login: str
    password_1: str  # для формирования платежа
    password_2: str  # для проверки webhook
    is_test: bool = True

    @classmethod
    def from_settings(cls) -> "RobokassaConfig":
        return cls(
            merchant_login=getattr(settings, "RB_MERCHANT_LOGIN", "") or "",
            password_1=getattr(settings, "RB_PASSWORD_1", "") or "",
            password_2=getattr(settings, "RB_PASSWORD_2", "") or "",
            is_test=str(getattr(settings, "RB_IS_TEST", "1")) == "1",
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.merchant_login and self.password_1 and self.password_2)


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def create_payment_url(
    amount: float,
    order_id: int,
    description: str,
    email: str | None = None,
    is_test: bool | None = None,
    receipt_items: list[dict] | None = None,
) -> str:
    """
    Generates payment URL for Robokassa redirect.

    :param amount: Rubles (e.g. 1490.00)
    :param order_id: unique MaxSurge Payment.id
    :param description: human-readable description (shown on payment page)
    :param email: user email (for receipt)
    :param is_test: override test mode from config
    :param receipt_items: optional items for fiscal receipt (54-ФЗ)
    :return: URL string to redirect user to
    """
    cfg = RobokassaConfig.from_settings()
    if not cfg.is_configured:
        raise ValueError("Robokassa не настроена (RB_MERCHANT_LOGIN/PASSWORD_1/PASSWORD_2)")

    test_mode = is_test if is_test is not None else cfg.is_test
    amount_str = f"{amount:.2f}"

    # Build signature: MerchantLogin:OutSum:InvId:Password1[:receipt_url_encoded]
    # Then MD5
    sig_parts = [cfg.merchant_login, amount_str, str(order_id)]

    receipt_param = ""
    if receipt_items:
        import json
        receipt_obj = {
            "sno": "usn_income",  # УСН доходы
            "items": receipt_items,
        }
        receipt_json = json.dumps(receipt_obj, ensure_ascii=False, separators=(",", ":"))
        receipt_param = urllib.parse.quote(receipt_json, safe="")
        sig_parts.append("Receipt=" + receipt_param)

    sig_parts.append(cfg.password_1)
    signature = _md5(":".join(sig_parts))

    params = {
        "MerchantLogin": cfg.merchant_login,
        "OutSum": amount_str,
        "InvId": str(order_id),
        "Description": description[:100],
        "SignatureValue": signature,
        "Culture": "ru",
        "Encoding": "utf-8",
    }
    if email:
        params["Email"] = email
    if test_mode:
        params["IsTest"] = "1"
    if receipt_param:
        params["Receipt"] = receipt_param

    base = "https://auth.robokassa.ru/Merchant/Index.aspx"
    return f"{base}?" + urllib.parse.urlencode(params)


def verify_result_signature(
    out_sum: str,
    inv_id: str,
    signature_value: str,
) -> bool:
    """
    Verifies webhook signature from Robokassa ResultURL.

    Robokassa sends: OutSum, InvId, SignatureValue (uppercase MD5)
    Expected MD5 format: OutSum:InvId:Password2
    """
    cfg = RobokassaConfig.from_settings()
    if not cfg.is_configured:
        logger.warning("Robokassa not configured, cannot verify signature")
        return False

    expected = _md5(f"{out_sum}:{inv_id}:{cfg.password_2}")
    return expected.lower() == signature_value.lower()


def verify_success_signature(
    out_sum: str,
    inv_id: str,
    signature_value: str,
) -> bool:
    """
    Verifies signature on SuccessURL (when user returns from payment page).

    Expected MD5 format: OutSum:InvId:Password1
    """
    cfg = RobokassaConfig.from_settings()
    if not cfg.is_configured:
        return False
    expected = _md5(f"{out_sum}:{inv_id}:{cfg.password_1}")
    return expected.lower() == signature_value.lower()


def build_receipt_item(
    name: str,
    price: float,
    quantity: int = 1,
    tax: str = "none",  # "none" для УСН, "vat20" для ОСН
) -> dict:
    """Build one item for fiscal receipt (54-ФЗ). For digital services."""
    return {
        "name": name[:128],
        "quantity": quantity,
        "sum": round(price * quantity, 2),
        "payment_method": "full_payment",
        "payment_object": "service",
        "tax": tax,
    }
