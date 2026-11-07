import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from backend.services.admin_stats import list_users, search_users, user_report
from backend.services.errors import InsufficientFunds
from backend.services.payments import recent_transactions
from backend.services.users import audit, get_wallet
from backend.services.wallet import apply_wallet_change
from bot.filters import AdminOnly, InputAction, not_command
from bot.handlers.menu import _TX_LABEL
from bot.keyboards.admin import kb
from bot.states.states import AdminStates
from bot.utils import edit_or_answer, fmt_dt, fmt_money, parse_amount
from config.settings import get_settings
from database.models import Panel, Service, TxType, User
from uuid import uuid4

log = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())
PER_PAGE = 8


def _name(u: User) -> str:
    return " ".join(x for x in (u.first_name, u.last_name) if x) or "بدون نام"


async def _ask(cb_or_msg, state: FSMContext, action: str, text: str, back: str, **data):
    await state.set_state(AdminStates.input)
    await state.set_data({"action": action, **data})
    markup = kb([("🔙 انصراف", back)])
    if isinstance(cb_or_msg, CallbackQuery):
        await edit_or_answer(cb_or_msg, text, markup)
        await cb_or_msg.answer()
    else:
        await cb_or_msg.answer(text, reply_markup=markup)


async def _card(session, uid: int):
    u = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if u is None:
        return "کاربر پیدا نشد.", kb([("🔙 کاربران", "adm:users")])
    r = await user_report(session, u)
    text = (
        f"👤 {_name(u)}\n"
        f"🔗 یوزرنیم: {('@' + u.username) if u.username else '—'}\n"
        f"🆔 آیدی تلگرام: {u.telegram_id}\n"
        f"📅 عضویت: {fmt_dt(u.created_at)}\n"
        f"وضعیت: {'🚫 مسدود' if u.is_blocked else '✅ فعال'}\n\n"
        f"💰 موجودی: {fmt_money(r['balance'])} تومان\n"
        f"➕ مجموع پرداخت (شارژ): {fmt_money(r['total_charged'])} تومان\n"
        f"🛍 مجموع خرید: {fmt_money(r['total_spent'])} تومان\n"
        f"🧾 تعداد خرید: {r['purchases']}\n"
        f"🎁 تست‌های گرفته‌شده: {r['tests']}\n"
        f"📦 سرویس‌ها: {r['services']} (فعال: {r['services_active']})"
    )
    markup = kb(
        [("➕ افزایش موجودی", f"adm:ua:{u.id}"), ("➖ کاهش موجودی", f"adm:us:{u.id}")],
        [("✅ رفع مسدودی" if u.is_blocked else "🚫 مسدود کردن", f"adm:ub:{u.id}"),
         ("✉️ ارسال پیام", f"adm:um:{u.id}")],
        [("📜 تراکنش‌ها", f"adm:ut:{u.id}"), ("📦 سرویس‌ها", f"adm:uv:{u.id}")],
        [("🔙 کاربران", "adm:users")],
    )
    return text, markup


