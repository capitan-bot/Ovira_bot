import json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.filters import AdminOnly, not_command
from bot.keyboards.admin import kb
from bot.ui_manager import (
    COLOR_PRESETS,
    init_custom_db,
    set_premium_emoji, delete_premium_emoji, get_all_emojis,
    set_text_replacement, delete_text_replacement, get_text_replacements,
    set_button_rename, delete_button_rename, get_button_renames,
    set_button_color, delete_button_color, clear_all_button_colors, get_button_colors,
    get_ui_config, set_ui_config,
)

router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())

init_custom_db()

class CustomAdminStates(StatesGroup):
    # ایموجی پریمیوم
    emj_base = State()
    emj_premium = State()
    emj_delete = State()
    # تغییر نام دکمه
    btn_old_name = State()
    btn_new_name = State()
    btn_del_name = State()
    # چیدمان دکمه‌ها
    btn_layout_order = State()
    # تغییر متن‌ها
    txt_old = State()
    txt_new = State()
    txt_del_id = State()
    # رنگ دکمه‌ها
    clr_custom_btn = State()

# ----------------- ۱. منوی ایموجی پریمیوم -----------------
def emoji_menu_kb():
    return kb(
        [("➕ افزودن / جایگزینی ایموجی", "adm:emj:add")],
        [("🗑 حذف ایموجی", "adm:emj:del"), ("📋 لیست ایموجی‌ها", "adm:emj:list")],
        [("🔙 بازگشت به پنل مدیریت", "adm:home")],
    )

@router.callback_query(F.data == "adm:emj")
async def open_emoji_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    emojis = get_all_emojis()
    text = (
        "✨ <b>مدیریت ایموجی‌های پریمیوم ربات</b>\n\n"
        f"📊 تعداد ایموجی‌های فعال: <b>{len(emojis)}</b>\n\n"
        "ابتدا ایموجی ساده (پایه) و سپس ایموجی پریمیوم را بفرستید تا در کل ربات جایگزین شود:"
    )
    await call.message.edit_text(text, reply_markup=emoji_menu_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "adm:emj:add")
async def start_add_emoji(call: CallbackQuery, state: FSMContext):
    await state.set_state(CustomAdminStates.emj_base)
    await call.message.edit_text(
        "1️⃣ لطفاً ابتدا <b>ایموجی ساده (پایه)</b> را بفرستید (مثلاً ❤️ یا 🔥):",
        reply_markup=kb([("🔙 انصراف", "adm:emj")]),
        parse_mode="HTML",
    )
    await call.answer()

@router.message(CustomAdminStates.emj_base, F.text, not_command)
async def receive_base_emoji(message: Message, state: FSMContext):
    base = message.text.strip()
    if not base or len(base) > 8:
        await message.answer("❌ لطفاً فقط یک ایموجی ساده ارسال کنید:", reply_markup=kb([("🔙 انصراف", "adm:emj")]))
        return
    await state.update_data(base_emoji=base)
    await state.set_state(CustomAdminStates.emj_premium)
    await message.answer(
        f"✅ ایموجی پایه ( {base} ) دریافت شد.\n\n"
        "2️⃣ حالا <b>ایموجی پریمیوم</b> مورد نظر را ارسال کنید تا جایگزین آن شود:",
        reply_markup=kb([("🔙 انصراف", "adm:emj")]),
        parse_mode="HTML",
    )

@router.message(CustomAdminStates.emj_premium, not_command)
async def receive_premium_emoji(message: Message, state: FSMContext):
    entities = message.entities or message.caption_entities or []
    custom_id = None
    for ent in entities:
        if ent.type == "custom_emoji" and getattr(ent, "custom_emoji_id", None):
            custom_id = ent.custom_emoji_id
            break

    if not custom_id:
        await message.answer(
            "❌ این پیام حاوی ایموجی پریمیوم نیست! لطفاً یک ایموجی پریمیوم تلگرام ارسال کنید:",
            reply_markup=kb([("🔙 انصراف", "adm:emj")]),
        )
        return

    data = await state.get_data()
    base = data["base_emoji"]
    set_premium_emoji(base, custom_id)
    await state.clear()

    await message.answer(
        f"🎉 <b>ایموجی پریمیوم با موفقیت ست شد!</b>\n\n"
        f"🔹 ایموجی ساده: {base}\n"
        f"🔸 نسخه پریمیوم: <tg-emoji emoji-id=\"{custom_id}\">{base}</tg-emoji>",
        reply_markup=emoji_menu_kb(),
        parse_mode="HTML",
    )

