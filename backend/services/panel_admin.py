from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.crypto import encrypt_text
from database.models import Order, Panel, PanelType, Service


async def create_panel(session: AsyncSession, *, name: str, panel_type: PanelType, api_url: str,
                       username: str | None, password: str | None, token: str | None = None) -> Panel:
    order = (await session.execute(select(func.coalesce(func.max(Panel.sort_order), 0)))).scalar_one()
    panel = Panel(
        display_name=name, panel_type=panel_type, api_url=api_url.rstrip("/"),
        username_enc=encrypt_text(username), password_enc=encrypt_text(password), token_enc=encrypt_text(token),
        sort_order=order + 1,
    )
    session.add(panel)
    await session.flush()
    return panel


async def update_credentials(session: AsyncSession, panel: Panel, *, api_url: str,
                             username: str | None, password: str | None) -> None:
    panel.api_url = api_url.rstrip("/")
    panel.username_enc = encrypt_text(username)
    panel.password_enc = encrypt_text(password)
    await session.flush()


async def panel_usage(session: AsyncSession, panel_id: int) -> int:
    orders = (await session.execute(select(func.count()).select_from(Order).where(Order.panel_id == panel_id))).scalar_one()
    services = (await session.execute(select(func.count()).select_from(Service).where(Service.panel_id == panel_id))).scalar_one()
    return int(orders) + int(services)


async def delete_panel(session: AsyncSession, panel: Panel) -> bool:
    """Refuses to delete a panel that has orders/services (history must stay consistent)."""
    if await panel_usage(session, panel.id) > 0:
        return False
    await session.delete(panel)
    await session.flush()
    return True
