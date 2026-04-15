"""Unified MAX operations wrapper for PyMax.

Replaces legacy `vkmax.functions.*` imports with PyMax MaxClient methods.
All workers (sender/parser/inviter/neurochat/guard/etc) should import from here
instead of vkmax directly. This centralizes MAX API usage in one place.

Usage in workers:
    from max_client.ops import send_message, invite_users, fetch_members
    from max_client.account import account_manager

    client = await account_manager.get_client(phone)
    await send_message(client, chat_id=123, text="Привет")
"""
from typing import Any, Iterable

from loguru import logger
from pymax import MaxClient


# ════════════════════════════════════════════════════════════════════
#  MESSAGES
# ════════════════════════════════════════════════════════════════════

async def send_message(
    client: MaxClient,
    chat_id: int,
    text: str,
    reply_to: int | None = None,
    notify: bool = True,
) -> Any:
    """Отправить сообщение в чат/диалог."""
    return await client.send_message(
        text=text,
        chat_id=chat_id,
        notify=notify,
        reply_to=reply_to,
    )


async def edit_message(client: MaxClient, chat_id: int, message_id: int, text: str) -> Any:
    return await client.edit_message(chat_id=chat_id, message_id=message_id, text=text)


async def delete_message(client: MaxClient, chat_id: int, message_ids: list[int] | int) -> Any:
    if isinstance(message_ids, int):
        message_ids = [message_ids]
    return await client.delete_message(chat_id=chat_id, message_ids=message_ids)


async def fetch_history(client: MaxClient, chat_id: int, count: int = 50, marker: int | None = 0) -> Any:
    return await client.fetch_history(chat_id=chat_id, count=count, marker=marker)


# ════════════════════════════════════════════════════════════════════
#  GROUPS / CHATS
# ════════════════════════════════════════════════════════════════════

async def fetch_chats(client: MaxClient) -> list[Any]:
    return await client.fetch_chats()


async def get_chat_id(client: MaxClient, chat_name_or_link: str) -> int | None:
    """Resolve chat id from public link or username."""
    try:
        chat = await client.resolve_chat_by_name(chat_name_or_link)
        if chat:
            return getattr(chat, "id", None)
    except Exception as e:
        logger.debug("get_chat_id failed: {}", e)
    return None


async def resolve_chat_by_link(client: MaxClient, link: str) -> Any:
    """Backwards-compat alias: resolve group/channel by public link."""
    try:
        return await client.resolve_chat_by_name(link)
    except Exception:
        pass
    try:
        return await client.resolve_channel_by_name(link)
    except Exception:
        pass
    return None


async def join_group(client: MaxClient, link_or_chat_id: str | int) -> Any:
    return await client.join_group(link_or_chat_id)


async def join_channel(client: MaxClient, link_or_channel_id: str | int) -> Any:
    return await client.join_channel(link_or_channel_id)


async def leave_group(client: MaxClient, chat_id: int) -> Any:
    return await client.leave_group(chat_id)


async def leave_channel(client: MaxClient, channel_id: int) -> Any:
    return await client.leave_channel(channel_id)


# ════════════════════════════════════════════════════════════════════
#  MEMBERS
# ════════════════════════════════════════════════════════════════════

async def load_members(
    client: MaxClient,
    chat_id: int,
    count: int = 50,
    marker: int | None = 0,
) -> tuple[list[Any], int | None]:
    """Returns (members, next_marker). Use in a loop until next_marker is None."""
    return await client.load_members(chat_id=chat_id, count=count, marker=marker)


async def fetch_all_members(client: MaxClient, chat_id: int, max_pages: int = 100) -> list[Any]:
    """Iterate through all member pages and return full list."""
    result = []
    marker: int | None = 0
    for _ in range(max_pages):
        members, marker = await load_members(client, chat_id, count=200, marker=marker)
        result.extend(members)
        if not marker:
            break
    return result


async def invite_users(
    client: MaxClient,
    chat_id: int,
    user_ids: list[int],
    show_history: bool = True,
) -> Any:
    """Invite users to a group."""
    return await client.invite_users_to_group(
        chat_id=chat_id,
        user_ids=user_ids,
        show_history=show_history,
    )


async def invite_users_to_channel(
    client: MaxClient,
    channel_id: int,
    user_ids: list[int],
) -> Any:
    return await client.invite_users_to_channel(channel_id=channel_id, user_ids=user_ids)


async def remove_users(client: MaxClient, chat_id: int, user_ids: list[int]) -> Any:
    return await client.remove_users_from_group(chat_id=chat_id, user_ids=user_ids)


# ════════════════════════════════════════════════════════════════════
#  USERS / CONTACTS
# ════════════════════════════════════════════════════════════════════

async def resolve_users(client: MaxClient, phones: list[str] | list[int]) -> list[Any]:
    """Resolve users by phone numbers or IDs."""
    try:
        return await client.fetch_users(phones)
    except Exception:
        try:
            return await client.get_users(phones)
        except Exception as e:
            logger.debug("resolve_users failed: {}", e)
            return []


async def get_user(client: MaxClient, user_id: int) -> Any:
    return await client.get_user(user_id)


async def add_to_contacts(client: MaxClient, user_id: int, name: str | None = None) -> Any:
    return await client.add_contact(user_id=user_id, name=name)


async def remove_contact(client: MaxClient, user_id: int) -> Any:
    return await client.remove_contact(user_id)


# ════════════════════════════════════════════════════════════════════
#  PROFILE
# ════════════════════════════════════════════════════════════════════

async def change_profile(
    client: MaxClient,
    first_name: str,
    last_name: str | None = None,
    description: str | None = None,
) -> Any:
    return await client.change_profile(
        first_name=first_name,
        last_name=last_name,
        description=description,
    )


async def set_online_status_visibility(client: MaxClient, visible: bool) -> Any:
    """Try all available method names across PyMax versions."""
    for name in ("set_online_status_visibility", "change_online_status_visibility"):
        if hasattr(client, name):
            return await getattr(client, name)(visible)
    logger.warning("No online_status_visibility method on MaxClient")
    return None


async def set_findable_by_phone(client: MaxClient, findable: bool) -> Any:
    for name in ("set_findable_by_phone", "set_is_findable_by_phone"):
        if hasattr(client, name):
            return await getattr(client, name)(findable)
    return None


async def set_invite_privacy(client: MaxClient, everyone: bool = True) -> Any:
    for name in ("set_invite_privacy", "invite_privacy"):
        if hasattr(client, name):
            return await getattr(client, name)(everyone)
    return None


# ════════════════════════════════════════════════════════════════════
#  LOW-LEVEL — for code that needs direct opcode access (rare)
# ════════════════════════════════════════════════════════════════════

async def send_raw(client: MaxClient, opcode: int, payload: dict) -> dict:
    """Send a raw opcode+payload to MAX server. Used for advanced operations."""
    return await client._send_and_wait(opcode=opcode, payload=payload)