@router.callback_query(F.data == "adm:emj:list")
async def list_emojis(call: CallbackQuery):
    emojis = get_all_emojis()
    if not emojis:
        await call.answer("⚠️ هنوز هیچ ایموجی پریمیومی ثبت نشده است.", show_alert=True)
        return
    lines = ["📋 <b>لیست ایموجی‌های پریمیوم فعال:</b>\n"]
    for base, cid in emojis.items():
        lines.append(f"• {base} ➔ <tg-emoji emoji-id=\"{cid}\">{base}</tg-emoji> (<code>{cid}</code>)")
    await call.message.edit_text("\n".join(lines), reply_markup=emoji_menu_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "adm:emj:del")
async def start_delete_emoji(call: CallbackQuery, state: FSMContext):
    if not get_all_emojis():
        await call.answer("⚠️ لیستی برای حذف وجود ندارد.", show_alert=True)
        return
    await state.set_state(CustomAdminStates.emj_delete)
    await call.message.edit_text(
        "🗑 لطفاً <b>ایموجی ساده (پایه)</b> که می‌خواهید حذف شود را بفرستید:",
        reply_markup=kb([("🔙 انصراف", "adm:emj")]),
        parse_mode="HTML",
    )
    await call.answer()

@router.message(CustomAdminStates.emj_delete, F.text, not_command)
async def confirm_delete_emoji(message: Message, state: FSMContext):
    delete_premium_emoji(message.text.strip())
    await state.clear()
    await message.answer("✅ ایموجی به حالت ساده برگشت.", reply_markup=emoji_menu_kb())


# ----------------- ۲. منوی مستقل رنگ دکمه‌ها (🌈 رنگ دکمه‌ها) -----------------
def color_menu_kb():
    return kb(
        [("🎨 انتخاب دکمه و تغییر رنگ", "adm:clr:pick")],
        [("🟣 تم یکدست بنفش نئون", "adm:clr:theme:purple"), ("🟢 تم یکدست سبز نئون", "adm:clr:theme:green")],
        [("🌈 تم رنگارنگ ویژه (VIP)", "adm:clr:theme:rainbow")],
        [("📋 لیست دکمه‌های رنگی", "adm:clr:list"), ("♻️ حذف همه رنگ‌ها", "adm:clr:reset")],
        [("🔙 بازگشت به پنل مدیریت", "adm:home")],
    )

def color_palette_kb(back_cb: str = "adm:clr:pick"):
    return kb(
        [("🟣 بنفش نئون", "adm:clr:set:purple"), ("🟢 سبز نئون", "adm:clr:set:green")],
        [("🔴 قرمز ویژه", "adm:clr:set:red"), ("🔵 آبی الماسی", "adm:clr:set:blue")],
        [("🟡 طلایی VIP", "adm:clr:set:gold"), ("🟠 نارنجی", "adm:clr:set:orange")],
        [("⚫️ مشکی دارک", "adm:clr:set:dark"), ("⚪️ سفید نقره‌ای", "adm:clr:set:white")],
        [("🗑 حذف رنگ این دکمه", "adm:clr:set:none")],
        [("🔙 بازگشت", back_cb)],
    )

@router.callback_query(F.data == "adm:clr")
async def open_color_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    colors = get_button_colors()
    text = (
        "🌈 <b>مدیریت رنگ دکمه‌های ربات</b>\n\n"
        f"🎨 دکمه‌های دارای رنگ اختصاصی: <b>{len(colors)}</b>\n\n"
        "می‌توانید برای تک‌تک دکمه‌های ربات رنگ دلخواه انتخاب کنید یا با یک کلیک به کل منوی اصلی تم رنگی بدهید:"
    )
    await call.message.edit_text(text, reply_markup=color_menu_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "adm:clr:pick")
async def pick_button_for_color(call: CallbackQuery, state: FSMContext):
    await state.clear()
    detected_raw = get_ui_config("detected_main_buttons")
    rows = []
    if detected_raw:
        try:
            btns = json.loads(detected_raw)
            colors = get_button_colors()
            for i, b in enumerate(btns):
                c_code = colors.get(b["text"]) or colors.get(b["cb"])
                badge = COLOR_PRESETS[c_code]["badge"] + " " if c_code in COLOR_PRESETS else ""
                rows.append([(f"{badge}{b['text']}", f"adm:clr:btn:{i}")])
        except Exception:
            pass
    rows.append([("✍️ تایپ نام یک دکمه دلخواه دیگر", "adm:clr:custom")])
    rows.append([("🔙 بازگشت به منوی رنگ‌ها", "adm:clr")])

    await call.message.edit_text(
        "🎨 <b>انتخاب دکمه برای تغییر رنگ</b>\n\n"
        "یکی از دکمه‌های منوی اصلی زیر را انتخاب کنید (یا گزینه تایپ نام دکمه دلخواه را بزنید):",
        reply_markup=kb(*rows),
        parse_mode="HTML",
    )
    await call.answer()

