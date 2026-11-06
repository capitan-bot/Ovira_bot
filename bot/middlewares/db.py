from aiogram import BaseMiddleware

from database.connection import session_scope


class DbSessionMiddleware(BaseMiddleware):
    """One DB transaction per update: commit on success, rollback on any error."""

    async def __call__(self, handler, event, data):
        async with session_scope() as session:
            data["session"] = session
            return await handler(event, data)
