"""My services: list, usage, refresh from the panel, and (re)download of the config files.
Management actions (renew, new link, on/off, QR, delete) live in service_actions.py."""
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from adapters.base import PanelError
from backend.services.shop import adapter_for, apply_remote, unpack_files, user_services
from bot.delivery import send_files
from bot.keyboards.shop import kb
from bot.service_view import STATUS, detail
from bot.utils import edit_or_answer, fmt_dt
from database.models import Panel, Service, ServiceStatus

log = logging.getLogger(__name__)
router = Router()


async def _mine(session, sid: int, user_id: int) -> Service | None:
    svc = await session.get(Service, sid)
    return svc if svc and svc.user_id == user_id and svc.status != ServiceStatus.DELETED else None


@router.callback_query(F.data == "menu:services")
async def services_list(cb: CallbackQuery, session, state: FSMContext, db_user):
    await state.clear()
    items = await user_services(session, db_user.id)
    if not items:
        await edit_or_answer(cb, "📦 سرویس‌های من\n\nهنوز سرویسی ندارید.",
                             kb([("🛒 خرید اشتراک", "menu:buy"), ("🎁 تست رایگان", "menu:test")],
                                [("🔙 بازگشت", "menu:main")]))
        await cb.answer()
        return
    rows = [[(f"{STATUS.get(s.status, '')[:1]} {s.username}{' (تست)' if s.is_test else ''} · تا {fmt_dt(s.expires_at)[:10]}",
              f"svc:v:{s.id}")] for s in items]
    await edit_or_answer(cb, "📦 سرویس‌های من\n\nیکی را انتخاب کنید:", kb(*rows, [("🔙 بازگشت", "menu:main")]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^svc:v:\d+$"))
async def service_view(cb: CallbackQuery, session, state: FSMContext, db_user):
    await state.clear()
    svc = await _mine(session, int(cb.data.split(":")[2]), db_user.id)
    if svc is None:
        await cb.answer("سرویس پیدا نشد.", show_alert=True)
        return
    panel = await session.get(Panel, svc.panel_id)
    text, markup = detail(svc, panel.display_name if panel else "—")
    await edit_or_answer(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^svc:r:\d+$"))
async def service_refresh(cb: CallbackQuery, session, db_user):
    svc = await _mine(session, int(cb.data.split(":")[2]), db_user.id)
    if svc is None:
        await cb.answer("سرویس پیدا نشد.", show_alert=True)
        return
    panel = await session.get(Panel, svc.panel_id)
    try:
        remote = await adapter_for(panel).get_user(svc.username)
    except PanelError as e:
        log.warning("refresh of service %s failed: %s", svc.id, e)
        svc.last_sync_error = str(e)[:500]
        await cb.answer("به‌روزرسانی از سرور ممکن نشد. کمی بعد دوباره امتحان کنید.", show_alert=True)
        return
    apply_remote(svc, remote)
    text, markup = detail(svc, panel.display_name)
    await edit_or_answer(cb, text, markup)
    await cb.answer("به‌روز شد ✅")


@router.callback_query(F.data.regexp(r"^svc:c:\d+$"))
async def service_config(cb: CallbackQuery, session, db_user, bot: Bot):
    svc = await _mine(session, int(cb.data.split(":")[2]), db_user.id)
    if svc is None:
        await cb.answer("سرویس پیدا نشد.", show_alert=True)
        return
    panel = await session.get(Panel, svc.panel_id)
    files, link = [], svc.subscription_link
    try:                                    # the panel is the source of truth
        remote = await adapter_for(panel).get_user(svc.username)
        files, link = remote.config_files, remote.subscription_link or link
        apply_remote(svc, remote)
    except PanelError as e:
        log.warning("config fetch for service %s failed: %s", svc.id, e)
        files = unpack_files(svc.config_blob_enc)      # fall back to the copy saved at purchase time
    await cb.answer()
    if not await send_files(bot, cb.message.chat.id, files, link):
        await cb.message.answer("⚠️ الان دریافت کانفیگ ممکن نیست. کمی بعد دوباره امتحان کنید یا به پشتیبانی پیام بدهید.")
