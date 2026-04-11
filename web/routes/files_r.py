"""Хранилище файлов (с изоляцией и лимитами)."""
from pathlib import Path
from fastapi import APIRouter, Request, Form, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, or_
from db.models import UserFile, FileType, async_session_factory
from db.plan_limits import check_limit
from web.routes._scope import get_request_user, scope_query

router = APIRouter(prefix="/files")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _detect_file_type(content: str) -> FileType:
    lines = [l.strip() for l in content.splitlines() if l.strip()][:10]
    if not lines:
        return FileType.OTHER
    digits = sum(1 for l in lines if l.lstrip("-").isdigit())
    links = sum(1 for l in lines if "max.ru" in l or "join/" in l or "http" in l)
    phones = sum(1 for l in lines if l.startswith(("+7", "7", "8")) and len(l.replace(" ", "").replace("-", "")) >= 10)
    if links > len(lines) * 0.5:
        return FileType.LINKS
    if phones > len(lines) * 0.5:
        return FileType.PHONES
    if digits > len(lines) * 0.5:
        return FileType.IDS
    return FileType.OTHER


@router.get("/", response_class=HTMLResponse)
async def files_page(request: Request, folder: str = "", search: str = "", msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(UserFile), UserFile, user)
        if folder:
            q = q.where(UserFile.folder == folder)
        if search:
            q = q.where(or_(UserFile.name.ilike(f"%{search}%"), UserFile.original_filename.ilike(f"%{search}%")))
        files = (await s.execute(q.order_by(UserFile.created_at.desc()))).scalars().all()

        folders_q = scope_query(select(UserFile.folder), UserFile, user).distinct()
        folders = (await s.execute(folders_q)).scalars().all()

        total_q = scope_query(select(func.count(UserFile.id)), UserFile, user)
        total_files = (await s.execute(total_q)).scalar() or 0

    return templates.TemplateResponse(request=request, name="files.html", context={
        "files": files,
        "folders": sorted(set(f for f in folders if f)),
        "folder_filter": folder,
        "search": search,
        "total_files": total_files,
        "msg": msg,
    })


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(""),
    folder: str = Form("default"),
):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, UserFile, "max_files")
        if not can_add:
            return RedirectResponse(
                f"/app/files/?msg=Лимит+файлов+({current}/{limit})",
                status_code=303,
            )

    content = (await file.read()).decode("utf-8", errors="ignore")
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    file_type = _detect_file_type(content)
    display_name = name.strip() or file.filename or "file.txt"

    async with async_session_factory() as s:
        s.add(UserFile(
            name=display_name,
            original_filename=file.filename,
            file_type=file_type,
            content="\n".join(lines),
            lines_total=len(lines),
            folder=folder.strip() or "default",
            owner_id=user.id if user else None,
        ))
        await s.commit()
    return RedirectResponse(f"/app/files/?msg=Загружен+{display_name}+({len(lines)}+строк)", status_code=303)


@router.post("/create")
async def create_from_text(
    request: Request,
    name: str = Form(...),
    content: str = Form(...),
    folder: str = Form("default"),
):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, UserFile, "max_files")
        if not can_add:
            return RedirectResponse(
                f"/app/files/?msg=Лимит+файлов+({current}/{limit})",
                status_code=303,
            )

    lines = [l.strip() for l in content.splitlines() if l.strip()]
    file_type = _detect_file_type(content)
    async with async_session_factory() as s:
        s.add(UserFile(
            name=name,
            file_type=file_type,
            content="\n".join(lines),
            lines_total=len(lines),
            folder=folder.strip() or "default",
            owner_id=user.id if user else None,
        ))
        await s.commit()
    return RedirectResponse(f"/app/files/?msg=Создан+{name}", status_code=303)


async def _get_file_if_owned(session, file_id: int, user):
    f = await session.get(UserFile, file_id)
    if not f:
        return None
    if user and getattr(user, "is_superadmin", False):
        return f
    if f.owner_id == (user.id if user else None):
        return f
    return None


@router.get("/{file_id}")
async def view_file(request: Request, file_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        f = await _get_file_if_owned(s, file_id, user)
    if not f:
        return JSONResponse({"error": "not found"}, 404)
    lines = f.content.splitlines()
    return JSONResponse({
        "id": f.id, "name": f.name, "file_type": f.file_type.value,
        "lines_total": f.lines_total, "lines_used": f.lines_used,
        "preview": lines[:50], "folder": f.folder,
    })


@router.post("/{file_id}/delete")
async def delete_file(request: Request, file_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        f = await _get_file_if_owned(s, file_id, user)
        if f:
            await s.delete(f)
            await s.commit()
    return RedirectResponse("/app/files/", status_code=303)
