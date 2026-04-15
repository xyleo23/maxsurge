"""Массовое управление профилями MAX аккаунтов."""
import asyncio
from loguru import logger
from max_client.account import account_manager
from max_client.ops import change_profile, set_online_status_visibility as change_online_status_visibility, set_findable_by_phone as set_is_findable_by_phone, set_invite_privacy as invite_privacy

_profile_status: dict = {"running": False, "done": 0, "total": 0, "log": []}


def get_profile_status() -> dict:
    return dict(_profile_status)


async def mass_update_profiles(
    account_ids: list[int] | None,
    first_names: list[str] | None = None,
    last_names: list[str] | None = None,
    bio: str | None = None,
    hide_online: bool | None = None,
    findable_by_phone: bool | None = None,
    allow_invites: bool | None = None,
):
    """Массовое обновление профилей."""
    global _profile_status
    _profile_status = {"running": True, "done": 0, "total": 0, "log": []}

    try:
        pairs = await account_manager.get_all_active_clients()
        if account_ids:
            pairs = [(a, c) for a, c in pairs if a.id in account_ids]

        _profile_status["total"] = len(pairs)
        if not pairs:
            _profile_status["log"].append("Нет аккаунтов")
            return

        for i, (acc, client) in enumerate(pairs):
            if not _profile_status["running"]:
                break
            try:
                fname = first_names[i % len(first_names)] if first_names else None
                lname = last_names[i % len(last_names)] if last_names else None

                if fname or lname or bio:
                    await change_profile(client, first_name=fname, last_name=lname, bio=bio)
                    _profile_status["log"].append(f"[OK] {acc.phone}: {fname or ''} {lname or ''}")

                if hide_online is not None:
                    await change_online_status_visibility(client, hide_online)

                if findable_by_phone is not None:
                    await set_is_findable_by_phone(client, findable_by_phone)

                if allow_invites is not None:
                    await invite_privacy(client, allow_invites)

                _profile_status["done"] += 1
            except Exception as e:
                _profile_status["log"].append(f"[FAIL] {acc.phone}: {str(e)[:60]}")
            await asyncio.sleep(2)

    except Exception as e:
        _profile_status["log"].append(f"ОШИБКА: {e}")
    finally:
        _profile_status["running"] = False
