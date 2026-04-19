import asyncio
"""Биллинг через ЮKassa: выбор тарифа, создание платежа, webhook."""
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import select
from yookassa import Configuration, Payment as YKPayment
from max_client.robokassa import (
    RobokassaConfig,
    create_payment_url as rb_create_payment_url,
    verify_result_signature as rb_verify_result,
    verify_success_signature as rb_verify_success,
    build_receipt_item as rb_build_receipt_item,
)
from max_client.prodamus import (
    ProdamusConfig,
    create_payment_url as pd_create_payment_url,
    verify_signature as pd_verify_signature,
)

from config import get_settings
from max_client.invoice import generate_invoice_pdf
from max_client.tg_notifier import on_payment_success, on_payment_created
from db.models import Payment, PaymentStatus, SiteUser, UserPlan, RefCommission, async_session_factory
from web.routes.auth_r import get_current_user
from max_client.webhook_dispatcher import dispatch_webhook

router = APIRouter(prefix="/billing")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
settings = get_settings()

# Конфигурация ЮKassa
if settings.YK_SHOP_ID and settings.YK_SECRET_KEY:
    Configuration.account_id = settings.YK_SHOP_ID
    Configuration.secret_key = settings.YK_SECRET_KEY


# ── Цены тарифов (в рублях) ──────────────────────────
PLAN_PRICES: Dict[UserPlan, dict] = {
    UserPlan.START: {
        "amount": 1490,
        "title": "Start",
        "description": "MaxSurge Start — 1 месяц",
        "period_days": 30,
    },
    UserPlan.BASIC: {
        "amount": 2990,
        "title": "Basic",
        "description": "MaxSurge Basic — 1 месяц",
        "period_days": 30,
    },
    UserPlan.PRO: {
        "amount": 4990,
        "title": "Pro",
        "description": "MaxSurge Pro — 1 месяц",
        "period_days": 30,
    },
    UserPlan.LIFETIME: {
        "amount": 49900,
        "title": "Lifetime",
        "description": "MaxSurge Lifetime — пожизненный доступ",
        "period_days": 36500,
    },
}


@router.get("/", response_class=HTMLResponse)
async def billing_page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        payments = (await s.execute(
            select(Payment).where(Payment.owner_id == user.id).order_by(Payment.created_at.desc()).limit(20)
        )).scalars().all()

    return templates.TemplateResponse(request=request, name="billing.html", context={
        "user": user,
        "plans": PLAN_PRICES,
        "payments": payments,
        "msg": msg,
    })


@router.post("/create-payment")
async def create_payment(request: Request, plan: str = Form(...)):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    try:
        plan_enum = UserPlan(plan)
    except ValueError:
        return RedirectResponse("/app/billing/?msg=Неверный+тариф", status_code=303)

    if plan_enum not in PLAN_PRICES:
        return RedirectResponse("/app/billing/?msg=Тариф+недоступен+для+оплаты", status_code=303)

    if not settings.YK_SHOP_ID or not settings.YK_SECRET_KEY:
        return RedirectResponse("/app/billing/?msg=ЮKassa+не+настроена", status_code=303)

    plan_info = PLAN_PRICES[plan_enum]
    idempotence_key = str(uuid.uuid4())

    try:
        yk_payment = YKPayment.create({
            "amount": {
                "value": f"{plan_info['amount']:.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": settings.YK_RETURN_URL,
            },
            "capture": True,
            "description": f"{plan_info['description']} ({user.email})",
            "metadata": {
                "user_id": str(user.id),
                "plan": plan,
            },
        }, idempotence_key)
    except Exception as e:
        logger.error("ЮKassa create error: {}", e)
        return RedirectResponse(f"/app/billing/?msg=Ошибка+оплаты:+{str(e)[:80]}", status_code=303)

    async with async_session_factory() as s:
        p = Payment(
            owner_id=user.id,
            yk_payment_id=yk_payment.id,
            plan=plan_enum,
            amount=plan_info["amount"],
            status=PaymentStatus.PENDING,
            description=plan_info["description"],
            confirmation_url=yk_payment.confirmation.confirmation_url,
        )
        s.add(p)
        await s.commit()

    logger.info("Создан платёж {} для user={} plan={}", yk_payment.id, user.id, plan)
    on_payment_created(user.email, plan, plan_info["amount"])
    return RedirectResponse(yk_payment.confirmation.confirmation_url, status_code=303)