@router.callback_query(F.data.startswith("adm:clr:btn:"))
async def select_detected_btn_color(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[-1])
    detected_raw = get_ui_config("detected_main_buttons")
    btns = json.loads(detected_raw) if detected_raw else []
    if idx < 0 or idx >= len(btns):
        await call.answer("❌ دکمه یافت نشد.", show_alert=True)
        return
    target_btn = btns[idx]["text"]
    await state.update_data(clr_target=target_btn)
    await call.message.edit_text(
        f"🎨 دکمه انتخاب‌شده: <b>{target_btn}</b>\n\n"
        "حالا رنگ مورد نظر خود را برای این دکمه انتخاب کنید:",
        reply_markup=color_palette_kb("adm:clr:pick"),
        parse_mode="HTML",
    )
    await call.answer()

@router.callback_query(F.data == "adm:clr:custom")
async def ask_custom_btn_color(call: CallbackQuery, state: FSMContext):
    await state.set_state(CustomAdminStates.clr_custom_btn)
    await call.message.edit_text(
        "✍️ لطفاً <b>نام دقیق دکمه</b> مورد نظر را ارسال کنید تا رنگش را انتخاب کنیم:",
        reply_markup=kb([("🔙 انصراف", "adm:clr:pick")]),
        parse_mode="HTML",
    )
    await call.answer()

@router.message(CustomAdminStates.clr_custom_btn, F.text, not_command)
async def receive_custom_btn_for_color(message: Message, state: FSMContext):
    target_btn = message.text.strip()
    await state.update_data(clr_target=target_btn)
    await state.set_state(None)
    await message.answer(
        f"🎨 دکمه انتخاب‌شده: <b>{target_btn}</b>\n\n"
        "حالا رنگ مورد نظر خود را برای این دکمه انتخاب کنید:",
        reply_markup=color_palette_kb("adm:clr:pick"),
        parse_mode="HTML",
    )

@router.callback_query(F.data.startswith("adm:clr:set:"))
async def apply_selected_color(call: CallbackQuery, state: FSMContext):
    color_code = call.data.split(":")[-1]
    data = await state.get_data()
    target_btn = data.get("clr_target")
    if not target_btn:
        await call.answer("⚠️ ابتدا یک دکمه را انتخاب کنید.", show_alert=True)
        return

    if color_code == "none":
        delete_button_color(target_btn)
        await call.answer("✅ رنگ دکمه حذف شد.", show_alert=True)
    else:
        set_button_color(target_btn, color_code)
        title = COLOR_PRESETS[color_code]["title"]
        await call.answer(f"✅ رنگ {title} روی دکمه اعمال شد!", show_alert=True)

    await pick_button_for_color(call, state)

@router.callback_query(F.data.startswith("adm:clr:theme:"))
async def apply_full_theme(call: CallbackQuery, state: FSMContext):
    theme = call.data.split(":")[-1]
    detected_raw = get_ui_config("detected_main_buttons")
    if not detected_raw:
        await call.answer("⚠️ ابتدا یک بار دکمه «🏠 منوی کاربری» را بزنید تا دکمه‌های منو شناسایی شوند.", show_alert=True)
        return
    btns = json.loads(detected_raw)
    rainbow_cycle = ["purple", "green", "blue", "gold", "red", "orange"]
    for i, b in enumerate(btns):
        c = rainbow_cycle[i % len(rainbow_cycle)] if theme == "rainbow" else theme
        set_button_color(b["text"], c)

    await call.answer("🎉 تم رنگی با موفقیت روی تمام دکمه‌های منوی اصلی اعمال شد!", show_alert=True)
    await open_color_menu(call, state)