async def _show_card(target, session, uid: int):
    text, markup = await _card(session, uid)
    if isinstance(target, CallbackQuery):
        await edit_or_answer(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


# ---------- menu / list / search ----------
@router.callback_query(F.data == "adm:users")
async def users_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_or_answer(cb, "👥 مدیریت کاربران", kb(
        [("🔎 جستجوی کاربر", "adm:usearch")],
        [("📋 همه کاربران", "adm:ul:all:0"), ("🚫 مسدودشده‌ها", "adm:ul:blocked:0")],
        [("🔙 پنل مدیریت", "adm:home")],
    ))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:ul:"))
async def users_list(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    _, _, flt, page = cb.data.split(":")
    page = int(page)
    rows, total = await list_users(session, page, PER_PAGE, blocked_only=(flt == "blocked"))
    buttons = [[(f"{'🚫 ' if u.is_blocked else ''}{_name(u)[:18]} · {('@' + u.username) if u.username else u.telegram_id}",
                 f"adm:u:{u.id}")] for u in rows]
    nav = []
    if page > 0:
        nav.append(("◀️ قبلی", f"adm:ul:{flt}:{page - 1}"))
    if (page + 1) * PER_PAGE < total:
        nav.append(("بعدی ▶️", f"adm:ul:{flt}:{page + 1}"))
    markup = kb(*buttons, *([nav] if nav else []), [("🔙 کاربران", "adm:users")])
    title = "🚫 کاربران مسدود" if flt == "blocked" else "📋 همه کاربران"
    await edit_or_answer(cb, f"{title}\nتعداد: {total:,}  |  صفحه {page + 1}" if total else f"{title}\n\nموردی نیست.", markup)
    await cb.answer()


@router.callback_query(F.data == "adm:usearch")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await _ask(cb, state, "user_search",
               "🔎 آیدی عددی تلگرام، یوزرنیم (@name) یا بخشی از نام کاربر را بفرستید:", "adm:users")


@router.message(InputAction("user_search"), F.text, ~F.text.startswith("/"))
async def search_do(message: Message, session, state: FSMContext):
    users = await search_users(session, message.text)
    if not users:
        await message.answer("❌ کاربری پیدا نشد. دوباره بفرستید یا انصراف بزنید.")
        return
    await state.clear()
    if len(users) == 1:
        await _show_card(message, session, users[0].id)
        return
    markup = kb(*[[(f"{_name(u)[:18]} · {('@' + u.username) if u.username else u.telegram_id}", f"adm:u:{u.id}")]
                  for u in users], [("🔙 کاربران", "adm:users")])
    await message.answer(f"🔎 {len(users)} نتیجه:", reply_markup=markup)


@router.callback_query(F.data.regexp(r"^adm:u:\d+$"))
async def user_card(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    await _show_card(cb, session, int(cb.data.split(":")[2]))
    await cb.answer()


# ---------- block / unblock ----------
@router.callback_query(F.data.startswith("adm:ub:"))
async def toggle_block(cb: CallbackQuery, session):
    uid = int(cb.data.split(":")[2])
    u = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if u is None:
        await cb.answer("کاربر پیدا نشد", show_alert=True)
        return
    if u.telegram_id in get_settings().admin_telegram_ids:
        await cb.answer("مدیر را نمی‌شود مسدود کرد.", show_alert=True)
        return
    u.is_blocked = not u.is_blocked
    await audit(session, f"admin:{cb.from_user.id}", "user.block" if u.is_blocked else "user.unblock",
                target=f"user:{u.id}")
    await _show_card(cb, session, uid)
    await cb.answer("مسدود شد 🚫" if u.is_blocked else "رفع مسدودی شد ✅")


# ---------- balance ----------
@router.callback_query(F.data.regexp(r"^adm:u[as]:\d+$"))
async def balance_start(cb: CallbackQuery, state: FSMContext):
    _, kind, uid = cb.data.split(":")
    sign = "add" if kind == "ua" else "sub"
    await _ask(cb, state, "bal_amount",
               f"{'➕ افزایش' if sign == 'add' else '➖ کاهش'} موجودی\n\nمبلغ را به تومان (عدد) بفرستید:",
               f"adm:u:{uid}", uid=int(uid), sign=sign)


@router.message(InputAction("bal_amount"), F.text, ~F.text.startswith("/"))
async def balance_amount(message: Message, session, state: FSMContext):
    data = await state.get_data()
    amount = parse_amount(message.text)
    if not amount:
        await message.answer("❌ مبلغ نامعتبر است. فقط عدد مثبت بفرستید.")
        return
    if data["sign"] == "sub":
        w = await get_wallet(session, data["uid"])
        if amount > w.balance:
            await message.answer(f"❌ موجودی کاربر ({fmt_money(w.balance)} تومان) کمتر از این مبلغ است.")
            return
    await state.update_data(action="bal_note", amount=amount)
    note_hint = "(برای بدون توضیح «-» بفرستید)" if data["sign"] == "add" else "(الزامی)"
    await message.answer(f"📝 توضیح/دلیل تراکنش را بنویسید {note_hint}:",
                         reply_markup=kb([("🔙 انصراف", f"adm:u:{data['uid']}")]))


@router.message(InputAction("bal_note"), F.text, ~F.text.startswith("/"))
async def balance_note(message: Message, session, state: FSMContext, bot: Bot):
    data = await state.get_data()
    note = message.text.strip()[:300]
    if note == "-":
        if data["sign"] == "sub":
            await message.answer("❌ برای کاهش موجودی نوشتن دلیل الزامی است.")
            return
        note = ""
    uid, amount, sign = data["uid"], data["amount"], data["sign"]
    await state.clear()
    u = (await session.execute(select(User).where(User.id == uid))).scalar_one()
    try:
        res = await apply_wallet_change(
            session, user_id=uid, delta=amount if sign == "add" else -amount,
            tx_type=TxType.ADMIN_ADD if sign == "add" else TxType.ADMIN_SUB,
            idempotency_key=f"admin:{message.from_user.id}:{uuid4().hex}",
            ref_type="manual", description=note or None, admin_telegram_id=message.from_user.id,
        )
    except InsufficientFunds:
        await message.answer("❌ موجودی کاربر کافی نیست.")
        return
    await audit(session, f"admin:{message.from_user.id}", f"wallet.{sign}", target=f"user:{uid}",
                details={"amount": amount, "note": note})
    await message.answer(f"✅ انجام شد. موجودی جدید: {fmt_money(res.tx.balance_after)} تومان")
    try:
        await bot.send_message(
            u.telegram_id,
            f"{'➕ موجودی شما افزایش یافت' if sign == 'add' else '➖ از موجودی شما کسر شد'}: {fmt_money(amount)} تومان\n"
            f"💰 موجودی جدید: {fmt_money(res.tx.balance_after)} تومان" + (f"\n📝 {note}" if note else ""))
    except Exception as e:
        log.warning("notify user failed: %s", e)
    await _show_card(message, session, uid)


# ---------- message to user ----------
@router.callback_query(F.data.startswith("adm:um:"))
async def msg_start(cb: CallbackQuery, state: FSMContext):
    uid = int(cb.data.split(":")[2])
    await _ask(cb, state, "user_msg", "✉️ پیام خود را بفرستید (متن، عکس، فایل و ...):", f"adm:u:{uid}", uid=uid)


@router.message(InputAction("user_msg"), not_command)
async def msg_send(message: Message, session, state: FSMContext, bot: Bot):
    uid = (await state.get_data())["uid"]
    await state.clear()
    u = (await session.execute(select(User).where(User.id == uid))).scalar_one()
    try:
        await bot.copy_message(u.telegram_id, message.chat.id, message.message_id)
        await audit(session, f"admin:{message.from_user.id}", "user.message", target=f"user:{uid}")
        await message.answer("✅ پیام ارسال شد.")
    except Exception as e:
        await message.answer(f"❌ ارسال نشد (احتمالاً کاربر ربات را بلاک کرده): {e}")
    await _show_card(message, session, uid)


# ---------- transactions / services ----------
@router.callback_query(F.data.startswith("adm:ut:"))
async def user_txs(cb: CallbackQuery, session):
    uid = int(cb.data.split(":")[2])
    txs = await recent_transactions(session, uid, 15)
    body = "\n".join(
        f"{'➕' if t.amount > 0 else '➖'} {fmt_money(abs(t.amount))} — {_TX_LABEL.get(t.type.value, t.type.value)}"
        f"{(' · ' + t.description) if t.description else ''}\n   {fmt_dt(t.created_at)} | موجودی: {fmt_money(t.balance_after)}"
        for t in txs) or "تراکنشی ثبت نشده."
    await edit_or_answer(cb, f"📜 تراکنش‌های اخیر\n\n{body}", kb([("🔙 کاربر", f"adm:u:{uid}")]))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:uv:"))
async def user_services(cb: CallbackQuery, session):
    uid = int(cb.data.split(":")[2])
    rows = (await session.execute(
        select(Service, Panel.display_name).join(Panel, Panel.id == Service.panel_id)
        .where(Service.user_id == uid).order_by(Service.id.desc()).limit(15))).all()
    body = "\n".join(
        f"• {s.username} | {pn} | {s.status.value} | تا {fmt_dt(s.expires_at)}{' | تست' if s.is_test else ''}"
        for s, pn in rows) or "سرویسی ثبت نشده."
    await edit_or_answer(cb, f"📦 سرویس‌های کاربر\n\n{body}", kb([("🔙 کاربر", f"adm:u:{uid}")]))
    await cb.answer()
