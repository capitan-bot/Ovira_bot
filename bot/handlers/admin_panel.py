"""Admin home, stats, bot on/off, pending receipts."""
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from backend.services.admin_stats import global_stats
from backend.services.settings_service import get_setting, set_setting
from backend.services.users import audit
from bot.filters import AdminOnly
from bot.keyboards.admin import home_kb, kb
from bot.receipts import send_pending
from bot.utils import edit_or_answer, fmt_money

router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())


async def _home(session):
    on = (await get_setting(session, "bot_enabled", "1")) != "0"
    text = ("🛠 پنل مدیریت CAPITAN VPN\n\n"
            f"وضعیت ربات: {'🟢 روشن' if on else '🔴 خاموش (کاربران پیام تعمیرات می‌بینند)'}\n\n"
            "یکی از بخش‌ها را انتخاب کنید:")
    return text, home_kb(on)


@router.message(Command("admin"))
async def cmd_admin(message: Message, session, state: FSMContext):
    await state.clear()
    text, markup = await _home(session)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:home")
async def home(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    text, markup = await _home(session)
    await edit_or_answer(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data == "adm:stats")
async def stats(cb: CallbackQuery, session):
    s = await global_stats(session)
    text = (
        "📊 آمار ربات\n\n"
        f"👥 کاربران: {s['users']:,}  (مسدود: {s['blocked']:,})\n"
        f"🆕 عضو جدید ۲۴ ساعت اخیر: {s['new24']:,}\n\n"
        f"💰 مجموع موجودی کیف پول‌ها: {fmt_money(s['wallet_sum'])} تومان\n"
        f"➕ مجموع شارژهای تأییدشده: {fmt_money(s['charged_sum'])} تومان\n"
        f"🧾 رسیدهای در انتظار بررسی: {s['pending_receipts']}\n\n"
        f"🛍 خریدهای تکمیل‌شده: {s['orders_done']:,}\n"
        f"💵 مجموع فروش: {fmt_money(s['sales_sum'])} تومان\n"
        f"📦 سرویس‌ها: {s['services']:,}  (فعال: {s['services_active']:,})\n"
        f"🎁 تست‌های داده‌شده: {s['tests']:,}\n"
        f"🛰 پنل‌های ثبت‌شده: {s['panels']}"
    )
    await edit_or_answer(cb, text, kb([("🔄 به‌روزرسانی", "adm:stats")], [("🔙 پنل مدیریت", "adm:home")]))
    await cb.answer()


@router.callback_query(F.data == "adm:bot")
async def toggle_bot(cb: CallbackQuery, session, state: FSMContext):
    on = (await get_setting(session, "bot_enabled", "1")) != "0"
    await set_setting(session, "bot_enabled", "0" if on else "1")
    await audit(session, f"admin:{cb.from_user.id}", "bot.toggle", details={"enabled": not on})
    text, markup = await _home(session)
    await edit_or_answer(cb, text, markup)
    await cb.answer("ربات خاموش شد ⏸" if on else "ربات روشن شد ▶️")


@router.callback_query(F.data == "adm:rc")
async def receipts(cb: CallbackQuery, session, bot: Bot):
    n = await send_pending(bot, session, cb.message.chat.id)
    await cb.answer("رسید در انتظار بررسی وجود ندارد ✅" if n == 0 else f"{n} رسید ارسال شد", show_alert=(n == 0))