@router.callback_query(F.data == "adm:clr:list")
async def list_button_colors(call: CallbackQuery):
    colors = get_button_colors()
    if not colors:
        await call.answer("⚠️ هنوز هیچ رنگی برای دکمه‌ها تنظیم نشده است.", show_alert=True)
        return
    lines = ["📋 <b>لیست دکمه‌های رنگی فعال:</b>\n"]
    for k, c in colors.items():
        title = COLOR_PRESETS.get(c, {}).get("title", c)
        lines.append(f"• <b>{k}</b> ➔ {title}")
    await call.message.edit_text("\n".join(lines), reply_markup=color_menu_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "adm:clr:reset")
async def reset_button_colors(call: CallbackQuery, state: FSMContext):
    clear_all_button_colors()
    await call.answer("✅ رنگ تمامی دکمه‌ها به حالت پیش‌فرض برگشت.", show_alert=True)
    await open_color_menu(call, state)


# ----------------- ۳. منوی سفارشی‌سازی دکمه‌ها و متن‌ها -----------------
def ui_menu_kb():
    return kb(
        [("✏️ تغییر نام دکمه‌ها", "adm:ui:btn_rename"), ("📐 تغییر جایگاه دکمه‌ها", "adm:ui:btn_layout")],
        [("📝 تغییر متن‌های ربات", "adm:ui:texts"), ("🌈 رنگ دکمه‌ها", "adm:clr")],
        [("📋 مشاهده تغییرات فعال", "adm:ui:list"), ("♻️ بازنشانی به حالت پیش‌فرض", "adm:ui:reset")],
        [("🔙 بازگشت به پنل مدیریت", "adm:home")],
    )

@router.callback_query(F.data == "adm:ui")
async def open_ui_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    renames = get_button_renames()
    texts = get_text_replacements()
    colors = get_button_colors()
    has_layout = "بله ✅" if get_ui_config("custom_main_layout") else "پیش‌فرض"
    msg = (
        "🎨 <b>پنل سفارشی‌سازی دکمه‌ها و متن‌های ربات</b>\n\n"
        f"🔹 دکمه‌های تغییر نام یافته: <b>{len(renames)}</b>\n"
        f"🌈 دکمه‌های رنگ‌شده: <b>{len(colors)}</b>\n"
        f"🔸 چیدمان سفارشی منو: <b>{has_layout}</b>\n"
        f"📝 متن‌های ویرایش‌شده: <b>{len(texts)}</b>\n\n"
        "از طریق گزینه‌های زیر می‌توانید نام، رنگ و جایگاه دکمه‌ها یا هر متنی در ربات را به دلخواه تغییر دهید:"
    )
    await call.message.edit_text(msg, reply_markup=ui_menu_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "adm:ui:btn_rename")
async def start_btn_rename(call: CallbackQuery, state: FSMContext):
    await state.set_state(CustomAdminStates.btn_old_name)
    detected_raw = get_ui_config("detected_main_buttons")
    hint = ""
    if detected_raw:
        try:
            btns = json.loads(detected_raw)
            hint = "\n\n💡 <b>دکمه‌های منوی اصلی فعلی (برای کپی راحت):</b>\n" + "\n".join(f"• <code>{b['text']}</code>" for b in btns)
        except Exception:
            pass
    await call.message.edit_text(
        "✏️ <b>تغییر نام دکمه</b>\n\n"
        "1️⃣ لطفاً <b>نام فعلی دکمه</b> را ارسال کنید:" + hint,
        reply_markup=kb([("🗑 حذف یک تغییر نام", "adm:ui:btn_del")], [("🔙 بازگشت", "adm:ui")]),
        parse_mode="HTML",
    )
    await call.answer()

@router.message(CustomAdminStates.btn_old_name, F.text, not_command)
async def receive_btn_old_name(message: Message, state: FSMContext):
    await state.update_data(old_label=message.text.strip())
    await state.set_state(CustomAdminStates.btn_new_name)
    await message.answer(
        f"✅ دکمه «{message.text.strip()}» انتخاب شد.\n\n"
        "2️⃣ حالا <b>نام جدید دکمه</b> را ارسال کنید:",
        reply_markup=kb([("🔙 انصراف", "adm:ui")]),
    )

@router.message(CustomAdminStates.btn_new_name, F.text, not_command)
async def receive_btn_new_name(message: Message, state: FSMContext):
    data = await state.get_data()
    old_label = data["old_label"]
    new_label = message.text.strip()
    set_button_rename(old_label, new_label)
    await state.clear()
    await message.answer(
        f"🎉 نام دکمه با موفقیت تغییر کرد!\n\n"
        f"قبلی: {old_label}\nجدید: {new_label}",
        reply_markup=ui_menu_kb(),
    )

