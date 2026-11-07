"""
Atomic wallet operations. Call inside a transaction (session_scope()).
Every change: row lock on the wallet -> balance check -> ledger row. The idempotency key
makes repeated calls (double click, retry, restart) harmless.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.errors import InsufficientFunds, NotFound
from database.models import TxType, Wallet, WalletTransaction

_DEBIT_TYPES = {TxType.PURCHASE, TxType.ADMIN_SUB}


@dataclass
class WalletResult:
    tx: WalletTransaction
    duplicate: bool


async def apply_wallet_change(
    session: AsyncSession,
    *,
    user_id: int,
    delta: int,
    tx_type: TxType,
    idempotency_key: str,
    ref_type: str | None = None,
    ref_id: int | None = None,
    description: str | None = None,
    admin_telegram_id: int | None = None,
) -> WalletResult:
    if delta == 0:
        raise ValueError("delta must be non-zero")
    if (tx_type in _DEBIT_TYPES) != (delta < 0):
        raise ValueError(f"sign of delta does not match type {tx_type.value}")

    existing = (await session.execute(
        select(WalletTransaction).where(WalletTransaction.idempotency_key == idempotency_key)
    )).scalar_one_or_none()
    if existing:
        return WalletResult(existing, duplicate=True)

    wallet = (await session.execute(
        select(Wallet).where(Wallet.user_id == user_id).with_for_update()
    )).scalar_one_or_none()
    if wallet is None:
        raise NotFound("wallet not found")

    new_balance = wallet.balance + delta
    if new_balance < 0:
        raise InsufficientFunds()

    wallet.balance = new_balance
    if delta > 0 and tx_type in (TxType.CHARGE, TxType.ADMIN_ADD):
        wallet.total_charged += delta
    if tx_type == TxType.PURCHASE:
        wallet.total_spent += -delta
    if tx_type == TxType.REFUND:
        wallet.total_spent = max(0, wallet.total_spent - delta)

    tx = WalletTransaction(
        user_id=user_id, type=tx_type, amount=delta, balance_after=new_balance,
        idempotency_key=idempotency_key, ref_type=ref_type, ref_id=ref_id,
        description=description, admin_telegram_id=admin_telegram_id,
    )
    session.add(tx)
    await session.flush()
    return WalletResult(tx, duplicate=False)
