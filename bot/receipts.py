import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

from bot.utils import fmt_dt, fmt_money
from config.settings import get_settings
from database.models import Invoice, Receipt, User

log = logging.getLogger(__name__)


def admin_caption(receipt: Receipt, inv: Invoice, user: User) -> str:
    name = " ".join(x for x in (user.first_name, user.last_name) if x) or "—"
    return (
        f"🧾 رسید جدید — فاکتور #{inv.id}\n\n"
        f"👤 نام: {name}\n"
        f"🔗 یوزرنیم: {('@' + user.username) if user.username else '—'}\n"
        f"🆔 آیدی تلگرام: {user.telegram_id}\n\n"
        f"💰 مبلغ شارژ (به کیف پول): {fmt_money(inv.base_amount)} تومان\n"
        f"🔢 مبلغ قابل پرداخت (با مبلغ اختصاصی): {fmt_money(inv.payable_amount)} تومان\n"
        f"🕐 زمان ارسال رسید: {fmt_dt(receipt.created_at)}\n"
        f"📌 شماره رسید: {receipt.id}\n\n"
        "مبلغ واریزی را با حساب بانکی خود تطبیق دهید و بعد تأیید کنید."
    )


def admin_kb(receipt_id: int) -> Kb:
    return Kb(inline_keyboard=[[
        Btn(text="✅ تأیید پرداخت", callback_data=f"rcpt:ok:{receipt_id}"),
        Btn(text="❌ رد پرداخت", callback_data=f"rcpt:no:{receipt_id}"),
    ]])


async def send_receipt_to_admins(bot: Bot, receipt: Receipt, inv: Invoice, user: User) -> int:
    sent = 0
    for admin_id in get_settings().admin_telegram_ids:
        try:
            await bot.send_photo(admin_id, receipt.telegram_file_id,
                                 caption=admin_caption(receipt, inv, user), reply_markup=admin_kb(receipt.id))
            sent += 1
        except Exception as e:
            log.warning("Could not send receipt %s to admin %s: %s", receipt.id, admin_id, e)
    return sent


async def send_pending(bot: Bot, session, chat_id: int, limit: int = 10) -> int:
    from sqlalchemy import select

    from backend.services.payments import get_receipt_bundle
    from database.models import ReceiptStatus

    ids = (await session.execute(
        select(Receipt.id).where(Receipt.status == ReceiptStatus.PENDING).order_by(Receipt.id).limit(limit)
    )).scalars().all()
    for rid in ids:
        receipt, inv, user = await get_receipt_bundle(session, rid)
        await bot.send_photo(chat_id, receipt.telegram_file_id,
                             caption=admin_caption(receipt, inv, user), reply_markup=admin_kb(rid))
    return len(ids)