@router.callback_query(F.data == "adm:ui:btn_del")
async def start_btn_del(call: CallbackQuery, state: FSMContext):
    renames = get_button_renames()
    if not renames:
        await call.answer("⚠️ هیچ تغییر نامی ثبت نشده است.", show_alert=True)
        return
    await state.set_state(CustomAdminStates.btn_del_name)
    lines = ["🗑 نام اصلی دکمه‌ای که می‌خواهید به حالت قبل برگردد را بفرستید:\n"]
    for k, v in renames.items():
        lines.append(f"• <code>{k}</code> (فعلی: {v})")
    await call.message.edit_text("\n".join(lines), reply_markup=kb([("🔙 بازگشت", "adm:ui")]), parse_mode="HTML")
    await call.answer()

@router.message(CustomAdminStates.btn_del_name, F.text, not_command)
async def confirm_btn_del(message: Message, state: FSMContext):
    delete_button_rename(message.text.strip())
    await state.clear()
    await message.answer("✅ نام دکمه به حالت اولیه بازگشت.", reply_markup=ui_menu_kb())

@router.callback_query(F.data == "adm:ui:btn_layout")
async def start_btn_layout(call: CallbackQuery, state: FSMContext):
    detected_raw = get_ui_config("detected_main_buttons")
    if not detected_raw:
        await call.answer("⚠️ ابتدا یک بار دکمه «🏠 منوی کاربری» یا /start را بزنید تا دکمه‌های منو شناسایی شوند.", show_alert=True)
        return
    btns = json.loads(detected_raw)
    await state.set_state(CustomAdminStates.btn_layout_order)
    await state.update_data(detected_btns=btns)

    list_str = "\n".join(f"<b>{i+1}.</b> {b['text']}" for i, b in enumerate(btns))
    help_text = (
        "📐 <b>تغییر جایگاه و چیدمان دکمه‌های منوی اصلی</b>\n\n"
        "لیست دکمه‌های منوی اصلی با شماره آن‌ها:\n"
        f"{list_str}\n\n"
        "💡 <b>نحوه چیدمان:</b>\n"
        "شماره دکمه‌هایی که می‌خواهید در یک ردیف باشند را با <code>,</code> جدا کنید و هر ردیف جدید را در یک خط جدید بنویسید.\n\n"
        "مثال:\n"
        "<code>1\n2,3\n4,5\n6</code>"
    )
    await call.message.edit_text(
        help_text,
        reply_markup=kb([("♻️ بازگشت چیدمان به پیش‌فرض", "adm:ui:layout_reset")], [("🔙 انصراف", "adm:ui")]),
        parse_mode="HTML",
    )
    await call.answer()

@router.callback_query(F.data == "adm:ui:layout_reset")
async def reset_btn_layout(call: CallbackQuery, state: FSMContext):
    set_ui_config("custom_main_layout", "")
    await state.clear()
    await call.message.edit_text("✅ چیدمان دکمه‌های منوی اصلی به حالت پیش‌فرض برگشت.", reply_markup=ui_menu_kb())
    await call.answer()

