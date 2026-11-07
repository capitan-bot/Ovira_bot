import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import get_settings
from database.base import Base
import database.models  # noqa: F401  (register all tables)

target_metadata = Base.metadata
url = get_settings().database_url


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
