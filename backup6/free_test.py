"""Free test account: one tap, limited per Telegram id, created on the panel chosen by the admin."""
import logging
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from adapters.base import CreateUserRequest, PanelError, UsernameTaken
from backend.services.errors import DomainError
from backend.services.shop import (
    GB, TestLimitReached, adapter_for, cancel_test, complete_test, get_test_target, inbound_ids,
    reserve_test, test_count,
)
from backend.services.users import audit
from bot.delivery import notify_admins, send_files, user_lock
from bot.keyboards.shop import kb
from bot.utils import edit_or_answer, fmt_dt
from database.base import utcnow
from database.connection import session_scope

log = logging.getLogger(__name__)
router = Router()
BACK = [("\U0001f519 بازگشت", "menu:main")]


def _gb_text(gb: float) -> str:
    return f"{gb:g}"


@router.callback_query(F.data == "menu:test")
async def test_start(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    try:
        t = await get_test_target(session)
    except DomainError as e:
        await edit_or_answer(cb, str(e), kb(BACK))
        await cb.answer()
        return
    used = await test_count(session, cb.from_user.id)
    left = t["max_per_user"] - used
    if left <= 0:
        await edit_or_answer(cb, "\U0001f381 تست رایگان\n\nشما از سهمیه تست رایگان خود استفاده کرده\u200cاید.", kb(BACK))
        await cb.answer()
        return
    await edit_or_answer(
        cb,
        "\U0001f381 تست رایگان\n\n"
        f"\U0001f4be حجم: {_gb_text(t['gb'])} گیگابایت\n"
        f"\u23f1 مدت: {t['hours']} ساعت\n"
        f"\U0001f501 تعداد تست باقی\u200cمانده برای شما: {left}\n\n"
        "برای دریافت تست\u060c دکمه زیر را بزنید.",
        kb([("\U0001f381 دریافت تست رایگان", "test:go")], BACK),
    )
    await cb.answer()


@router.callback_query(F.data == "test:go")
async def test_go(cb: CallbackQuery, session, db_user, bot: Bot):
    lock = user_lock(db_user.id)
    if lock.locked():
        await cb.answer("درخواست شما در حال پردازش است.", show_alert=True)
        return
    async with lock:
        await cb.answer()
        try:
            t = await get_test_target(session)
        except DomainError as e:
            await edit_or_answer(cb, str(e), kb(BACK))
            return
        try:
            async with session_scope() as s:
                ft, n = await reserve_test(s, user_id=db_user.id, telegram_id=cb.from_user.id,
                                           max_per_user=t["max_per_user"])
                ft_id = ft.id
        except TestLimitReached:
            await edit_or_answer(cb, "\U0001f381 شما از سهمیه تست رایگان خود استفاده کرده\u200cاید.", kb(BACK))
            return

        username = f"test_{cb.from_user.id}_{n}"
        panel, profile = t["panel"], t["profile"]
        total = int(t["gb"] * GB)
        await edit_or_answer(cb, "\u23f3 در حال ساخت تست ...", None)
        adapter = adapter_for(panel)
        attempted = False
        try:
            if await adapter.username_exists(username):
                raise UsernameTaken(f"user name '{username}' already exists on the panel")
            attempted = True
            remote = await adapter.create_user(CreateUserRequest(
                username=username, total_bytes=total, expires_at=utcnow() + timedelta(hours=t["hours"]),
                inbound_ids=inbound_ids(profile), settings=dict(profile.settings or {})))
        except Exception as e:  # noqa: BLE001
            err = str(e) if isinstance(e, PanelError) else f"{type(e).__name__}: {e}"
            log.exception("free test for %s failed", cb.from_user.id)
            if attempted and not isinstance(e, UsernameTaken):
                try:
                    await adapter.delete_user(username)
                except Exception as ce:  # noqa: BLE001
                    log.warning("cleanup of %s failed: %s", username, ce)
            try:
                async with session_scope() as s:
                    await cancel_test(s, ft_id)       # the attempt is given back
            except Exception:  # noqa: BLE001
                log.exception("could not release test attempt %s", ft_id)
            await edit_or_answer(cb, "\u274c ساخت تست انجام نشد. سهمیه شما مصرف نشد\u061b کمی بعد دوباره تلاش کنید.", kb(BACK))
            await notify_admins(bot, f"\u26a0\ufe0f ساخت تست رایگان ناموفق بود\nکاربر {cb.from_user.id} | پنل {panel.display_name}\nخطا: {err[:400]}")
            return

        expires = remote.expires_at
        try:
            async with session_scope() as s:
                svc = await complete_test(s, ft_id, panel_id=panel.id, profile_id=profile.id, username=username,
                                          total_bytes=total, hours=t["hours"], remote=remote)
                await audit(s, f"user:{cb.from_user.id}", "test.created", target=f"service:{svc.id}")
                expires = svc.expires_at
        except Exception:  # noqa: BLE001
            log.exception("test service exists on the panel but could not be saved")
            await notify_admins(bot, f"\U0001f6a8 تست روی پنل ساخته شد ولی در دیتابیس ثبت نشد!\nکاربر {cb.from_user.id} | "
                                     f"پنل {panel.display_name} | نام کاربری {username}")
        await edit_or_answer(
            cb,
            "\U0001f389 تست رایگان شما ساخته شد!\n\n"
            f"\U0001f464 نام کاربری: {username}\n\U0001f4be حجم: {_gb_text(t['gb'])} گیگابایت\n\u23f3 انقضا: {fmt_dt(expires)}",
            kb([("\U0001f4e6 سرویس\u200cهای من", "menu:services")], [("\U0001f3e0 منو", "menu:main")]),
        )
        if not await send_files(bot, cb.message.chat.id, remote.config_files, remote.subscription_link):
            await bot.send_message(cb.message.chat.id, "\u2139\ufe0f سرور فایل کانفیگ برنگرداند. از \u00abسرویس\u200cهای من\u00bb دوباره امتحان کنید.")
