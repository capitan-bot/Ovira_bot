from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from backend.services.payments import invoice_counts, recent_transactions
from backend.services.users import get_wallet
from bot.keyboards.menus import back_kb, wallet_kb
from bot.utils import edit_or_answer, fmt_dt, fmt_money

router = Router()

# Sections implemented in later stages. We say so honestly instead of faking them.
_COMING = {
    "menu:buy": "🛒 خرید اشتراک",
    "menu:test": "🎁 تست رایگان",
    "menu:services": "📦 سرویس‌های من",
    "menu:support": "🎧 پشتیبانی",
}

_TX_LABEL = {
    "charge": "شارژ", "purchase": "خرید", "refund": "بازگشت وجه",
    "admin_add": "افزایش توسط مدیر", "admin_sub": "کاهش توسط مدیر", "referral": "پاداش معرفی",
}


@router.callback_query(F.data.in_(_COMING.keys()))
async def coming_soon(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_or_answer(cb, f"{_COMING[cb.data]}\n\n🚧 این بخش هنوز فعال نشده است.", back_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:wallet")
async def wallet(cb: CallbackQuery, session, db_user, state: FSMContext):
    await state.clear()
    w = await get_wallet(session, db_user.id)
    unpaid, paid = await invoice_counts(session, db_user.id)
    text = (
        "💳 کیف پول من\n\n"
        f"💰 موجودی: {fmt_money(w.balance)} تومان\n"
        f"➕ مجموع شارژها: {fmt_money(w.total_charged)} تومان\n"
        f"🛍 مجموع خریدها: {fmt_money(w.total_spent)} تومان\n"
        f"🧾 فاکتورهای پرداخت‌نشده: {unpaid}\n"
        f"✅ فاکتورهای تأییدشده: {paid}"
    )
    await edit_or_answer(cb, text, wallet_kb())
    await cb.answer()


@router.callback_query(F.data == "wallet:history")
async def history(cb: CallbackQuery, session, db_user):
    txs = await recent_transactions(session, db_user.id)
    if not txs:
        body = "هنوز تراکنشی ثبت نشده است."
    else:
        body = "\n".join(
            f"{'➕' if t.amount > 0 else '➖'} {fmt_money(abs(t.amount))} تومان — {_TX_LABEL.get(t.type.value, t.type.value)}\n"
            f"   {fmt_dt(t.created_at)} | موجودی: {fmt_money(t.balance_after)}"
            for t in txs
        )
    await edit_or_answer(cb, f"📜 ۱۰ تراکنش آخر\n\n{body}", back_kb("menu:wallet"))
    await cb.answer()
