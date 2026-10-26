"""Защита: бот отвечает только владельцу."""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

log = logging.getLogger(__name__)


class OwnerOnlyMiddleware(BaseMiddleware):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id != self.owner_id:
            # Чужим не отвечаем вообще
            log.info("Игнорирую пользователя %s", getattr(user, "id", None))
            return None
        return await handler(event, data)
