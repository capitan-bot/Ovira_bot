"""Admin: profiles (= product made of real panel inbounds) per panel, and the free-test target."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from adapters.base import PanelError
from backend.services.settings_service import get_setting, get_settings_map, set_setting
from backend.services.shop import adapter_available, adapter_for
from backend.services.users import audit
from bot.filters import AdminOnly, InputAction
from bot.keyboards.shop import kb
from bot.states.states import AdminStates
from bot.utils import edit_or_answer
from database.models import Order, Panel, Service, ServiceProfile

log = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())
MAX_INBOUNDS = 40


def _proto(items: list[dict]) -> str:
    return "+".join(sorted({(i.get("protocol") or "?") for i in items}))[:32]


async def _ask(target, state: FSMContext, action: str, text: str, back: str, **data):
    await state.set_state(AdminStates.input)
    await state.set_data({"action": action, **data})
    markup = kb([("\U0001f519 انصراف", back)])
    if isinstance(target, CallbackQuery):
        await edit_or_answer(target, text, markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


# ---------- profile list / card ----------
async def _list_view(session, pid: int):
    panel = await session.get(Panel, pid)
    if panel is None:
        return "پنل پیدا نشد.", kb([("\U0001f519 لیست پنل\u200cها", "adm:pn")])
    profiles = (await session.execute(
        select(ServiceProfile).where(ServiceProfile.panel_id == pid)
        .order_by(ServiceProfile.sort_order, ServiceProfile.id))).scalars().all()
    rows = [[(f"{'\U0001f7e2' if p.is_active else '\U0001f534'} {p.name}{'' if p.sales_enabled else ' \u26d4\ufe0f'}", f"adm:pfv:{p.id}")]
            for p in profiles]
    text = (f"\U0001f4e1 اینباندها / پروفایل\u200cها \u2014 {panel.display_name}\n\n"
            "هر پروفایل یک \u00abمحصول\u00bb است که از اینباندهای واقعی همین پنل ساخته می\u200cشود و مشتری هنگام خرید می\u200cبیند.\n\n"
            + ("پروفایل\u200cهای ثبت\u200cشده:" if profiles else "هنوز پروفایلی ساخته نشده است."))
    return text, kb(*rows, [("\u2795 ساخت پروفایل جدید", f"adm:pfa:{pid}")], [("\U0001f519 پنل", f"adm:p:{pid}")])


@router.callback_query(F.data.regexp(r"^adm:pf:\d+$"))
async def profiles_list(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    text, markup = await _list_view(session, int(cb.data.split(":")[2]))
    await edit_or_answer(cb, text, markup)
    await cb.answer()


async def _card(session, prof_id: int):
    p = await session.get(ServiceProfile, prof_id)
    if p is None:
        return "پروفایل پیدا نشد.", kb([("\U0001f519 لیست پنل\u200cها", "adm:pn")])
    panel = await session.get(Panel, p.panel_id)
    ibs = "\n".join(f"  \u2022 {i.get('remark') or i['id']} ({i.get('protocol') or '?'})" for i in (p.inbounds or [])) or "  \u2014"
    text = (
        f"\U0001f4e1 {p.name}\n\n"
        f"\U0001f6f0 پنل: {panel.display_name if panel else '\u2014'}\n"
        f"پروتکل: {p.protocol}\n"
        f"وضعیت: {'\U0001f7e2 روشن' if p.is_active else '\U0001f534 خاموش'}\n"
        f"فروش: {'\u2705 فعال' if p.sales_enabled else '\u26d4\ufe0f متوقف'}\n\n"
        f"اینباندهای انتخاب\u200cشده:\n{ibs}"
    )
    markup = kb(
        [("\u23fb خاموش کردن" if p.is_active else "\u23fb روشن کردن", f"adm:pft:{p.id}:active"),
         ("\u26d4\ufe0f توقف فروش" if p.sales_enabled else "\u25b6\ufe0f شروع فروش", f"adm:pft:{p.id}:sales")],
        [("\u270f\ufe0f تغییر نام", f"adm:pfr:{p.id}"), ("\U0001f501 تغییر اینباندها", f"adm:pfi:{p.id}")],
        [("\U0001f5d1 حذف پروفایل", f"adm:pfx:{p.id}")],
        [("\U0001f519 لیست پروفایل\u200cها", f"adm:pf:{p.panel_id}")],
    )
    return text, markup


async def _show(target, session, prof_id: int):
    text, markup = await _card(session, prof_id)
    if isinstance(target, CallbackQuery):
        await edit_or_answer(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^adm:pfv:\d+$"))
async def profile_card(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    await _show(cb, session, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:pft:\d+:(active|sales)$"))
async def profile_toggle(cb: CallbackQuery, session):
    _, _, pid, what = cb.data.split(":")
    p = await session.get(ServiceProfile, int(pid))
    if p is None:
        await cb.answer("پروفایل پیدا نشد", show_alert=True)
        return
    if what == "active":
        p.is_active = not p.is_active
    else:
        p.sales_enabled = not p.sales_enabled
    await audit(session, f"admin:{cb.from_user.id}", f"profile.{what}", target=f"profile:{p.id}",
                details={"active": p.is_active, "sales": p.sales_enabled})
    await _show(cb, session, p.id)
    await cb.answer("انجام شد \u2705")


# ---------- pick inbounds (create / change) ----------
def _pick_view(data: dict):
    sel = data["sel"]
    rows = []
    for idx, i in enumerate(data["ib"]):
        mark = "\u2705" if i["id"] in sel else "\u2b1c\ufe0f"
        rows.append([(f"{mark} {(i['remark'] or i['id'])[:30]} ({i['protocol'] or '?'})", f"adm:pfs:{idx}")])
    back = f"adm:pfv:{data['edit_pf']}" if data.get("edit_pf") else f"adm:pf:{data['pid']}"
    rows.append([(f"\u27a1\ufe0f ادامه ({len(sel)} انتخاب)", "adm:pfn")])
    rows.append([("\U0001f519 انصراف", back)])
    text = ("\U0001f4e1 اینباندهای این پروفایل را انتخاب کنید\n\n"
            "این لیست مستقیم از خود پنل خوانده شده است. روی هر مورد بزنید تا انتخاب یا برداشته شود\u061b "
            "کاربر در همه اینباندهای انتخاب\u200cشده ساخته می\u200cشود.")
    return text, kb(*rows)


async def _start_pick(cb: CallbackQuery, session, state: FSMContext, panel: Panel, edit_pf: int | None = None):
    if not adapter_available(panel):
        await cb.answer("آداپتر این نوع پنل هنوز ساخته نشده است.", show_alert=True)
        return
    try:
        inbounds = await adapter_for(panel).list_inbounds()
    except Exception as e:  # noqa: BLE001
        msg = str(e) if isinstance(e, PanelError) else f"{type(e).__name__}: {e}"
        await edit_or_answer(cb, f"\u274c خواندن اینباندها از پنل ممکن نشد:\n{msg[:300]}\n\nاول \u00abتست اتصال\u00bb پنل را بزنید.",
                             kb([("\U0001f519 پنل", f"adm:p:{panel.id}")]))
        await cb.answer()
        return
    if not inbounds:
        await edit_or_answer(cb, "\u2139\ufe0f این پنل هیچ اینباندی ندارد. اول داخل خود پنل یکی بسازید.",
                             kb([("\U0001f519 پنل", f"adm:p:{panel.id}")]))
        await cb.answer()
        return
    ib = [{"id": str(i.id), "remark": i.remark, "protocol": i.protocol} for i in inbounds[:MAX_INBOUNDS]]
    sel: list[str] = []
    if edit_pf:
        prof = await session.get(ServiceProfile, edit_pf)
        have = {str(x["id"]) for x in (prof.inbounds or [])}
        sel = [i["id"] for i in ib if i["id"] in have]
    data = {"action": "pf_pick", "pid": panel.id, "ib": ib, "sel": sel, "edit_pf": edit_pf}
    await state.set_state(AdminStates.input)
    await state.set_data(data)
    text, markup = _pick_view(data)
    await edit_or_answer(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:pfa:\d+$"))
async def add_profile(cb: CallbackQuery, session, state: FSMContext):
    panel = await session.get(Panel, int(cb.data.split(":")[2]))
    if panel is None:
        await cb.answer("پنل پیدا نشد", show_alert=True)
        return
    await _start_pick(cb, session, state, panel)


@router.callback_query(F.data.regexp(r"^adm:pfi:\d+$"))
async def change_inbounds(cb: CallbackQuery, session, state: FSMContext):
    prof = await session.get(ServiceProfile, int(cb.data.split(":")[2]))
    panel = await session.get(Panel, prof.panel_id) if prof else None
    if panel is None:
        await cb.answer("پروفایل پیدا نشد", show_alert=True)
        return
    await _start_pick(cb, session, state, panel, edit_pf=prof.id)


@router.callback_query(F.data.regexp(r"^adm:pfs:\d+$"), InputAction("pf_pick"))
async def toggle_inbound(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(cb.data.split(":")[2])
    if idx >= len(data["ib"]):
        await cb.answer()
        return
    iid = data["ib"][idx]["id"]
    sel = [x for x in data["sel"] if x != iid] if iid in data["sel"] else data["sel"] + [iid]
    await state.update_data(sel=sel)
    data["sel"] = sel
    text, markup = _pick_view(data)
    await edit_or_answer(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data == "adm:pfn", InputAction("pf_pick"))
async def pick_done(cb: CallbackQuery, session, state: FSMContext):
    data = await state.get_data()
    if not data["sel"]:
        await cb.answer("حداقل یک اینباند انتخاب کنید.", show_alert=True)
        return
    by_id = {i["id"]: i for i in data["ib"]}
    chosen = [by_id[i] for i in data["sel"]]
    if data.get("edit_pf"):
        prof = await session.get(ServiceProfile, data["edit_pf"])
        prof.inbounds = chosen
        prof.protocol = _proto(chosen)
        await state.clear()
        await audit(session, f"admin:{cb.from_user.id}", "profile.inbounds", target=f"profile:{prof.id}",
                    details={"ids": data["sel"]})
        await _show(cb, session, prof.id)
        await cb.answer("ذخیره شد \u2705")
        return
    await state.update_data(action="pf_name")
    await edit_or_answer(cb, "\u270d\ufe0f نام پروفایل را بفرستید (مشتری این نام را می\u200cبیند\u061b مثلا\u064b \u00ab\U0001f680 اینترنت پرسرعت\u00bb):",
                         kb([("\U0001f519 انصراف", f"adm:pf:{data['pid']}")]))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:pfs:") | (F.data == "adm:pfn"))
async def pick_expired(cb: CallbackQuery):
    await cb.answer("این درخواست منقضی شده است. دوباره از \u00abساخت پروفایل\u00bb شروع کنید.", show_alert=True)


@router.message(InputAction("pf_name"), F.text, ~F.text.startswith("/"))
async def create_profile(message: Message, session, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer("\u274c نام باید بین ۲ تا ۴۰ حرف باشد.")
        return
    data = await state.get_data()
    by_id = {i["id"]: i for i in data["ib"]}
    chosen = [by_id[i] for i in data["sel"]]
    order = (await session.execute(
        select(func.coalesce(func.max(ServiceProfile.sort_order), 0)).where(ServiceProfile.panel_id == data["pid"])
    )).scalar_one()
    prof = ServiceProfile(panel_id=data["pid"], name=name, protocol=_proto(chosen), inbounds=chosen,
                          settings={}, sort_order=order + 1)
    session.add(prof)
    await session.flush()
    await state.clear()
    await audit(session, f"admin:{message.from_user.id}", "profile.create", target=f"profile:{prof.id}",
                details={"name": name, "inbounds": data["sel"]})
    await message.answer("\u2705 پروفایل ساخته شد و برای فروش آماده است.")
    await _show(message, session, prof.id)


# ---------- rename / delete ----------
@router.callback_query(F.data.regexp(r"^adm:pfr:\d+$"))
async def rename_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[2])
    await _ask(cb, state, "pf_rename", "\u270f\ufe0f نام جدید پروفایل را بفرستید:", f"adm:pfv:{pid}", pid=pid)


@router.message(InputAction("pf_rename"), F.text, ~F.text.startswith("/"))
async def rename_do(message: Message, session, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer("\u274c نام باید بین ۲ تا ۴۰ حرف باشد.")
        return
    pid = (await state.get_data())["pid"]
    await state.clear()
    prof = await session.get(ServiceProfile, pid)
    prof.name = name
    await audit(session, f"admin:{message.from_user.id}", "profile.rename", target=f"profile:{pid}", details={"name": name})
    await message.answer("\u2705 نام ذخیره شد.")
    await _show(message, session, pid)


async def _usage(session, prof_id: int) -> int:
    orders = (await session.execute(select(func.count()).select_from(Order).where(Order.profile_id == prof_id))).scalar_one()
    services = (await session.execute(select(func.count()).select_from(Service).where(Service.profile_id == prof_id))).scalar_one()
    return int(orders) + int(services)


@router.callback_query(F.data.regexp(r"^adm:pfx:\d+$"))
async def delete_ask(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    used = await _usage(session, pid)
    if used:
        await cb.answer(f"این پروفایل {used} سفارش/سرویس دارد و حذف نمی\u200cشود. به\u200cجای حذف\u060c فروش یا پروفایل را خاموش کنید.",
                        show_alert=True)
        return
    await edit_or_answer(cb, "\u26a0\ufe0f این پروفایل برای همیشه حذف می\u200cشود. مطمئنید\u061f",
                         kb([("\U0001f5d1 بله\u060c حذف شود", f"adm:pfxy:{pid}")], [("\U0001f519 انصراف", f"adm:pfv:{pid}")]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:pfxy:\d+$"))
async def delete_do(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[2])
    prof = await session.get(ServiceProfile, pid)
    if prof is None or await _usage(session, pid):
        await cb.answer("حذف انجام نشد.", show_alert=True)
        return
    panel_id, name = prof.panel_id, prof.name
    if (await get_setting(session, "test_profile_id", "")) == str(pid):
        await set_setting(session, "test_profile_id", "")
        await set_setting(session, "test_panel_id", "")
    await session.delete(prof)
    await session.flush()
    await audit(session, f"admin:{cb.from_user.id}", "profile.delete", target=f"profile:{pid}", details={"name": name})
    await cb.answer("حذف شد \u2705")
    text, markup = await _list_view(session, panel_id)
    await edit_or_answer(cb, text, markup)


# ---------- free-test target ----------
@router.callback_query(F.data == "adm:tp")
async def test_target(cb: CallbackQuery, session, state: FSMContext):
    await state.clear()
    cfg = await get_settings_map(session, ["test_panel_id", "test_profile_id"])
    current = "هنوز انتخاب نشده"
    if cfg["test_profile_id"].isdigit():
        prof = await session.get(ServiceProfile, int(cfg["test_profile_id"]))
        panel = await session.get(Panel, prof.panel_id) if prof else None
        if prof and panel:
            current = f"{panel.display_name} \u2014 {prof.name}"
    rows = (await session.execute(
        select(ServiceProfile, Panel).join(Panel, Panel.id == ServiceProfile.panel_id)
        .where(ServiceProfile.is_active.is_(True), Panel.is_active.is_(True))
        .order_by(Panel.sort_order, ServiceProfile.sort_order, ServiceProfile.id).limit(30))).all()
    buttons = [[(f"{pn.display_name} \u2014 {pf.name}", f"adm:tps:{pf.id}")] for pf, pn in rows if adapter_available(pn)]
    text = f"\U0001f3af پنل و پروفایل تست رایگان\n\nانتخاب فعلی: {current}\n\n" + (
        "یکی را برای ساخت تست انتخاب کنید:" if buttons else "هنوز پروفایل فعالی روی پنلی با آداپتر آماده وجود ندارد. اول در \u00abمدیریت پنل\u200cها\u00bb پروفایل بسازید.")
    await edit_or_answer(cb, text, kb(*buttons, [("\U0001f519 تنظیمات تست", "adm:ts")]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:tps:\d+$"))
async def test_target_set(cb: CallbackQuery, session, state: FSMContext):
    prof = await session.get(ServiceProfile, int(cb.data.split(":")[2]))
    if prof is None:
        await cb.answer("پروفایل پیدا نشد", show_alert=True)
        return
    await set_setting(session, "test_panel_id", str(prof.panel_id))
    await set_setting(session, "test_profile_id", str(prof.id))
    await audit(session, f"admin:{cb.from_user.id}", "test.target", target=f"profile:{prof.id}")
    await test_target(cb, session, state)
