from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import utcnow
from database.models import (
    FreeTest, Order, OrderStatus, Panel, Receipt, ReceiptStatus, Service, ServiceStatus, User, Wallet,
)


async def _n(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


async def global_stats(session: AsyncSession) -> dict:
    since = utcnow() - timedelta(hours=24)
    cnt = lambda model, *where: select(func.count()).select_from(model).where(*where)  # noqa: E731
    return {
        "users": await _n(session, cnt(User)),
        "blocked": await _n(session, cnt(User, User.is_blocked.is_(True))),
        "new24": await _n(session, cnt(User, User.created_at >= since)),
        "wallet_sum": await _n(session, select(func.coalesce(func.sum(Wallet.balance), 0))),
        "charged_sum": await _n(session, select(func.coalesce(func.sum(Wallet.total_charged), 0))),
        "pending_receipts": await _n(session, cnt(Receipt, Receipt.status == ReceiptStatus.PENDING)),
        "orders_done": await _n(session, cnt(Order, Order.status == OrderStatus.COMPLETED)),
        "sales_sum": await _n(session, select(func.coalesce(func.sum(Order.final_price), 0))
                              .where(Order.status == OrderStatus.COMPLETED)),
        "services": await _n(session, cnt(Service)),
        "services_active": await _n(session, cnt(Service, Service.status == ServiceStatus.ACTIVE)),
        "tests": await _n(session, cnt(FreeTest)),
        "panels": await _n(session, cnt(Panel)),
    }


async def user_report(session: AsyncSession, user: User) -> dict:
    wallet = (await session.execute(select(Wallet).where(Wallet.user_id == user.id))).scalar_one()
    cnt = lambda model, *where: select(func.count()).select_from(model).where(*where)  # noqa: E731
    return {
        "balance": wallet.balance,
        "total_charged": wallet.total_charged,
        "total_spent": wallet.total_spent,
        "purchases": await _n(session, cnt(Order, Order.user_id == user.id, Order.status == OrderStatus.COMPLETED)),
        "tests": await _n(session, cnt(FreeTest, FreeTest.user_id == user.id)),
        "services": await _n(session, cnt(Service, Service.user_id == user.id)),
        "services_active": await _n(session, cnt(Service, Service.user_id == user.id,
                                                 Service.status == ServiceStatus.ACTIVE)),
    }


async def search_users(session: AsyncSession, q: str, limit: int = 8) -> list[User]:
    q = (q or "").strip()
    if not q:
        return []
    if q.isdigit():
        stmt = select(User).where(User.telegram_id == int(q))
    else:
        like = f"%{q.lstrip('@')}%"
        stmt = select(User).where(or_(User.username.ilike(like), User.first_name.ilike(like),
                                      User.last_name.ilike(like))).order_by(User.id.desc())
    return list((await session.execute(stmt.limit(limit))).scalars())


async def list_users(session: AsyncSession, page: int, per_page: int = 8,
                     blocked_only: bool = False) -> tuple[list[User], int]:
    where = [User.is_blocked.is_(True)] if blocked_only else []
    total = await _n(session, select(func.count()).select_from(User).where(*where))
    rows = (await session.execute(
        select(User).where(*where).order_by(User.id.desc()).offset(page * per_page).limit(per_page)
    )).scalars().all()
    return list(rows), total
