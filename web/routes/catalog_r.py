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
async def catalog_page(
    request: Request,
    category: str = "",
    search: str = "",
    type_filter: str = "",   # "chat" | "channel" | ""
    sort: str = "members_desc",  # members_desc | members_asc | name | recent
    page: int = 1,
    msg: str = "",
):
    user = await get_request_user(request)
    per_page = 50
    page = max(1, page)

    async with async_session_factory() as s:
        # Show user's own + public (owner_id IS NULL). Superadmin sees everything.
        if user and not getattr(user, "is_superadmin", False):
            q = select(ChatCatalog).where(
                or_(ChatCatalog.owner_id == user.id, ChatCatalog.owner_id.is_(None))
            )
        elif user:
            q = select(ChatCatalog)
        else:
            q = select(ChatCatalog).where(ChatCatalog.owner_id == -1)  # unauth sees nothing

        if category:
            q = q.where(ChatCatalog.category == category)
        if search:
            q = q.where(or_(
                ChatCatalog.name.ilike(f"%{search}%"),
                ChatCatalog.description.ilike(f"%{search}%"),
            ))
        if type_filter == "channel":
            q = q.where(ChatCatalog.is_channel == True)
        elif type_filter == "chat":
            q = q.where(ChatCatalog.is_channel == False)

        # Count total for pagination
        total = (await s.execute(
            select(func.count()).select_from(q.subquery())
        )).scalar() or 0

        # Sort
        if sort == "members_asc":
            q = q.order_by(ChatCatalog.members_count.asc().nullslast())
        elif sort == "name":
            q = q.order_by(ChatCatalog.name.asc())
        elif sort == "recent":
            q = q.order_by(ChatCatalog.added_at.desc())
        else:  # members_desc default
            q = q.order_by(ChatCatalog.members_count.desc().nullslast())

        chats = (await s.execute(
            q.offset((page - 1) * per_page).limit(per_page)
        )).scalars().all()

        # Distinct categories from user's visible scope
        cat_q = select(ChatCatalog.category).distinct().where(ChatCatalog.category.isnot(None))
        if user and not getattr(user, "is_superadmin", False):
            cat_q = cat_q.where(or_(ChatCatalog.owner_id == user.id, ChatCatalog.owner_id.is_(None)))
        categories = (await s.execute(cat_q)).scalars().all()

    has_next = total > page * per_page
    return templates.TemplateResponse(request=request, name="catalog.html", context={
        "chats": chats,
        "categories": sorted(c for c in categories if c),
        "category_filter": category,
        "search": search,
        "type_filter": type_filter,
        "sort": sort,
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_next": has_next,
        "msg": msg,
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
