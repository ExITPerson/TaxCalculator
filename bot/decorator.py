from enum import Enum
from functools import lru_cache, wraps

from bot.instance import bot
from config.settings import ADMIN_IDS
from database.db import Session


class Role(str, Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


ROLE_LEVEL = {
    Role.USER: 0,
    Role.MODERATOR: 10,
    Role.ADMIN: 100,
}


@lru_cache(maxsize=1024)
def _get_role_cached(user_id: int) -> Role:
    from database.crud import UserCrud
    with Session() as session:
        return UserCrud(session).get_role(user_id)


def get_user_role(user_id: int) -> Role:
    """ADMIN_IDS из .env — всегда админы. Остальные — из БД."""
    if user_id in ADMIN_IDS:
        return Role.ADMIN
    return _get_role_cached(user_id)


def clear_role_cache() -> None:
    """Сбросить кэш ролей (после set_role)."""
    _get_role_cached.cache_clear()


def require_role_cb(min_role: Role):
    """Декоратор для callback handler."""
    def decorator(func):
        @wraps(func)
        def wrapper(call, *args, **kwargs):
            role = get_user_role(call.from_user.id)
            if ROLE_LEVEL[role] < ROLE_LEVEL[min_role]:
                bot.answer_callback_query(call.id, "⛔ Недостаточно прав", show_alert=True)
                return
            return func(call, *args, **kwargs)
        return wrapper
    return decorator


def require_role(min_role: Role):
    """Декоратор для message handler."""
    def decorator(func):
        @wraps(func)
        def wrapper(message, *args, **kwargs):
            if not message.from_user:
                return
            role = get_user_role(message.from_user.id)
            if ROLE_LEVEL[role] < ROLE_LEVEL[min_role]:
                bot.reply_to(message, "⛔ Недостаточно прав")
                return
            return func(message, *args, **kwargs)
        return wrapper
    return decorator