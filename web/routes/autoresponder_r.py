"""Роуты автоответчика (с AI режимом)."""
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from web.routes._scope import scope_query
from db.models import MaxAccount, AccountStatus, async_session_factory
from web.routes.auth_r import get_current_user
from max_client.autoresponder import start_autoresponder, stop_autoresponder, get_responder_status, get_responder_configs

router = APIRouter(prefix="/autoresponder")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
    return templates.TemplateResponse(request=request, name="autoresponder.html", context={
        "accounts": accounts,
        "status": get_responder_status(),
        "configs": get_responder_configs(),
        "msg": msg,
    })


@router.post("/start")
async def start(
    request: Request,
    phone: str = Form(...),
    text: str = Form(""),
    delay_min: float = Form(3),
    delay_max: float = Form(10),
    limit_per_day: int = Form(50),
    typing_emulation: bool = Form(True),
    use_ai: bool = Form(False),
    knowledge_base: str = Form(""),
):
    import asyncio
    user = await get_current_user(request)
    user_id = user.id if user else None
    asyncio.create_task(start_autoresponder(
        phone=phone,
        text=text or "Здравствуйте! Спасибо за ваше сообщение.",
        delay_min=delay_min,
        delay_max=delay_max,
        limit_per_day=limit_per_day,
        typing_emulation=typing_emulation,
        use_ai=use_ai,
        knowledge_base=knowledge_base,
        user_id=user_id,
    ))
    mode = "AI" if use_ai else "статичный"
    return RedirectResponse(
        f"/app/autoresponder/?msg=Автоответчик+{phone}+запущен+({mode})",
        status_code=303,
    )


@router.post("/stop")
async def stop(phone: str = Form(...)):
    stop_autoresponder(phone)
    return RedirectResponse("/app/autoresponder/?msg=Остановлен", status_code=303)


@router.get("/status")
async def status():
    return JSONResponse(get_responder_status())
