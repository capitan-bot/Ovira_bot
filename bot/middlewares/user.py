import asyncio

from aiogram import BaseMiddleware
from aiogram.types import Update

from backend.services.settings_service import get_setting
from backend.services.users import get_or_create_user
from bot.logger_group import notify_log
from config.settings import get_settings


class UserMiddleware(BaseMiddleware):
    """Registers the user on first contact, flags admins, and stops blocked users."""

    async def __call__(self, handler, event: Update, data):
        tg = data.get("event_from_user")
        if tg is None or tg.is_bot:
            return await handler(event, data)

        ref = None
        if event.message and event.message.text and event.message.text.startswith("/start ref_"):
            tail = event.message.text.split("ref_", 1)[1].strip()
            ref = int(tail) if tail.isdigit() else None

        session = data["session"]
        user, created = await get_or_create_user(
            session, telegram_id=tg.id, first_name=tg.first_name, last_name=tg.last_name,
            username=tg.username, referrer_telegram_id=ref,
        )
        bot = data.get("bot")
        if bot is not None:
            who = f"{tg.full_name} | {('@' + tg.username) if tg.username else '—'} | {tg.id}"
            before = getattr(user, "profile_before", None)
            if created:
                asyncio.create_task(notify_log(bot, "account", f"🆕 عضو جدید\n👤 {who}"))
            elif before:
                old_name = " ".join(x for x in before[:2] if x) or "—"
                old_un = ('@' + before[2]) if before[2] else "—"
                asyncio.create_task(notify_log(
                    bot, "account", f"✏️ تغییر مشخصات کاربر\nقبل: {old_name} | {old_un}\nبعد: {who}"))

        is_admin = tg.id in get_settings().admin_telegram_ids

        if user.is_blocked and not is_admin:
            text = "⛔️ حساب شما مسدود شده است. برای پیگیری با پشتیبانی تماس بگیرید."
            if event.callback_query:
                await event.callback_query.answer(text, show_alert=True)
            elif event.message:
                await event.message.answer(text)
            return None

        if not is_admin and (await get_setting(session, "bot_enabled", "1")) == "0":
            text = "🔧 ربات موقتاً در دسترس نیست. لطفاً کمی بعد دوباره تلاش کنید."
            if event.callback_query:
                await event.callback_query.answer(text, show_alert=True)
            elif event.message:
                await event.message.answer(text)
            return None

        data["db_user"] = user
        data["is_admin"] = is_admin
        return await handler(event, data)
