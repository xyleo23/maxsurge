"""Contact page + form submission → TG notification to owner."""
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from web.routes._rate_limit import rate_limit, get_client_ip

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/contacts", response_class=HTMLResponse)
async def contacts_page(request: Request, msg: str = ""):
    return templates.TemplateResponse(request=request, name="contacts.html", context={"msg": msg})


@router.post("/contacts/send")
async def send_contact(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    message: str = Form(""),
):
    ip = get_client_ip(request)
    ok, reset = rate_limit(f"contact:{ip}", max_requests=3, window_sec=600)
    if not ok:
        return RedirectResponse(f"/contacts?msg=Подождите+{reset}+секунд", status_code=303)

    if not message.strip():
        return RedirectResponse("/contacts?msg=Введите+сообщение", status_code=303)

    # TG notify
    try:
        from max_client.tg_notifier import notify_async
        text = (
            "📨 <b>Контактная форма</b>\n\n"
            + f"👤 {name or 'Аноним'}\n"
            + f"📧 {email or '—'}\n"
            + f"💬 {message[:1000]}\n"
            + f"🌐 IP: {ip}"
        )
        notify_async(text)
    except Exception:
        pass

    return RedirectResponse("/contacts?msg=Сообщение+отправлено!+Мы+ответим+в+ближайшее+время.", status_code=303)