@router.post("/webhook")
async def webhook(request: Request):
    """Обработчик webhook от ЮKassa. Активирует тариф при успешной оплате."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, 400)

    event = data.get("event")
    obj = data.get("object", {})
    yk_id = obj.get("id")
    status = obj.get("status")

    logger.info("ЮKassa webhook: event={} id={} status={}", event, yk_id, status)

    if not yk_id:
        return JSONResponse({"ok": True})

    async with async_session_factory() as s:
        payment = (await s.execute(
            select(Payment).where(Payment.yk_payment_id == yk_id)
        )).scalar_one_or_none()

        if not payment:
            logger.warning("Платёж {} не найден в БД", yk_id)
            return JSONResponse({"ok": True})

        # Обновляем статус
        try:
            payment.status = PaymentStatus(status)
        except ValueError:
            pass

        if event == "payment.succeeded" and status == "succeeded":
            payment.paid_at = datetime.utcnow()
            # Активируем тариф пользователя
            user = await s.get(SiteUser, payment.owner_id)
            if user:
                user.plan = payment.plan
                # Устанавливаем срок действия
                plan_info = PLAN_PRICES.get(payment.plan, {})
                period = plan_info.get("period_days", 30)
                if payment.plan == UserPlan.LIFETIME:
                    user.plan_expires_at = None  # Навсегда
                else:
                    # Если подписка активна — продлеваем, иначе от сегодня
                    base = user.plan_expires_at if (user.plan_expires_at and user.plan_expires_at > datetime.utcnow()) else datetime.utcnow()
                    # P9: Бонусные дни за крупные платежи
                    bonus_days = 0
                    if payment.amount >= 10000:
                        bonus_days = 30       # +1 месяц
                    elif payment.amount >= 5000:
                        bonus_days = 14       # +2 недели
                    elif payment.amount >= 3000:
                        bonus_days = 7        # +1 неделя
                    total_days = period + bonus_days
                    user.plan_expires_at = base + timedelta(days=total_days)
                    if bonus_days:
                        logger.info("P9: Бонусные дни +{} для user={}", bonus_days, user.id)
                logger.info("Тариф {} активирован для user={} до {}", payment.plan.value, user.id, user.plan_expires_at)
                on_payment_success(user.email, payment.plan.value, payment.amount)
                # P-E3: персональное уведомление пользователю
                from max_client.tg_notifier import notify_user_async
                from max_client.webhook_sender import webhook_async
                webhook_async(user.id, "payment.succeeded", {"plan": payment.plan.value, "amount": payment.amount})
                asyncio.create_task(dispatch_webhook(user.id, "payment_success", {
                    "plan": payment.plan.value,
                    "amount": payment.amount,
                    "payment_id": payment.yk_payment_id,
                    "email": user.email,
                }))
                notify_user_async(user.id, "\U0001f4b0 <b>\u041f\u043b\u0430\u0442\u0451\u0436 \u0443\u0441\u043f\u0435\u0448\u0435\u043d</b>\n\n\u0422\u0430\u0440\u0438\u0444: <b>" + payment.plan.value + "</b>\n\u0421\u0443\u043c\u043c\u0430: <b>" + str(payment.amount) + "\u20bd</b>", pref_field="notify_on_payment")

                # Реферальная комиссия (20% если юзер пришёл по рефералу)
                # 2-level referral commissions: 20% / 5%
                existing = (await s.execute(
                    select(RefCommission).where(RefCommission.payment_id == payment.id)
                )).scalars().all()
                if not existing:
                    # Level 1: прямой реферер 20%
                    if user.referred_by:
                        l1 = round(payment.amount * 0.20, 2)
                        s.add(RefCommission(
                            referrer_id=user.referred_by,
                            referred_id=user.id,
                            payment_id=payment.id,
                            amount=l1,
                            percent=20.0,
                            level=1,
                        ))
                        l1_user = await s.get(SiteUser, user.referred_by)
                        if l1_user:
                            l1_user.ref_balance = (l1_user.ref_balance or 0) + l1
                            l1_user.ref_earned_total = (l1_user.ref_earned_total or 0) + l1
                            logger.info("Ref L1 {} RUB for user={} payment={}", l1, l1_user.id, payment.id)
                            # Level 2: реферер реферера 5%
                            if l1_user.referred_by and l1_user.referred_by != user.id:
                                l2 = round(payment.amount * 0.05, 2)
                                s.add(RefCommission(
                                    referrer_id=l1_user.referred_by,
                                    referred_id=user.id,
                                    payment_id=payment.id,
                                    amount=l2,
                                    percent=5.0,
                                    level=2,
                                ))
                                l2_user = await s.get(SiteUser, l1_user.referred_by)
                                if l2_user:
                                    l2_user.ref_balance = (l2_user.ref_balance or 0) + l2
                                    l2_user.ref_earned_total = (l2_user.ref_earned_total or 0) + l2
                                    logger.info("Ref L2 {} RUB for user={} payment={}", l2, l2_user.id, payment.id)

        await s.commit()

    return JSONResponse({"ok": True})


# ════════════════════════════════════════════════════════════════════
#  ROBOKASSA endpoints (parallel to YooKassa above)
# ════════════════════════════════════════════════════════════════════

@router.post("/create-payment-rb")
async def create_payment_robokassa(request: Request, plan: str = Form(...)):
    """Create payment via Robokassa instead of YooKassa."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    try:
        plan_enum = UserPlan(plan)
    except ValueError:
        return RedirectResponse("/app/billing/?msg=Неверный+тариф", status_code=303)

    if plan_enum not in PLAN_PRICES:
        return RedirectResponse("/app/billing/?msg=Тариф+недоступен", status_code=303)

    cfg = RobokassaConfig.from_settings()
    if not cfg.is_configured:
        return RedirectResponse("/app/billing/?msg=Robokassa+не+настроена", status_code=303)

    plan_info = PLAN_PRICES[plan_enum]
    amount = plan_info["amount"]

    # Create pending Payment record
    async with async_session_factory() as s:
        payment = Payment(
            owner_id=user.id,
            yk_payment_id=f"rb_pending_{uuid.uuid4().hex[:12]}",  # temporary, will update after InvId
            plan=plan_enum,
            amount=amount,
            currency="RUB",
            status=PaymentStatus.PENDING,
            description=plan_info["description"],
        )
        s.add(payment)
        await s.commit()
        await s.refresh(payment)
        inv_id = payment.id
        # Update yk_payment_id to "rb_<id>" for tracking
        payment.yk_payment_id = f"rb_{inv_id}"
        await s.commit()

    # Build receipt for 54-ФЗ (digital service, УСН)
    receipt_items = [
        rb_build_receipt_item(
            name=plan_info["description"],
            price=amount,
            quantity=1,
            tax="none",
        )
    ]

    try:
        pay_url = rb_create_payment_url(
            amount=amount,
            order_id=inv_id,
            description=plan_info["description"],
            email=user.email,
            receipt_items=receipt_items,
        )
    except Exception as e:
        logger.exception("Robokassa create payment error")
        return RedirectResponse(f"/app/billing/?msg=Ошибка+создания+платежа:+{str(e)[:80]}", status_code=303)

    try:
        on_payment_created(user.email, amount, plan_enum.value)
    except Exception:
        pass

    logger.info("[rb] payment {} created for user {} plan={} amount={}", inv_id, user.email, plan, amount)
    return RedirectResponse(pay_url, status_code=303)


