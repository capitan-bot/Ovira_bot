from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.settings_service import get_settings_map
from database.models import (
    Invoice, InvoiceKind, InvoiceStatus, Receipt, User, WalletTransaction,
)


async def get_charge_limits(session: AsyncSession) -> dict[str, int]:
    keys = ["charge_min", "charge_max", "unique_extra_min", "unique_extra_max", "invoice_ttl_minutes"]
    raw = await get_settings_map(session, keys)
    defaults = {"charge_min": 10000, "charge_max": 5000000, "unique_extra_min": 1,
                "unique_extra_max": 99, "invoice_ttl_minutes": 60}
    out = {}
    for k in keys:
        try:
            out[k] = int(raw[k])
        except (TypeError, ValueError):
            out[k] = defaults[k]
    return out


async def cancel_open_charge_invoices(session: AsyncSession, user_id: int) -> None:
    """Starting a new charge frees the amounts of the user's unpaid old ones (no receipt under review)."""
    await session.execute(
        update(Invoice)
        .where(Invoice.user_id == user_id, Invoice.kind == InvoiceKind.WALLET_CHARGE,
               Invoice.status == InvoiceStatus.PENDING)
        .values(status=InvoiceStatus.CANCELED)
    )


async def cancel_invoice(session: AsyncSession, invoice_id: int, user_id: int) -> bool:
    res = await session.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.user_id == user_id, Invoice.status == InvoiceStatus.PENDING)
        .values(status=InvoiceStatus.CANCELED)
    )
    return (res.rowcount or 0) > 0


async def get_receipt_bundle(session: AsyncSession, receipt_id: int):
    """Returns (Receipt, Invoice, User) or None."""
    row = (await session.execute(
        select(Receipt, Invoice, User)
        .join(Invoice, Invoice.id == Receipt.invoice_id)
        .join(User, User.id == Receipt.user_id)
        .where(Receipt.id == receipt_id)
    )).first()
    return tuple(row) if row else None


async def invoice_counts(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """(unpaid, paid) invoice counts for the wallet screen."""
    async def count(*statuses):
        return (await session.execute(
            select(func.count()).select_from(Invoice)
            .where(Invoice.user_id == user_id, Invoice.status.in_(statuses))
        )).scalar_one()
    return (await count(InvoiceStatus.PENDING, InvoiceStatus.AWAITING_REVIEW),
            await count(InvoiceStatus.PAID))


async def recent_transactions(session: AsyncSession, user_id: int, limit: int = 10):
    return (await session.execute(
        select(WalletTransaction).where(WalletTransaction.user_id == user_id)
        .order_by(WalletTransaction.id.desc()).limit(limit)
    )).scalars().all()
