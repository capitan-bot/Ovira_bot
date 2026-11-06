"""Admin review of card-to-card receipts. Money moves ONLY here, after an admin presses approve."""
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from backend.services.errors import AlreadyReviewed
from backend.services.invoices import review_receipt
from backend.services.payments import get_receipt_bundle
from backend.services.settings_service import get_settings_map
from backend.services.users import audit, get_wallet
from bot.filters import AdminOnly
from bot.keyboards.menus import resend_kb, back_kb
from bot.receipts import admin_caption, admin_kb
from bot.states.states import AdminStates
from bot.utils import fmt_money, safe_format
from database.models import Receipt, ReceiptStatus

log = logging.getLogger(__name__)
router = Router()


async def _strip_buttons(cb: CallbackQuery, suffix: str):
    try:
        await cb.message.edit_caption(caption=(cb.message.caption or "") + suffix, reply_markup=None)
    except Exception as e:  # message too old / unchanged: not critical
        log.debug("edit_caption failed: %s", e)


@router.callback_query(F.data.startswith("rcpt:ok:"), AdminOnly())
async def approve(cb: CallbackQuery, session, bot: Bot):
    rid = int(cb.data.rsplit(":", 1)[1])
    try:
        await review_receipt(session, receipt_id=rid, admin_telegram_id=cb.from_user.id, approve=True)
    except AlreadyReviewed:
        await cb.answer("این رسید قبلاً بررسی شده است.", show_alert=True)
        await _strip_buttons(cb, "\n\nℹ️ قبلاً بررسی شده")
        return
    await audit(session, f"admin:{cb.from_user.id}", "receipt.approve", target=f"receipt:{rid}")
    _, inv, user = await get_receipt_bundle(session, rid)
    wallet = await get_wallet(session, user.id)
    cfg = await get_settings_map(session, ["payment_success_text"])
    text = safe_format(cfg["payment_success_text"] or "✅ پرداخت شما تأیید شد.")
    await _strip_buttons(cb, f"\n\n✅ تأیید شد توسط {cb.from_user.id}")
    await cb.answer("تأیید شد ✅")
    try:
        await bot.send_message(
            user.telegram_id,
            f"{text}\n\n➕ مبلغ شارژ: {fmt_money(inv.base_amount)} تومان\n"
            f"💰 موجودی جدید: {fmt_money(wallet.balance)} تومان",
            reply_markup=back_kb("menu:wallet"),
        )
    except Exception as e:
        log.warning("Could not notify user %s: %s", user.telegram_id, e)


@router.callback_query(F.data.startswith("rcpt:no:"), AdminOnly())
async def reject_start(cb: CallbackQuery, session, state: FSMContext):
    rid = int(cb.data.rsplit(":", 1)[1])
    status = (await session.execute(select(Receipt.status).where(Receipt.id == rid))).scalar_one_or_none()
    if status != ReceiptStatus.PENDING:
        await cb.answer("این رسید قبلاً بررسی شده است.", show_alert=True)
        await _strip_buttons(cb, "\n\nℹ️ قبلاً بررسی شده")
        return
    await state.set_state(AdminStates.reject_reason)
    await state.update_data(receipt_id=rid)
    await cb.message.answer(f"✍️ دلیل رد رسید #{rid} را بنویسید و بفرستید.\n(انصراف: /cancel)")
    await cb.answer()


@router.message(AdminStates.reject_reason, F.text, ~F.text.startswith("/"), AdminOnly())
async def reject_finish(message: Message, session, state: FSMContext, bot: Bot):
    data = await state.get_data()
    rid = data["receipt_id"]
    reason = message.text.strip()[:500]
    await state.clear()
    try:
        await review_receipt(session, receipt_id=rid, admin_telegram_id=message.from_user.id,
                             approve=False, reason=reason)
    except AlreadyReviewed:
        await message.answer("ℹ️ این رسید در همین فاصله بررسی شد و دیگر قابل رد نیست.")
        return
    await audit(session, f"admin:{message.from_user.id}", "receipt.reject", target=f"receipt:{rid}",
                details={"reason": reason})
    _, inv, user = await get_receipt_bundle(session, rid)
    cfg = await get_settings_map(session, ["payment_failed_text"])
    text = safe_format(cfg["payment_failed_text"] or "❌ پرداخت شما تأیید نشد.\nدلیل: {reason}", reason=reason)
    await message.answer(f"❌ رسید #{rid} رد شد و دلیل برای مشتری ارسال شد.")
    try:
        await bot.send_message(
            user.telegram_id,
            f"{text}\n\nاگر واریز را انجام داده‌اید، می‌توانید رسید درست را دوباره ارسال کنید.",
            reply_markup=resend_kb(inv.id),
        )
    except Exception as e:
        log.warning("Could not notify user %s: %s", user.telegram_id, e)


@router.callback_query(F.data.startswith("rate_star:"))
async def handle_star_rating(cb: CallbackQuery):
    stars = cb.data.split(":")[1]
    await cb.answer("❤️ ممنون از لطف شما!", show_alert=True)
    try:
        await cb.message.edit_text(f"❤️ ممنون از لطف شما! (امتیاز ثبت‌شده شما: {stars} ⭐️)")
    except Exception:
        pass