@router.post("/webhook-rb")
async def webhook_robokassa(request: Request):
    """Robokassa ResultURL webhook.

    Docs: https://docs.robokassa.ru/pay-interface/#result
    Expects POST form: OutSum, InvId, SignatureValue
    Must respond with: "OK{InvId}" (plain text) to confirm receipt
    """
    form = await request.form()
    out_sum = str(form.get("OutSum", "")).strip()
    inv_id = str(form.get("InvId", "")).strip()
    sig = str(form.get("SignatureValue", "")).strip()

    if not out_sum or not inv_id or not sig:
        logger.warning("[rb webhook] missing params")
        return Response("bad request", status_code=400)

    if not rb_verify_result(out_sum, inv_id, sig):
        logger.warning("[rb webhook] bad signature for InvId={}", inv_id)
        return Response("bad sign", status_code=400)

    # Signature valid — activate plan
    try:
        payment_id = int(inv_id)
    except ValueError:
        return Response("bad inv_id", status_code=400)

    async with async_session_factory() as s:
        payment = await s.get(Payment, payment_id)
        if not payment:
            logger.warning("[rb webhook] payment {} not found", payment_id)
            # Still return OK — Robokassa will stop retrying
            return Response(f"OK{inv_id}", media_type="text/plain")

        if payment.status == PaymentStatus.SUCCEEDED:
            logger.info("[rb webhook] payment {} already succeeded (duplicate)", payment_id)
            return Response(f"OK{inv_id}", media_type="text/plain")

        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = datetime.utcnow()
        await s.commit()
        await s.refresh(payment)

        # Activate user plan
        user = await s.get(SiteUser, payment.owner_id)
        if user:
            plan_info = PLAN_PRICES.get(payment.plan)
            period_days = plan_info["period_days"] if plan_info else 30
            now = datetime.utcnow()
            if user.plan_expires_at and user.plan_expires_at > now:
                user.plan_expires_at = user.plan_expires_at + timedelta(days=period_days)
            else:
                user.plan_expires_at = now + timedelta(days=period_days)
            user.plan = payment.plan
            await s.commit()

            try:
                on_payment_success(user.email, float(payment.amount), payment.plan.value)
            except Exception:
                pass

            try:
                from max_client.webhook_sender import webhook_async
                webhook_async(user.id, "payment.succeeded", {"plan": payment.plan.value, "amount": float(payment.amount), "gateway": "robokassa"})
                asyncio.create_task(dispatch_webhook(user.id, "payment_success", {
                    "payment_id": payment.yk_payment_id,
                    "amount": float(payment.amount),
                    "plan": payment.plan.value,
                    "gateway": "robokassa",
                }))
            except Exception:
                pass

            # Referral commission
            if user.referred_by:
                try:
                    referrer = await s.get(SiteUser, user.referred_by)
                    if referrer:
                        commission = round(float(payment.amount) * 0.20, 2)
                        referrer.ref_balance = float(referrer.ref_balance or 0) + commission
                        referrer.ref_earned_total = float(referrer.ref_earned_total or 0) + commission
                        s.add(RefCommission(
                            referrer_id=referrer.id,
                            referred_id=user.id,
                            payment_id=payment.id,
                            amount=commission,
                            level=1,
                        ))
                        # L2
                        if referrer.referred_by:
                            l2 = await s.get(SiteUser, referrer.referred_by)
                            if l2:
                                l2_comm = round(float(payment.amount) * 0.05, 2)
                                l2.ref_balance = float(l2.ref_balance or 0) + l2_comm
                                l2.ref_earned_total = float(l2.ref_earned_total or 0) + l2_comm
                                s.add(RefCommission(
                                    referrer_id=l2.id,
                                    referred_id=user.id,
                                    payment_id=payment.id,
                                    amount=l2_comm,
                                    level=2,
                                ))
                        await s.commit()
                except Exception as e:
                    logger.warning("ref commission error: {}", e)

    logger.info("[rb webhook] payment {} succeeded InvId={}", payment_id, inv_id)
    return Response(f"OK{inv_id}", media_type="text/plain")


