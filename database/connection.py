from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import get_settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


def session_scope():
    """Usage: async with session_scope() as s:  (commits on success, rolls back on error)"""
    return _Scope()


class _Scope:
    async def __aenter__(self) -> AsyncSession:
        self.session = get_sessionmaker()()
        self.tx = await self.session.begin()
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                await self.tx.commit()
            else:
                await self.tx.rollback()
        finally:
            await self.session.close()
