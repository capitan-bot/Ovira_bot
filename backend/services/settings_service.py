from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Setting


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return row.value if row and row.value is not None else default


async def get_settings_map(session: AsyncSession, keys: list[str]) -> dict[str, str]:
    rows = (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    data = {r.key: (r.value or "") for r in rows}
    return {k: data.get(k, "") for k in keys}


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.flush()