@router.get("/success-rb")
async def success_robokassa(request: Request, OutSum: str = "", InvId: str = "", SignatureValue: str = ""):
    """Robokassa SuccessURL — user returned from payment page."""
    if OutSum and InvId and SignatureValue:
        if rb_verify_success(OutSum, InvId, SignatureValue):
            return RedirectResponse(f"/app/billing/success?source=robokassa&inv={InvId}", status_code=303)
    return RedirectResponse("/app/billing/?msg=Платёж+обработан", status_code=303)


@router.get("/fail-rb")
async def fail_robokassa(request: Request):
    """Robokassa FailURL — payment cancelled/failed."""
    return RedirectResponse("/app/billing/?msg=Платёж+отменён", status_code=303)


# ================================================================
#  PRODAMUS endpoints
# ================================================================

@router.post("/create-payment-pd")
async def create_payment_prodamus(request: Request, plan: str = Form(...)):
    """Create payment via Prodamus."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    try:
        plan_enum = UserPlan(plan)
    except ValueError:
        return RedirectResponse("/app/billing/?msg=Неверный+тариф", status_code=303)

    if plan_enum not in PLAN_PRICES:
        return RedirectResponse("/app/billing/?msg=Тариф+недоступен", status_code=303)

    cfg = ProdamusConfig.from_settings()
    if not cfg.is_configured:
        return RedirectResponse("/app/billing/?msg=Prodamus+не+настроен", status_code=303)

    plan_info = PLAN_PRICES[plan_enum]
    amount = plan_info["amount"]

    async with async_session_factory() as s:
        payment = Payment(
            owner_id=user.id,
            yk_payment_id=f"pd_pending_{uuid.uuid4().hex[:12]}",
            plan=plan_enum,
            amount=amount,
            currency="RUB",
            status=PaymentStatus.PENDING,
            description=plan_info["description"],
        )
        s.add(payment)
        await s.commit()
        await s.refresh(payment)
        order_id = payment.id
        payment.yk_payment_id = f"pd_{order_id}"
        await s.commit()

    try:
        pay_url = pd_create_payment_url(
            amount=amount,
            order_id=order_id,
            description=plan_info["description"],
            email=user.email,
        )
    except Exception as e:
        logger.exception("Prodamus create payment error")
        return RedirectResponse(f"/app/billing/?msg=Ошибка+создания+платежа:+{str(e)[:80]}", status_code=303)

    try:
        on_payment_created(user.email, amount, plan_enum.value)
    except Exception:
        pass

    logger.info("[pd] payment {} created for user {} plan={} amount={}", order_id, user.email, plan, amount)
    return RedirectResponse(pay_url, status_code=303)


@router.post("/webhook-pd")
async def webhook_prodamus(request: Request):
    """Prodamus urlNotification webhook.

    Expects POST form with: order_id, sum, payment_status, signature
    """
    form = await request.form()
    data = {k: str(v) for k, v in form.items()}
    signature = data.pop("signature", "")
    order_id = data.get("order_id", "")
    status = data.get("payment_status", "")
    paid_sum = data.get("sum", "")

    if not pd_verify_signature(data, signature):
        logger.warning("[pd webhook] bad signature for order_id={}", order_id)
        return Response("bad sign", status_code=400)

    try:
        payment_id = int(order_id)
    except ValueError:
        return Response("bad order_id", status_code=400)

    if status not in ("success", "paid"):
        logger.info("[pd webhook] status={} for order {}, ignoring", status, payment_id)
        return Response("ok", media_type="text/plain")

    async with async_session_factory() as s:
        payment = await s.get(Payment, payment_id)
        if not payment:
            logger.warning("[pd webhook] payment {} not found", payment_id)
            return Response("ok", media_type="text/plain")

        if payment.status == PaymentStatus.SUCCEEDED:
            logger.info("[pd webhook] payment {} already succeeded (duplicate)", payment_id)
            return Response("ok", media_type="text/plain")

        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = datetime.utcnow()
        await s.commit()
        await s.refresh(payment)

        user = await s.get(SiteUser, payment.owner_id)
        if user:
            plan_info = PLAN_PRICES.get(payment.plan)
            period_days = plan_info["period_days"] if plan_info else 30
            now = datetime.utcnow()
            if user.plan_expires_at and user.plan_expires_at > now:
                user.plan_expires_at = user.plan_expires_at + timedelta(days=period_days)
            else:
                user.plan_expires_at = now + timedelta(days=period_days)
            user.plan = payment.plan
            await s.commit()

            try:
                on_payment_success(user.email, float(payment.amount), payment.plan.value)
            except Exception:
                pass

            try:
                from max_client.webhook_sender import webhook_async
                webhook_async(user.id, "payment.succeeded", {"plan": payment.plan.value, "amount": float(payment.amount), "gateway": "prodamus"})
                asyncio.create_task(dispatch_webhook(user.id, "payment_success", {
                    "payment_id": payment.yk_payment_id,
                    "amount": float(payment.amount),
                    "plan": payment.plan.value,
                    "gateway": "prodamus",
                }))
            except Exception:
                pass

            if user.referred_by:
                try:
                    referrer = await s.get(SiteUser, user.referred_by)
                    if referrer:
                        commission = round(float(payment.amount) * 0.20, 2)
                        referrer.ref_balance = float(referrer.ref_balance or 0) + commission
                        referrer.ref_earned_total = float(referrer.ref_earned_total or 0) + commission
                        s.add(RefCommission(
                            referrer_id=referrer.id,
                            referred_id=user.id,
                            payment_id=payment.id,
                            amount=commission,
                            level=1,
                        ))
                        if referrer.referred_by:
                            l2 = await s.get(SiteUser, referrer.referred_by)
                            if l2:
                                l2_comm = round(float(payment.amount) * 0.05, 2)
                                l2.ref_balance = float(l2.ref_balance or 0) + l2_comm
                                l2.ref_earned_total = float(l2.ref_earned_total or 0) + l2_comm
                                s.add(RefCommission(
                                    referrer_id=l2.id,
                                    referred_id=user.id,
                                    payment_id=payment.id,
                                    amount=l2_comm,
                                    level=2,
                                ))
                        await s.commit()
                except Exception as e:
                    logger.warning("ref commission error: {}", e)

    logger.info("[pd webhook] payment {} succeeded sum={}", payment_id, paid_sum)
    return Response("success", media_type="text/plain")


@router.get("/success-pd")
async def success_prodamus(request: Request):
    """Prodamus return URL."""
    return RedirectResponse("/app/billing/success?source=prodamus", status_code=303)


@router.get("/success", response_class=HTMLResponse)
async def success_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request=request, name="billing_success.html", context={
        "user": user,
    })


@router.post("/check/{payment_id}")
async def check_payment(request: Request, payment_id: int):
    """Ручная проверка статуса платежа (если webhook не пришёл)."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        payment = await s.get(Payment, payment_id)
        if not payment or payment.owner_id != user.id:
            return RedirectResponse("/app/billing/?msg=Не+найдено", status_code=303)

        try:
            yk_payment = YKPayment.find_one(payment.yk_payment_id)
            payment.status = PaymentStatus(yk_payment.status)
            if yk_payment.status == "succeeded" and not payment.paid_at:
                payment.paid_at = datetime.utcnow()
                user_db = await s.get(SiteUser, payment.owner_id)
                if user_db:
                    user_db.plan = payment.plan
                    plan_info = PLAN_PRICES.get(payment.plan, {})
                    period = plan_info.get("period_days", 30)
                    if payment.plan == UserPlan.LIFETIME:
                        user_db.plan_expires_at = None
                    else:
                        base = user_db.plan_expires_at if (user_db.plan_expires_at and user_db.plan_expires_at > datetime.utcnow()) else datetime.utcnow()
                        user_db.plan_expires_at = base + timedelta(days=period)
            await s.commit()
            return RedirectResponse(f"/app/billing/?msg=Статус:+{yk_payment.status}", status_code=303)
        except Exception as e:
            return RedirectResponse(f"/app/billing/?msg=Ошибка+проверки:+{str(e)[:60]}", status_code=303)



@router.get("/invoice/{payment_id}")
async def invoice_download(request: Request, payment_id: int):
    """Скачать PDF чек для успешного платежа."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        payment = await s.get(Payment, payment_id)

    if not payment:
        return RedirectResponse("/app/billing/?msg=Платёж+не+найден", status_code=303)

    # Только владелец или суперадмин
    if payment.owner_id != user.id and not getattr(user, "is_superadmin", False):
        return RedirectResponse("/app/billing/?msg=Нет+доступа", status_code=303)

    if payment.status != PaymentStatus.SUCCEEDED:
        return RedirectResponse("/app/billing/?msg=Платёж+ещё+не+оплачен", status_code=303)

    plan_info = PLAN_PRICES.get(payment.plan, {})
    pdf_bytes = generate_invoice_pdf(
        payment_id=payment.yk_payment_id,
        plan_name=plan_info.get("title", payment.plan.value),
        amount=payment.amount,
        email=user.email,
        paid_at=payment.paid_at or payment.created_at,
        description=payment.description or "",
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=invoice_{payment.id}.pdf"
        },
    )
