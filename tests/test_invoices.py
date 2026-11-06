import pytest
from sqlalchemy import select

from backend.services.errors import AlreadyReviewed, NoFreeAmount
from backend.services.invoices import create_invoice, review_receipt, submit_receipt
from database.models import InvoiceKind, InvoiceStatus, User, Wallet


async def _more_users(session, n):
    ids = []
    for i in range(n):
        u = User(telegram_id=1000 + i)
        session.add(u)
        await session.flush()
        session.add(Wallet(user_id=u.id))
        ids.append(u.id)
    await session.flush()
    return ids


async def test_unique_payable_amounts(session):
    ids = await _more_users(session, 5)
    amounts = set()
    for uid in ids:
        inv = await create_invoice(session, user_id=uid, kind=InvoiceKind.WALLET_CHARGE,
                                   base_amount=59500, extra_min=1, extra_max=99)
        amounts.add(inv.payable_amount)
    assert len(amounts) == 5
    assert all(59501 <= a <= 59599 for a in amounts)


async def test_range_exhausted(session):
    ids = await _more_users(session, 3)
    await create_invoice(session, user_id=ids[0], kind=InvoiceKind.WALLET_CHARGE, base_amount=1000, extra_min=1, extra_max=2)
    await create_invoice(session, user_id=ids[1], kind=InvoiceKind.WALLET_CHARGE, base_amount=1000, extra_min=1, extra_max=2)
    with pytest.raises(NoFreeAmount):
        await create_invoice(session, user_id=ids[2], kind=InvoiceKind.WALLET_CHARGE, base_amount=1000, extra_min=1, extra_max=2)


async def test_approve_once_and_credits_base_only(session, user):
    inv = await create_invoice(session, user_id=user.id, kind=InvoiceKind.WALLET_CHARGE,
                               base_amount=50000, extra_min=10, extra_max=50)
    r = await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="f", file_unique_id="u1")
    await review_receipt(session, receipt_id=r.id, admin_telegram_id=7, approve=True)
    bal = (await session.execute(select(Wallet.balance).where(Wallet.user_id == user.id))).scalar_one()
    assert bal == 50000                       # extra is NOT credited
    assert inv.status == InvoiceStatus.PAID
    with pytest.raises(AlreadyReviewed):      # second approval blocked
        await review_receipt(session, receipt_id=r.id, admin_telegram_id=7, approve=True)
    bal2 = (await session.execute(select(Wallet.balance).where(Wallet.user_id == user.id))).scalar_one()
    assert bal2 == 50000


async def test_reject_keeps_invoice_active_for_resend(session, user):
    inv = await create_invoice(session, user_id=user.id, kind=InvoiceKind.WALLET_CHARGE,
                               base_amount=20000, extra_min=1, extra_max=9)
    r = await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="f", file_unique_id="u2")
    await review_receipt(session, receipt_id=r.id, admin_telegram_id=7, approve=False, reason="مبلغ نادرست")
    assert inv.status == InvoiceStatus.PENDING
    r2 = await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="g", file_unique_id="u3")
    assert r2.id != r.id
