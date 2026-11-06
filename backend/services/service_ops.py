"""
Service management for customers: paid renewal (extra GB / extra days), link replacement,
on/off, full deletion.

Money rule (same as buying): the wallet is debited in its own committed transaction BEFORE the panel is
called, and refunded (REFUND row, unique key) if the panel fails. No new tables: renewals are wallet-ledger
rows with ref_type="renewal".
"""
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.errors import DomainError, NotFound
from backend.services.shop import GB, adapter_available, calc_price
from backend.services.wallet import apply_wallet_change
from database.base import utcnow
from database.models import Panel, Service, ServiceStatus, TxType


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def remaining_bytes(total_bytes: int, used_bytes: int) -> int:
    return max(0, int(total_bytes or 0) - int(used_bytes or 0))


def new_expiry(current: datetime | None, add_days: int, now: datetime | None = None) -> datetime:
    """Extra days are added to the later of 'now' and the current end date (an expired service restarts today)."""
    now = now or utcnow()
    base = max(now, aware(current)) if current else now
    return base + timedelta(days=add_days)


def renewal_price(panel: Panel, gb: int, days: int) -> int:
    return calc_price(panel, gb, days)


def check_renewal_input(panel: Panel, gb: int, days: int) -> str | None:
    """Returns a customer-safe error message, or None when the numbers are fine."""
    if gb < 0 or days < 0 or (gb == 0 and days == 0):
        return "حداقل یکی از حجم یا مدت باید بیشتر از صفر باشد."
    if gb > panel.max_gb:
        return f"حجم اضافه نباید بیشتر از {panel.max_gb} گیگابایت باشد."
    if days > panel.max_days:
        return f"مدت اضافه نباید بیشتر از {panel.max_days} روز باشد."
    return None


async def load_service_for_user(session: AsyncSession, service_id: int, user_id: int) -> Service:
    svc = await session.get(Service, service_id)
    if svc is None or svc.user_id != user_id or svc.status == ServiceStatus.DELETED:
        raise NotFound("سرویس پیدا نشد.")
    return svc


async def reserve_renewal(session: AsyncSession, *, user_id: int, service_id: int, gb: int, days: int,
                          key: str) -> tuple[int, Panel]:
    """Validates and debits the wallet. Raises InsufficientFunds (nothing saved) or DomainError/NotFound."""
    svc = await load_service_for_user(session, service_id, user_id)
    if svc.is_test:
        raise DomainError("سرویس تست قابل تمدید نیست. یک اشتراک جدید بخرید.")
    panel = await session.get(Panel, svc.panel_id)
    if panel is None or not panel.is_active or not adapter_available(panel):
        raise DomainError("پنل این سرویس در حال حاضر در دسترس نیست.")
    err = check_renewal_input(panel, gb, days)
    if err:
        raise DomainError(err)
    price = renewal_price(panel, gb, days)
    if price <= 0:
        raise DomainError("قیمت این پنل هنوز تنظیم نشده است.")
    await apply_wallet_change(
        session, user_id=user_id, delta=-price, tx_type=TxType.PURCHASE,
        idempotency_key=f"renew:{key}:pay", ref_type="renewal", ref_id=service_id,
        description=f"تمدید سرویس {svc.username} (+{gb}GB, +{days} روز)",
    )
    return price, panel


async def refund_renewal(session: AsyncSession, *, user_id: int, service_id: int, key: str, price: int) -> int:
    res = await apply_wallet_change(
        session, user_id=user_id, delta=price, tx_type=TxType.REFUND,
        idempotency_key=f"renew:{key}:refund", ref_type="renewal", ref_id=service_id,
        description="بازگشت وجه تمدید ناموفق",
    )
    return res.tx.balance_after


def gb_to_bytes(gb: int) -> int:
    return int(gb) * GB
