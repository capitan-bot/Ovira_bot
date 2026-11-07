"""VPN panel management inside Telegram: add / edit / switch on-off / pricing / delete."""
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from adapters.base import ADAPTERS, PanelCredentials, PanelError, build_adapter
from backend.services.panel_admin import create_panel, delete_panel, panel_usage, update_credentials
from backend.services.users import audit
from bot.filters import AdminOnly, InputAction
from bot.keyboards.admin import kb
from bot.states.states import AdminStates
from bot.utils import edit_or_answer, fmt_dt, fmt_money, parse_amount
from config.crypto import decrypt_text
from database.models import ConnStatus, Panel, PanelType

log = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())

TYPE_LABEL = {
    PanelType.PANEL_ONE: "OpenVPN / WireGuard",
    PanelType.OVIRA: "اویرا (OpenVPN / WireGuard)",
    PanelType.SANAEI: "سنایی (3x-ui)",
    PanelType.MARZBAN: "مرزبان (Marzban)",
    PanelType.REBECCA: "ربکا (Rebecca)",
}
CONN_LABEL = {
    ConnStatus.UNKNOWN: "⚪️ بررسی نشده",
    ConnStatus.ONLINE: "🟢 متصل",
    ConnStatus.OFFLINE: "🔴 قطع",
}
PRICE_FIELDS = {
    "price_per_gb": "💰 قیمت هر گیگ",
    "price_per_day": "📅 هزینه هر روز",
    "min_gb": "⬇️ حداقل حجم (GB)",
    "max_gb": "⬆️ حداکثر حجم (GB)",
    "min_days": "⬇️ حداقل روز",
    "max_days": "⬆️ حداکثر روز",
}
_PAIRS = {
    "min_gb": ("max_gb", True),
    "max_gb": ("min_gb", False),
    "min_days": ("max_days", True),
    "max_days": ("min_days", False),
}


async def _get(session, pid: int) -> Panel | None:
    return (await session.execute(select(Panel).where(Panel.id == pid))).scalar_one_or_none()


def _card(p: Panel):
    token_status = "فعال (Token/API Key)" if p.token_enc else "نام کاربری / رمز عبور"
    text = (
        f"🛰 {p.display_name}\n\n"
        f"نوع: {TYPE_LABEL.get(p.panel_type, p.panel_type.value)}\n"
        f"آدرس: {p.api_url}\n"
        f"وضعیت پنل: {'🟢 روشن' if p.is_active else '🔴 خاموش'}\n"
        f"فروش: {'✅ فعال' if p.sales_enabled else '⛔ متوقف'}\n"
        f"اتصال: {CONN_LABEL[p.conn_status]}"
        f"{(' — ' + fmt_dt(p.last_checked_at)) if p.last_checked_at else ''}\n"
        f"{('آخرین خطا: ' + p.last_error[:150] + chr(10)) if p.last_error else ''}"
        f"\n💰 تعرفه: هر گیگ {fmt_money(p.price_per_gb)} | هر روز {fmt_money(p.price_per_day)} تومان\n"
        f"حجم: {p.min_gb}–{p.max_gb} GB | مدت: {p.min_days}–{p.max_days} روز"
    )
    markup_rows = [
        [
            ("⏻ خاموش کردن پنل" if p.is_active else "⏻ روشن کردن پنل", f"adm:pt:{p.id}:active"),
            ("⛔ توقف فروش" if p.sales_enabled else "▶️ شروع فروش", f"adm:pt:{p.id}:sales"),
        ],
        [("📡 اینباندها / پروفایل‌ها", f"adm:pf:{p.id}")],
        [("✏️ تغییر نام", f"adm:pr:{p.id}"), ("💰 تعرفه", f"adm:pp:{p.id}")],
        [("🔌 تست اتصال", f"adm:pc:{p.id}"), ("🔑 تنظیم ورود / توکن", f"adm:pe:{p.id}")],
    ]
    if p.panel_type == PanelType.SANAEI:
        markup_rows.insert(2, [("📊 وضعیت زنده منابع سرور", f"adm:psrv:{p.id}")])
    markup_rows.append([("🗑 حذف پنل", f"adm:pd:{p.id}")])
    markup_rows.append([("🔙 لیست پنل‌ها", "adm:pn")])
    return text, kb(*markup_rows)


