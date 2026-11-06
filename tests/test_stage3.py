import pytest
from datetime import timedelta
from sqlalchemy import select

from backend.services.errors import NotFound
from backend.services.invoices import create_invoice, review_receipt, submit_receipt
from backend.services.payments import cancel_open_charge_invoices, get_receipt_bundle, invoice_counts
from bot.utils import fmt_card, parse_amount
from database.base import utcnow
from database.models import Invoice, InvoiceKind, InvoiceStatus


def test_parse_amount():
    assert parse_amount("50000") == 50000
    assert parse_amount("۵۰,۰۰۰") == 50000
    assert parse_amount("٥٠ ٠٠٠") == 50000
    assert parse_amount("abc") is None
    assert parse_amount("-5") is None
    assert parse_amount("") is None
    assert parse_amount("1" * 20) is None


def test_fmt_card():
    assert fmt_card("6219861987115929") == "6219 8619 8711 5929"


async def _inv(session, user, amount=30000):
    return await create_invoice(session, user_id=user.id, kind=InvoiceKind.WALLET_CHARGE,
                                base_amount=amount, extra_min=1, extra_max=99)


async def test_no_second_receipt_while_under_review(session, user):
    inv = await _inv(session, user)
    await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="a", file_unique_id="u1")
    with pytest.raises(NotFound):
        await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="b", file_unique_id="u2")


async def test_expired_invoice_rejects_receipt(session, user):
    inv = await _inv(session, user)
    inv.expires_at = utcnow() - timedelta(minutes=1)
    with pytest.raises(NotFound):
        await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="a", file_unique_id="u1")
    assert inv.status == InvoiceStatus.EXPIRED


async def test_cancel_frees_amount(session, user):
    inv = await _inv(session, user)
    await cancel_open_charge_invoices(session, user.id)
    await session.refresh(inv)
    assert inv.status == InvoiceStatus.CANCELED


async def test_other_user_cannot_submit(session, user):
    inv = await _inv(session, user)
    with pytest.raises(NotFound):
        await submit_receipt(session, invoice_id=inv.id, user_id=user.id + 99, file_id="a", file_unique_id="u1")


async def test_bundle_and_counts(session, user):
    inv = await _inv(session, user)
    r = await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="a", file_unique_id="u1")
    rec, i, u = await get_receipt_bundle(session, r.id)
    assert i.id == inv.id and u.id == user.id
    assert await invoice_counts(session, user.id) == (1, 0)
    await review_receipt(session, receipt_id=r.id, admin_telegram_id=1, approve=True)
    assert await invoice_counts(session, user.id) == (0, 1)


async def test_reject_extends_expiry(session, user):
    inv = await _inv(session, user)
    inv.expires_at = utcnow() + timedelta(minutes=1)
    r = await submit_receipt(session, invoice_id=inv.id, user_id=user.id, file_id="a", file_unique_id="u1")
    await review_receipt(session, receipt_id=r.id, admin_telegram_id=1, approve=False, reason="x")
    assert inv.expires_at > utcnow() + timedelta(minutes=20)
