"""Admin: free-test settings. One global screen + one screen per panel (enable, profile, size, time, limits).
Must be included BEFORE admin_settings in main.py (it takes over the 'adm:ts' and 'adm:tt' buttons)."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from backend.services.settings_service import get_setting, set_setting
from backend.services.shop import adapter_available
from backend.services.test_service import (
    count_panel_total, effective, global_cfg, panel_test_cfg, resolve_profile, set_panel_test, usable_profiles,
)
from backend.services.users import audit
from bot.filters import AdminOnly, InputAction
from bot.keyboards.admin import kb
from bot.states.states import AdminStates
from bot.utils import _DIGITS, edit_or_answer
from database.models import Panel

router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())

# global settings editable here: key -> (label, kind, (min, max))
GLOBAL = {
    "test_gb": ("\U0001f4e6 حجم پیش‌فرض تست (GB)", "float", (0.1, 100)),
    "test_hours": ("⏱ مدت پیش‌فرض تست (ساعت)", "int", (1, 720)),
    "test_max_per_user": ("\U0001f501 حداکثر تست هر کاربر (روی همه پنل‌ها)", "int", (1, 50)),
}
# per-panel fields: key -> (label, kind, (min, max), allow "-" for default)
FIELDS = {
    "gb": ("\U0001f4e6 حجم تست (GB)", "float", (0.1, 100), True),
    "hours": ("⏱ مدت تست (ساعت)", "int", (1, 720), True),
    "max_per_user": ("\U0001f464 حداکثر تست هر کاربر روی این پنل", "int", (1, 50), False),
    "max_total": ("\U0001f4ca سقف کل تست‌های این پنل (۰ = نامحدود)", "int", (0, 100000), False),
}


def _num(raw: str, kind: str, rng: tuple):
    t = (raw or "").strip().translate(_DIGITS).replace("٫", ".").replace(",", ".")
    try:
        v = float(t) if kind == "float" else int(t)
    except ValueError:
        return None
    return v if rng[0] <= v <= rng[1] else None


def _gb(x: float) -> str:
    return f"{x:g}"


async def _panels(session) -> list[Panel]:
    return list((await session.execute(select(Panel).order_by(Panel.sort_order, Panel.id))).scalars())


# ---------- global screen ----------
async def _global_view(session):
    g = await global_cfg(session)
    rows = []
    for p in await _panels(session):
        cfg = panel_test_cfg(p)
        ok = adapter_available(p) and cfg["enabled"] and p.is_active
        rows.append([(f"{'\U0001f7e2' if ok else '\U0001f534'} {p.display_name}", f"adm:tc:{p.id}")])
    text = (
        "\U0001f381 تنظیمات تست رایگان\n\n"
        f"وضعیت کلی: {'\U0001f7e2 فعال' if g['enabled'] else '\U0001f534 غیرفعال'}\n"
        f"\U0001f4e6 حجم پیش‌فرض: {_gb(g['gb'])} GB\n"
        f"⏱ مدت پیش‌فرض: {g['hours']} ساعت\n"
        f"\U0001f501 حداکثر تست هر کاربر روی همه پنل‌ها: {g['max_per_user']}\n\n"
        "هر پنل تنظیم و محدودیت جدا دارد؛ روی پنل بزنید:" if rows else
        "\U0001f381 تنظیمات تست رایگان\n\nهنوز پنلی اضافه نشده است."
    )
    markup = kb(
        [("⏸ غیرفعال کردن کل تست" if g["enabled"] else "▶️ فعال کردن کل تست", "adm:tt")],
        *rows,
        [("\U0001f7e2 روشن برای همه پنل‌ها", "adm:tca:on"), ("\U0001f534 خاموش برای همه", "adm:tca:off")],
        [("\U0001f4e6 حجم", "adm:tg:test_gb"), ("⏱ مدت", "adm:tg:test_hours")],
        [("\U0001f501 حداکثر تست هر کاربر", "adm:tg:test_max_per_user")],
        [("\U0001f519 پنل مدیریت", "adm:home")],
    )
    return text, markup


@router.callback_query(F.data == "adm:ts")
async def global_menu(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    text, markup = await _global_view(session)
    await edit_or_answer(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data == "adm:tt")
async def master_toggle(cb: CallbackQuery, session):
    on = (await get_setting(session, "test_enabled", "0")) == "1"
    await set_setting(session, "test_enabled", "0" if on else "1")
    await audit(session, f"admin:{cb.from_user.id}", "test.toggle", details={"enabled": not on})
    text, markup = await _global_view(session)
    await edit_or_answer(cb, text, markup)
    await cb.answer("غیرفعال شد" if on else "فعال شد")


@router.callback_query(F.data.regexp(r"^adm:tca:(on|off)$"))
async def all_panels(cb: CallbackQuery, session):
    on = cb.data.endswith(":on")
    for p in await _panels(session):
        await set_panel_test(session, p, enabled=on)
    await audit(session, f"admin:{cb.from_user.id}", "test.all_panels", details={"enabled": on})
    text, markup = await _global_view(session)
    await edit_or_answer(cb, text, markup)
    await cb.answer("برای همه پنل‌ها روشن شد" if on else "برای همه پنل‌ها خاموش شد")


@router.callback_query(F.data.regexp(r"^adm:tg:\w+$"))
async def global_edit(cb: CallbackQuery, session, state: FSMContext):
    key = cb.data.split(":")[2]
    if key not in GLOBAL:
        await cb.answer()
        return
    label, _, rng = GLOBAL[key]
    cur = await get_setting(session, key, "")
    await state.set_state(AdminStates.input)
    await state.set_data({"action": "tg_val", "key": key})
    await edit_or_answer(cb, f"{label}\n\nمقدار فعلی: {cur or '—'}\nمحدوده مجاز: {rng[0]} تا {rng[1]}\n\nمقدار جدید را بفرستید:",
                         kb([("\U0001f519 انصراف", "adm:ts")]))
    await cb.answer()


@router.message(InputAction("tg_val"), F.text, ~F.text.startswith("/"))
async def global_save(message: Message, session, state: FSMContext):
    key = (await state.get_data())["key"]
    label, kind, rng = GLOBAL[key]
    v = _num(message.text, kind, rng)
    if v is None:
        await message.answer(f"❌ یک عدد بین {rng[0]} و {rng[1]} بفرستید.")
        return
    await set_setting(session, key, str(v))
    await state.clear()
    await audit(session, f"admin:{message.from_user.id}", f"setting.{key}", details={"value": v})
    await message.answer("✅ ذخیره شد.")
    text, markup = await _global_view(session)
    await message.answer(text, reply_markup=markup)


# ---------- per-panel screen ----------
async def _panel_view(session, pid: int):
    p = await session.get(Panel, pid)
    if p is None:
        return "پنل پیدا نشد.", kb([("\U0001f519 تنظیمات تست", "adm:ts")])
    glob = await global_cfg(session)
    cfg = panel_test_cfg(p)
    profile = await resolve_profile(session, p, cfg, glob)
    gb, hours = effective(cfg, glob)
    given = await count_panel_total(session, p.id)
    notes = []
    if not adapter_available(p):
        notes.append("⚠️ آداپتر این پنل آماده نیست.")
    if profile is None:
        notes.append("⚠️ این پنل پروفایل فعال با اینباند ندارد؛ اول در «اینباندها / پروفایل‌ها» بسازید.")
    if not p.is_active:
        notes.append("⚠️ خود پنل خاموش است.")
    text = (
        f"\U0001f381 تست رایگان — {p.display_name}\n\n"
        f"وضعیت: {'\U0001f7e2 فعال' if cfg['enabled'] else '\U0001f534 غیرفعال'}\n"
        f"\U0001f3af پروفایل: {profile.name if profile else '—'}"
        f"{'' if cfg['profile_id'] else ' (خودکار)'}\n"
        f"\U0001f4e6 حجم: {_gb(gb)} GB{'' if cfg['gb'] else ' (پیش‌فرض)'}\n"
        f"⏱ مدت: {hours} ساعت{'' if cfg['hours'] else ' (پیش‌فرض)'}\n"
        f"\U0001f464 حداکثر هر کاربر روی این پنل: {cfg['max_per_user']}\n"
        f"\U0001f4ca سقف کل این پنل: {cfg['max_total'] or 'نامحدود'}  |  تا امروز داده‌شده: {given}\n"
        + ("\n" + "\n".join(notes) if notes else "")
    )
    markup = kb(
        [("⏸ غیرفعال کردن" if cfg["enabled"] else "▶️ فعال کردن", f"adm:tct:{pid}")],
        [("\U0001f3af انتخاب پروفایل", f"adm:tcp:{pid}")],
        [("\U0001f4e6 حجم", f"adm:tcf:{pid}:gb"), ("⏱ مدت", f"adm:tcf:{pid}:hours")],
        [("\U0001f464 حداکثر هر کاربر", f"adm:tcf:{pid}:max_per_user")],
        [("\U0001f4ca سقف کل پنل", f"adm:tcf:{pid}:max_total")],
        [("\U0001f519 تنظیمات تست", "adm:ts")],
    )
    return text, markup


@router.callback_query(F.data.regexp(r"^adm:tc:\d+$"))
async def panel_menu(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    text, markup = await _panel_view(session, int(cb.data.split(":")[2]))
    await edit_or_answer(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:tct:\d+$"))
async def panel_toggle(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    p = await session.get(Panel, pid)
    if p is None:
        await cb.answer("پنل پیدا نشد", show_alert=True)
        return
    await set_panel_test(session, p, enabled=not panel_test_cfg(p)["enabled"])
    await audit(session, f"admin:{cb.from_user.id}", "test.panel_toggle", target=f"panel:{pid}")
    text, markup = await _panel_view(session, pid)
    await edit_or_answer(cb, text, markup)
    await cb.answer("انجام شد ✅")


@router.callback_query(F.data.regexp(r"^adm:tcp:\d+$"))
async def profile_pick(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    profiles = await usable_profiles(session, pid)
    if not profiles:
        await edit_or_answer(
            cb, "این پنل پروفایل فعال با اینباند ندارد. اول در «مدیریت پنل‌ها ← اینباندها / پروفایل‌ها» بسازید.",
            kb([("\U0001f519 بازگشت", f"adm:tc:{pid}")]))
        await cb.answer()
        return
    rows = [[(f"{pf.name} ({pf.protocol})", f"adm:tcs:{pid}:{pf.id}")] for pf in profiles]
    await edit_or_answer(
        cb, "\U0001f3af پروفایلی که تست با آن ساخته می‌شود را انتخاب کنید:",
        kb([("\U0001f504 خودکار (اولین پروفایل فعال)", f"adm:tcs:{pid}:0")], *rows, [("\U0001f519 بازگشت", f"adm:tc:{pid}")]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:tcs:\d+:\d+$"))
async def profile_set(cb: CallbackQuery, session):
    _, _, pid, prof = cb.data.split(":")
    p = await session.get(Panel, int(pid))
    if p is None:
        await cb.answer("پنل پیدا نشد", show_alert=True)
        return
    valid = {x.id for x in await usable_profiles(session, p.id)}
    if int(prof) and int(prof) not in valid:
        await cb.answer("پروفایل معتبر نیست", show_alert=True)
        return
    await set_panel_test(session, p, profile_id=int(prof) or None)
    await audit(session, f"admin:{cb.from_user.id}", "test.profile", target=f"panel:{pid}", details={"profile": int(prof)})
    text, markup = await _panel_view(session, p.id)
    await edit_or_answer(cb, text, markup)
    await cb.answer("ذخیره شد ✅")


@router.callback_query(F.data.regexp(r"^adm:tcf:\d+:\w+$"))
async def field_edit(cb: CallbackQuery, session, state: FSMContext):
    _, _, pid, field = cb.data.split(":")
    if field not in FIELDS:
        await cb.answer()
        return
    p = await session.get(Panel, int(pid))
    if p is None:
        await cb.answer("پنل پیدا نشد", show_alert=True)
        return
    label, _, rng, can_default = FIELDS[field]
    cur = panel_test_cfg(p)[field]
    await state.set_state(AdminStates.input)
    await state.set_data({"action": "tc_val", "pid": int(pid), "field": field})
    hint = "\nبرای استفاده از مقدار پیش‌فرض «-» بفرستید." if can_default else ""
    await edit_or_answer(cb, f"{label}\n\nمقدار فعلی: {cur if cur not in (None, '') else 'پیش‌فرض'}\n"
                             f"محدوده مجاز: {rng[0]} تا {rng[1]}{hint}\n\nمقدار جدید را بفرستید:",
                         kb([("\U0001f519 انصراف", f"adm:tc:{pid}")]))
    await cb.answer()


@router.message(InputAction("tc_val"), F.text, ~F.text.startswith("/"))
async def field_save(message: Message, session, state: FSMContext):
    data = await state.get_data()
    field, pid = data["field"], data["pid"]
    label, kind, rng, can_default = FIELDS[field]
    raw = message.text.strip()
    if raw == "-" and can_default:
        v = None
    else:
        v = _num(raw, kind, rng)
        if v is None:
            await message.answer(f"❌ یک عدد بین {rng[0]} و {rng[1]} بفرستید.")
            return
    p = await session.get(Panel, pid)
    await state.clear()
    if p is None:
        await message.answer("پنل پیدا نشد.")
        return
    await set_panel_test(session, p, **{field: v})
    await audit(session, f"admin:{message.from_user.id}", "test.panel_field", target=f"panel:{pid}",
                details={"field": field, "value": v})
    await message.answer("✅ ذخیره شد.")
    text, markup = await _panel_view(session, pid)
    await message.answer(text, reply_markup=markup)