async def _ask(target, state: FSMContext, action: str, text: str, back: str, **data):
    await state.set_state(AdminStates.input)
    await state.set_data({"action": action, **data})
    markup = kb([("🔙 انصراف", back)])
    if isinstance(target, CallbackQuery):
        await edit_or_answer(target, text, markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


async def _show(target, session, pid: int):
    p = await _get(session, pid)
    text, markup = _card(p) if p else ("پنل پیدا نشد.", kb([("🔙 لیست پنل‌ها", "adm:pn")]))
    if isinstance(target, CallbackQuery):
        await edit_or_answer(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:pn")
async def panels_list(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    panels = (await session.execute(select(Panel).order_by(Panel.sort_order, Panel.id))).scalars().all()
    rows = [
        [(f"{'🟢' if p.is_active else '🔴'} {p.display_name} {'' if p.sales_enabled else '⛔'}", f"adm:p:{p.id}")]
        for p in panels
    ]
    await edit_or_answer(
        cb,
        "🛰 مدیریت پنل‌ها\n\n" + ("پنل‌های ثبت‌شده:" if panels else "هنوز پنلی اضافه نشده است."),
        kb(*rows, [("➕ افزودن پنل", "adm:pa")], [("🔙 پنل مدیریت", "adm:home")]),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:p:\d+$"))
async def panel_card(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    await _show(cb, session, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:pt:\d+:(active|sales)$"))
async def toggle(cb: CallbackQuery, session):
    _, _, pid, what = cb.data.split(":")
    p = await _get(session, int(pid))
    if p is None:
        await cb.answer("پنل پیدا نشد", show_alert=True)
        return
    if what == "active":
        p.is_active = not p.is_active
    else:
        p.sales_enabled = not p.sales_enabled
    await audit(
        session, f"admin:{cb.from_user.id}", f"panel.{what}", target=f"panel:{p.id}",
        details={"active": p.is_active, "sales": p.sales_enabled},
    )
    await _show(cb, session, p.id)
    await cb.answer("انجام شد ✅")


@router.callback_query(F.data == "adm:pa")
async def add_start(cb: CallbackQuery, state: FSMContext):
    await _ask(
        cb, state, "padd_name",
        "➕ افزودن پنل\n\nنام نمایشی پنل را بفرستید (مثلاً «🟣 سنایی اصلی»):",
        "adm:pn",
    )


@router.message(InputAction("padd_name"), F.text, ~F.text.startswith("/"))
async def add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer("❌ نام باید بین ۲ تا ۴۰ حرف باشد.")
        return
    await state.update_data(action="padd_type", name=name)
    await message.answer(
        "نوع پنل را انتخاب کنید:",
        reply_markup=kb(
            [("🟣 اویرا (OpenVPN / WireGuard)", "adm:pat:ovira")],
            [("🔵 سنایی (3x-ui)", "adm:pat:sanaei")],
            [("🟠 مرزبان (Marzban)", "adm:pat:marzban")],
            [("🟡 ربکا (Rebecca) - آزمایشی", "adm:pat:rebecca")],
            [("🔙 انصراف", "adm:pn")],
        ),
    )


@router.callback_query(F.data.startswith("adm:pat:"))
async def add_type(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("action") != "padd_type":
        await cb.answer("درخواست منقضی شده است.", show_alert=True)
        return
    await state.update_data(action="padd_url", ptype=cb.data.split(":")[2])
    await edit_or_answer(
        cb,
        "🌐 آدرس کامل پنل را بفرستید (با پورت و مسیر مخفی؛ مثال: https://panel.example.com:4000/secretpath):",
        kb([("🔙 انصراف", "adm:pn")]),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:pe:\d+$"))
async def edit_creds(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[2])
    await _ask(cb, state, "padd_url", "🌐 آدرس جدید پنل را بفرستید:", f"adm:p:{pid}", pid=pid)


@router.message(InputAction("padd_url"), F.text, ~F.text.startswith("/"))
async def add_url(message: Message, state: FSMContext):
    url = message.text.strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")) or len(url) > 250 or " " in url:
        await message.answer("❌ آدرس باید با http:// یا https:// شروع شود.")
        return
    await state.update_data(action="padd_auth_mode", url=url)
    await message.answer(
        "روش ورود به پنل را انتخاب کنید:",
        reply_markup=kb(
            [("🔑 استفاده از Token / API Key", "adm:am:token")],
            [("👤 نام کاربری و رمز عبور", "adm:am:creds")],
            [("🔙 انصراف", "adm:pn")],
        ),
    )


@router.callback_query(F.data.startswith("adm:am:"))
async def auth_mode_choice(cb: CallbackQuery, state: FSMContext):
    mode = cb.data.split(":")[2]
    await state.update_data(auth_mode=mode)
    if mode == "token":
        await state.update_data(action="padd_token")
        await edit_or_answer(cb, "🔑 کلید API / Token پنل را بفرستید:", kb([("🔙 انصراف", "adm:pn")]))
    else:
        await state.update_data(action="padd_user")
        await edit_or_answer(cb, "👤 نام کاربری ادمین پنل را بفرستید:", kb([("🔙 انصراف", "adm:pn")]))
    await cb.answer()


@router.message(InputAction("padd_token"), F.text, ~F.text.startswith("/"))
async def add_token_finish(message: Message, session, state: FSMContext):
    token = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    await state.clear()
    
    if data.get("pid"):
        p = await _get(session, data["pid"])
        from config.crypto import encrypt_text
        p.api_url = data["url"]
        p.token_enc = encrypt_text(token)
        p.username_enc = None
        p.password_enc = None
        p.conn_status, p.last_error = ConnStatus.UNKNOWN, None
        await audit(session, f"admin:{message.from_user.id}", "panel.token", target=f"panel:{p.id}")
        await message.answer("✅ توکن و آدرس پنل به‌روزرسانی شد.")
        await _show(message, session, p.id)
    else:
        p = await create_panel(
            session, name=data["name"], panel_type=PanelType(data["ptype"]),
            api_url=data["url"], username=None, password=None, token=token,
        )
        await audit(
            session, f"admin:{message.from_user.id}", "panel.create", target=f"panel:{p.id}",
            details={"name": p.display_name, "type": p.panel_type.value, "auth": "token"},
        )
        await message.answer("✅ پنل با توکن اضافه شد. حالا دکمه «🔌 تست اتصال» را بزنید.")
        await _show(message, session, p.id)


@router.message(InputAction("padd_user"), F.text, ~F.text.startswith("/"))
async def add_user(message: Message, state: FSMContext):
    await state.update_data(action="padd_pass", username=message.text.strip())
    await message.answer("🔒 رمز عبور ادمین پنل را بفرستید (پیام شما خودکار پاک می‌شود):")


@router.message(InputAction("padd_pass"), F.text, ~F.text.startswith("/"))
async def add_pass(message: Message, session, state: FSMContext):
    data = await state.get_data()
    password = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    
    if data.get("pid"):
        p = await _get(session, data["pid"])
        await update_credentials(session, p, api_url=data["url"], username=data["username"], password=password)
        p.token_enc = None
        p.conn_status, p.last_error = ConnStatus.UNKNOWN, None
        await audit(session, f"admin:{message.from_user.id}", "panel.credentials", target=f"panel:{p.id}")
        await message.answer("✅ اطلاعات پنل به‌روزرسانی شد.")
        await _show(message, session, p.id)
    else:
        p = await create_panel(
            session, name=data["name"], panel_type=PanelType(data["ptype"]),
            api_url=data["url"], username=data["username"], password=password, token=None,
        )
        await audit(
            session, f"admin:{message.from_user.id}", "panel.create", target=f"panel:{p.id}",
            details={"name": p.display_name, "type": p.panel_type.value, "auth": "password"},
        )
        await message.answer("✅ پنل اضافه شد. حالا دکمه «🔌 تست اتصال» را بزنید.")
        await _show(message, session, p.id)


@router.callback_query(F.data.regexp(r"^adm:pr:\d+$"))
async def rename_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[2])
    await _ask(cb, state, "prename", "✏️ نام جدید پنل را بفرستید:", f"adm:p:{pid}", pid=pid)


@router.message(InputAction("prename"), F.text, ~F.text.startswith("/"))
async def rename_do(message: Message, session, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer("❌ نام باید بین ۲ تا ۴۰ حرف باشد.")
        return
    pid = (await state.get_data())["pid"]
    await state.clear()
    p = await _get(session, pid)
    p.display_name = name
    await audit(session, f"admin:{message.from_user.id}", "panel.rename", target=f"panel:{pid}", details={"name": name})
    await message.answer("✅ نام ذخیره شد.")
    await _show(message, session, pid)


@router.callback_query(F.data.regexp(r"^adm:pp:\d+$"))
async def pricing(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    pid = int(cb.data.split(":")[2])
    p = await _get(session, pid)
    lines = "\n".join(f"{label}: {fmt_money(getattr(p, f))}" for f, label in PRICE_FIELDS.items())
    btns = [[(label, f"adm:ppf:{pid}:{f}")] for f, label in PRICE_FIELDS.items()]
    await edit_or_answer(
        cb, f"💰 تعرفه «{p.display_name}»\n\n{lines}\n\nبرای تغییر، روی مورد موردنظر بزنید:",
        kb(*btns, [("🔙 پنل", f"adm:p:{pid}")]),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:ppf:\d+:\w+$"))
async def price_field(cb: CallbackQuery, session, state: FSMContext):
    _, _, pid, field = cb.data.split(":")
    if field not in PRICE_FIELDS:
        await cb.answer()
        return
    p = await _get(session, int(pid))
    await _ask(
        cb, state, "pfield",
        f"{PRICE_FIELDS[field]}\nمقدار فعلی: {fmt_money(getattr(p, field))}\n\nمقدار جدید را (عدد) بفرستید:",
        f"adm:pp:{pid}", pid=int(pid), field=field,
    )


@router.message(InputAction("pfield"), F.text, ~F.text.startswith("/"))
async def price_set(message: Message, session, state: FSMContext):
    data = await state.get_data()
    val = parse_amount(message.text)
    field = data["field"]
    if val is None or val <= 0:
        await message.answer("❌ یک عدد مثبت بفرستید.")
        return
    p = await _get(session, data["pid"])
    if field in _PAIRS:
        other, is_min = _PAIRS[field]
        ov = getattr(p, other)
        if (is_min and val > ov) or (not is_min and val < ov):
            await message.answer(f"❌ حداقل نباید از حداکثر بیشتر شود (مقدار {PRICE_FIELDS[other]}: {ov}).")
            return
    setattr(p, field, val)
    await state.clear()
    await audit(
        session, f"admin:{message.from_user.id}", "panel.price", target=f"panel:{p.id}",
        details={"field": field, "value": val},
    )
    await message.answer("✅ ذخیره شد.")
    await _show(message, session, p.id)


@router.callback_query(F.data.regexp(r"^adm:pc:\d+$"))
async def test_conn(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    p = await _get(session, pid)
    if p.panel_type.value not in ADAPTERS:
        await cb.answer("آداپتر این نوع پنل فعال نیست.", show_alert=True)
        return
    creds = PanelCredentials(
        api_url=p.api_url, username=decrypt_text(p.username_enc),
        password=decrypt_text(p.password_enc), token=decrypt_text(p.token_enc), extra=p.extra or {},
    )
    try:
        await build_adapter(p.panel_type.value, creds).test_connection()
        p.conn_status, p.last_error = ConnStatus.ONLINE, None
        msg = "اتصال موفق بود ✅"
    except PanelError as e:
        p.conn_status, p.last_error = ConnStatus.OFFLINE, str(e)[:500]
        msg = "اتصال ناموفق بود ❌"
    p.last_checked_at = datetime.now(timezone.utc)
    await _show(cb, session, pid)
    await cb.answer(msg, show_alert=True)


@router.callback_query(F.data.regexp(r"^adm:psrv:\d+$"))
async def panel_server_status(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    p = await _get(session, pid)
    if not p or p.panel_type != PanelType.SANAEI:
        await cb.answer("این قابلیت فقط برای پنل سنایی فعال است.", show_alert=True)
        return
    
    creds = PanelCredentials(
        api_url=p.api_url, username=decrypt_text(p.username_enc),
        password=decrypt_text(p.password_enc), token=decrypt_text(p.token_enc), extra=p.extra or {},
    )
    try:
        adapter = build_adapter(p.panel_type.value, creds)
        st = await adapter.get_system_status()
        await adapter.close()
        
        if not st:
            await cb.answer("خطا در دریافت اطلاعات از پنل.", show_alert=True)
            return
            
        cpu = st.get("cpu", 0)
        mem = st.get("mem", {})
        swap = st.get("swap", {})
        disk = st.get("disk", {})
        
        def fmt_bytes(b):
            if not b: return "0 B"
            for u in ['B', 'KB', 'MB', 'GB', 'TB']:
                if b < 1024: return f"{b:.1f} {u}"
                b /= 1024
            return f"{b:.1f} PB"

        text = (
            f"📊 وضعیت زنده سرور «{p.display_name}»\n\n"
            f"💻 مصرف CPU: {cpu:.1f}%\n"
            f"🧠 رم (RAM): {fmt_bytes(mem.get('current', 0))} / {fmt_bytes(mem.get('total', 0))}\n"
            f"💾 دیسک (Disk): {fmt_bytes(disk.get('current', 0))} / {fmt_bytes(disk.get('total', 0))}\n"
            f"⚡ آپ‌تایم: {st.get('uptime', 0) // 3600} ساعت\n"
            f"📡 اتصالات فعال (Tcp/Udp): {st.get('tcpCount', 0)} / {st.get('udpCount', 0)}"
        )
        await edit_or_answer(cb, text, kb([("🔄 به‌روزرسانی", f"adm:psrv:{pid}"), ("🔙 پنل", f"adm:p:{pid}")]))
    except Exception as e:
        await cb.answer(f"خطا در ارتباط با پنل: {str(e)[:100]}", show_alert=True)


@router.callback_query(F.data.regexp(r"^adm:pd:\d+$"))
async def delete_ask(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    used = await panel_usage(session, pid)
    if used:
        await cb.answer(
            f"این پنل {used} سفارش/سرویس دارد و حذف نمی‌شود. به‌جای حذف، فروش یا پنل را خاموش کنید.",
            show_alert=True,
        )
        return
    await edit_or_answer(
        cb, "⚠️ این پنل و پروفایل‌هایش برای همیشه حذف می‌شود. مطمئنید؟",
        kb([("🗑 بله، حذف شود", f"adm:pdy:{pid}")], [("🔙 انصراف", f"adm:p:{pid}")]),
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:pdy:\d+$"))
async def delete_do(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    p = await _get(session, pid)
    name = p.display_name if p else ""
    deleted = bool(p and await delete_panel(session, p))
    if deleted:
        await audit(session, f"admin:{cb.from_user.id}", "panel.delete", target=f"panel:{pid}", details={"name": name})
        await cb.answer("حذف شد ✅")
    else:
        await cb.answer("حذف انجام نشد.", show_alert=True)
    await edit_or_answer(
        cb, "🛰 پنل حذف شد." if deleted else "❌ حذف انجام نشد.",
        kb([("🔙 لیست پنل‌ها", "adm:pn")]),
    )