@router.message(CustomAdminStates.btn_layout_order, F.text, not_command)
async def receive_btn_layout_order(message: Message, state: FSMContext):
    data = await state.get_data()
    btns = data.get("detected_btns", [])
    raw = message.text.strip().replace("-", "
")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]

    new_grid = []
    used = set()
    try:
        for line in lines:
            row_cbs = []
            for part in line.split(","):
                idx = int(part.strip()) - 1
                if idx < 0 or idx >= len(btns):
                    raise ValueError("Out of range")
                cb = btns[idx]["cb"]
                if cb not in used:
                    row_cbs.append(cb)
                    used.add(cb)
            if row_cbs:
                new_grid.append(row_cbs)
        for b in btns:
            if b["cb"] not in used:
                new_grid.append([b["cb"]])
    except Exception:
        await message.answer("❌ فرمت واردشده صحیح نیست. فقط از شماره‌های لیست و کاما (,) استفاده کنید:")
        return

    set_ui_config("custom_main_layout", json.dumps(new_grid))
    await state.clear()
    await message.answer("🎉 <b>چیدمان و جایگاه دکمه‌های منوی اصلی با موفقیت بروزرسانی شد!</b>", reply_markup=ui_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "adm:ui:texts")
async def start_text_replace(call: CallbackQuery, state: FSMContext):
    await state.set_state(CustomAdminStates.txt_old)
    await call.message.edit_text(
        "📝 <b>تغییر متن‌های ربات</b>\n\n"
        "1️⃣ لطفاً <b>متن فعلی</b> (یا بخشی از جمله فعلی ربات که می‌خواهید عوض شود) را دقیقاً ارسال کنید:",
        reply_markup=kb([("🗑 حذف یک متن جایگزین", "adm:ui:txt_del")], [("🔙 بازگشت", "adm:ui")]),
        parse_mode="HTML",
    )
    await call.answer()

@router.message(CustomAdminStates.txt_old, F.text, not_command)
async def receive_old_text(message: Message, state: FSMContext):
    await state.update_data(old_text=message.text.strip())
    await state.set_state(CustomAdminStates.txt_new)
    await message.answer(
        "✅ متن فعلی دریافت شد.\n\n"
        "2️⃣ حالا <b>متن جدید</b> را ارسال کنید تا در تمام پیام‌های ربات جایگزین آن شود:",
        reply_markup=kb([("🔙 انصراف", "adm:ui")]),
    )

@router.message(CustomAdminStates.txt_new, F.text, not_command)
async def receive_new_text(message: Message, state: FSMContext):
    data = await state.get_data()
    set_text_replacement(data["old_text"], message.text.strip())
    await state.clear()
    await message.answer("🎉 <b>متن جدید با موفقیت ثبت و جایگزین شد!</b>", reply_markup=ui_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "adm:ui:txt_del")
async def start_txt_del(call: CallbackQuery, state: FSMContext):
    rows = get_text_replacements()
    if not rows:
        await call.answer("⚠️ هیچ تغییر متنی ثبت نشده است.", show_alert=True)
        return
    await state.set_state(CustomAdminStates.txt_del_id)
    lines = ["🗑 <b>شماره (کد) متنی که می‌خواهید حذف شود را بفرستید:</b>\n"]
    for rid, old_t, new_t in rows:
        lines.append(f"🆔 <code>{rid}</code> : «{old_t[:25]}...» ➔ «{new_t[:25]}...»")
    await call.message.edit_text("\n".join(lines), reply_markup=kb([("🔙 بازگشت", "adm:ui")]), parse_mode="HTML")
    await call.answer()

@router.message(CustomAdminStates.txt_del_id, F.text, not_command)
async def confirm_txt_del(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ لطفاً فقط عدد کد را ارسال کنید:")
        return
    delete_text_replacement(int(message.text.strip()))
    await state.clear()
    await message.answer("✅ تغییر متن مورد نظر حذف شد.", reply_markup=ui_menu_kb())

@router.callback_query(F.data == "adm:ui:list")
async def list_ui_changes(call: CallbackQuery):
    renames = get_button_renames()
    texts = get_text_replacements()
    colors = get_button_colors()
    lines = ["📋 <b>لیست تغییرات فعال رابط کاربری:</b>\n"]
    if renames:
        lines.append("🔹 <b>تغییر نام دکمه‌ها:</b>")
        for k, v in renames.items():
            lines.append(f"• {k} ➔ {v}")
        lines.append("")
    if colors:
        lines.append("🌈 <b>رنگ دکمه‌ها:</b>")
        for k, c in colors.items():
            lines.append(f"• {k} ➔ {COLOR_PRESETS.get(c, {}).get('title', c)}")
        lines.append("")
    if texts:
        lines.append("📝 <b>تغییر متن‌ها:</b>")
        for rid, o, n in texts:
            lines.append(f"• [{rid}] {o[:20]} ➔ {n[:20]}")
    if not renames and not texts and not colors and not get_ui_config("custom_main_layout"):
        await call.answer("⚠️ هیچ تغییری ثبت نشده است.", show_alert=True)
        return
    await call.message.edit_text("\n".join(lines), reply_markup=ui_menu_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "adm:ui:reset")
async def reset_all_ui(call: CallbackQuery):
    for k in list(get_button_renames().keys()):
        delete_button_rename(k)
    for rid, _, _ in get_text_replacements():
        delete_text_replacement(rid)
    clear_all_button_colors()
    set_ui_config("custom_main_layout", "")
    await call.answer("✅ تمام دکمه‌ها، رنگ‌ها و متن‌ها به حالت پیش‌فرض بازگشتند.", show_alert=True)
    await call.message.edit_text(
        "✅ تمام تنظیمات ظاهری، رنگ‌ها، نام دکمه‌ها و متن‌ها به حالت پیش‌فرض برگشت.",
        reply_markup=ui_menu_kb()
    )
