import pytest

from backend.services.errors import InsufficientFunds
from backend.services.wallet import apply_wallet_change
from database.models import TxType, Wallet
from sqlalchemy import select


async def _bal(session, uid):
    return (await session.execute(select(Wallet.balance).where(Wallet.user_id == uid))).scalar_one()


async def test_credit_and_debit(session, user):
    await apply_wallet_change(session, user_id=user.id, delta=10000, tx_type=TxType.CHARGE, idempotency_key="a")
    await apply_wallet_change(session, user_id=user.id, delta=-4000, tx_type=TxType.PURCHASE, idempotency_key="b")
    assert await _bal(session, user.id) == 6000


async def test_insufficient_funds(session, user):
    with pytest.raises(InsufficientFunds):
        await apply_wallet_change(session, user_id=user.id, delta=-1, tx_type=TxType.PURCHASE, idempotency_key="x")
    assert await _bal(session, user.id) == 0


async def test_idempotent(session, user):
    r1 = await apply_wallet_change(session, user_id=user.id, delta=5000, tx_type=TxType.CHARGE, idempotency_key="same")
    r2 = await apply_wallet_change(session, user_id=user.id, delta=5000, tx_type=TxType.CHARGE, idempotency_key="same")
    assert not r1.duplicate and r2.duplicate
    assert await _bal(session, user.id) == 5000


async def test_sign_mismatch(session, user):
    with pytest.raises(ValueError):
        await apply_wallet_change(session, user_id=user.id, delta=100, tx_type=TxType.PURCHASE, idempotency_key="z")
