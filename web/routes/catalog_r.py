"""Каталог чатов MAX."""
from pathlib import Path
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, or_
from web.routes._scope import get_request_user, scope_query
from db.models import ChatCatalog, async_session_factory

router = APIRouter(prefix="/catalog")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/", response_class=HTMLResponse)
async def catalog_page(request: Request, category: str = "", search: str = "", msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(ChatCatalog), ChatCatalog, user)
        if category:
            q = q.where(ChatCatalog.category == category)
        if search:
            q = q.where(or_(ChatCatalog.name.ilike(f"%{search}%"), ChatCatalog.description.ilike(f"%{search}%")))
        chats = (await s.execute(q.order_by(ChatCatalog.members_count.desc().nullslast()))).scalars().all()
        cat_q = scope_query(select(ChatCatalog.category), ChatCatalog, user).distinct().where(ChatCatalog.category.isnot(None))
        categories = (await s.execute(cat_q)).scalars().all()
    return templates.TemplateResponse(request=request, name="catalog.html", context={
        "chats": chats, "categories": sorted(c for c in categories if c),
        "category_filter": category, "search": search, "msg": msg,
    })

@router.post("/add")
async def add_chat(request: Request, name: str = Form(...), invite_link: str = Form(""), category: str = Form(""),
                   description: str = Form(""), members_count: int = Form(0)):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        s.add(ChatCatalog(name=name, invite_link=invite_link, category=category,
                          description=description, members_count=members_count or None,
                          owner_id=user.id if user else None))
        await s.commit()
    return RedirectResponse("/app/catalog/?msg=Чат+добавлен", status_code=303)

@router.post("/{chat_id}/update")
async def update_chat(request: Request, chat_id: int, category: str = Form(""), description: str = Form("")):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        chat = await s.get(ChatCatalog, chat_id)
        if chat and (getattr(user, "is_superadmin", False) or chat.owner_id == (user.id if user else None)):
            chat.category = category
            chat.description = description
            await s.commit()
    return RedirectResponse("/app/catalog/", status_code=303)

@router.post("/{chat_id}/delete")
async def delete_chat(request: Request, chat_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        chat = await s.get(ChatCatalog, chat_id)
        if chat and (getattr(user, "is_superadmin", False) or chat.owner_id == (user.id if user else None)):
            await s.delete(chat)
            await s.commit()
    return RedirectResponse("/app/catalog/", status_code=303)
