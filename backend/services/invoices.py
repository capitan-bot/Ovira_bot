import random
from datetime import timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.errors import AlreadyReviewed, NoFreeAmount, NotFound
from backend.services.wallet import apply_wallet_change
from database.base import utcnow
from database.models import (
    ACTIVE_INVOICE_STATUSES, Invoice, InvoiceKind, InvoiceStatus, Receipt, ReceiptStatus, TxType,
)


async def create_invoice(
    session: AsyncSession, *, user_id: int, kind: InvoiceKind, base_amount: int,
    extra_min: int, extra_max: int, ttl_minutes: int = 60, order_id: int | None = None,
    max_attempts: int = 60,
) -> Invoice:
    """
    Reserves a unique payable amount (base + random extra). Uniqueness among active invoices is
    enforced by the DB partial unique index, so concurrent requests can't collide.
    """
    if extra_min < 0 or extra_max < extra_min:
        raise ValueError("invalid extra range")
    candidates = list(range(extra_min, extra_max + 1))
    random.shuffle(candidates)
    for extra in candidates[:max_attempts]:
        inv = Invoice(
            user_id=user_id, kind=kind, order_id=order_id, base_amount=base_amount,
            unique_extra=extra, payable_amount=base_amount + extra,
            status=InvoiceStatus.PENDING, expires_at=utcnow() + timedelta(minutes=ttl_minutes),
        )
        try:
            async with session.begin_nested():
                session.add(inv)
                await session.flush()
            return inv
        except IntegrityError:
            continue
    raise NoFreeAmount()


async def expire_old_invoices(session: AsyncSession) -> int:
    """Frees reserved amounts of unpaid invoices whose time ran out (called by a worker)."""
    res = await session.execute(
        update(Invoice)
        .where(Invoice.status == InvoiceStatus.PENDING, Invoice.expires_at < utcnow())
        .values(status=InvoiceStatus.EXPIRED)
    )
    return res.rowcount or 0


async def submit_receipt(
    session: AsyncSession, *, invoice_id: int, user_id: int, file_id: str, file_unique_id: str | None,
) -> Receipt:
    inv = (await session.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user_id).with_for_update()
    )).scalar_one_or_none()
    if inv is None or inv.status != InvoiceStatus.PENDING:
        raise NotFound("invoice not open for a receipt")
    exp = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=timezone.utc)
    if exp < utcnow():
        inv.status = InvoiceStatus.EXPIRED
        await session.flush()
        raise NotFound("invoice expired")
    receipt = Receipt(invoice_id=inv.id, user_id=user_id, telegram_file_id=file_id,
                      telegram_file_unique_id=file_unique_id)
    session.add(receipt)
    inv.status = InvoiceStatus.AWAITING_REVIEW
    await session.flush()
    return receipt


async def review_receipt(
    session: AsyncSession, *, receipt_id: int, admin_telegram_id: int,
    approve: bool, reason: str | None = None,
) -> Receipt:
    """
    Single guarded UPDATE: only a receipt still in 'pending' can change state, so a second click,
    a second admin, or a retry gets AlreadyReviewed and can never credit twice. On approval of a
    wallet-charge invoice only `base_amount` is credited (the random extra is never credited).
    """
    claimed = await session.execute(
        update(Receipt)
        .where(Receipt.id == receipt_id, Receipt.status == ReceiptStatus.PENDING)
        .values(
            status=ReceiptStatus.APPROVED if approve else ReceiptStatus.REJECTED,
            reviewed_by=admin_telegram_id, reviewed_at=utcnow(),
            reject_reason=None if approve else (reason or ""),
        )
        .returning(Receipt.id)
    )
    if claimed.scalar_one_or_none() is None:
        raise AlreadyReviewed()

    receipt = (await session.execute(select(Receipt).where(Receipt.id == receipt_id))).scalar_one()
    inv = (await session.execute(
        select(Invoice).where(Invoice.id == receipt.invoice_id).with_for_update()
    )).scalar_one()

    if approve:
        inv.status = InvoiceStatus.PAID
        inv.paid_at = utcnow()
        if inv.kind == InvoiceKind.WALLET_CHARGE:
            await apply_wallet_change(
                session, user_id=inv.user_id, delta=inv.base_amount, tx_type=TxType.CHARGE,
                idempotency_key=f"invoice:{inv.id}:credit", ref_type="invoice", ref_id=inv.id,
                description=f"شارژ کیف پول - فاکتور #{inv.id}", admin_telegram_id=admin_telegram_id,
            )
    else:
        # Rejected: customer may resend a receipt for the same invoice (stays active) until it expires.
        inv.status = InvoiceStatus.PENDING
        inv.expires_at = utcnow() + timedelta(minutes=30)   # time to resend a correct receipt
    await session.flush()
    return receipt
