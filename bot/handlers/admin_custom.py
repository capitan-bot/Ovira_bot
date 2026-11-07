import html
import sqlite3
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from bot.ui_manager import (
    set_premium_emoji, delete_premium_emoji, get_all_emojis,
    set_text_replacement, delete_text_replacement, get_text_replacements,
    set_button_rename, delete_button_rename, get_button_renames,
    set_button_color, delete_button_color, get_button_colors,
    get_seen_buttons, get_seen_button, section_of, SECTIONS,
    get_seen_lines, get_seen_line,
    get_ui_config, set_ui_config,
)


router = Router()

class CustomUIStates(StatesGroup):
    waiting_for_base_emoji = State()
    waiting_for_premium_emoji = State()
    waiting_for_color_target = State()
    waiting_for_color_style = State()
    waiting_for_rename_old = State()
    waiting_for_rename_new = State()
    waiting_for_text_old = State()
    waiting_for_text_new = State()
    waiting_for_welcome = State()

def main_custom_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✨ ایموجی پریمیوم", callback_data="admin:custom_emojis"),
            InlineKeyboardButton(text="✏️ تغییر نام دکمه‌ها", callback_data="admin:custom_renames")
        ],
        [
            InlineKeyboardButton(text="📝 تغییر متن‌های ربات", callback_data="admin:custom_texts")
        ],
        [
            InlineKeyboardButton(text="🎨 رنگ دکمه‌ها", callback_data="admin:colors"),
            InlineKeyboardButton(text="👋 متن خوش‌آمدگویی", callback_data="admin:welcome")
        ],
        [
            InlineKeyboardButton(text="♻️ بازنشانی کل ظاهر", callback_data="admin:custom_reset")
        ],
        [
            InlineKeyboardButton(text="🔙 بازگشت به پنل مدیریت", callback_data="adm:home")
        ]
    ])

@router.callback_query(F.data.in_({"adm:ui", "admin:custom"}))
async def admin_custom_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    emojis = get_all_emojis()
    renames = get_button_renames()
    replacements = get_text_replacements()
    colors = get_button_colors()
    
    text = (
        "🛠 <b>مدیریت تغییرات ظاهری ربات</b>\n\n"
        f"✨ ایموجی‌های پریمیوم فعال: {len(emojis)}\n"
        f"✏️ تغییر نام دکمه‌ها: {len(renames)}\n"
        f"📝 متن‌های ویرایش‌شده: {len(replacements)}\n"
        f"🎨 دکمه‌های رنگ‌شده: {len(colors)}\n\n"
        "از طریق دکمه‌های زیر می‌توانید تمام بخش‌های ظاهری ربات را به دلخواه شخصی‌سازی کنید:"
    )
    
    await callback.message.edit_text(text, reply_markup=main_custom_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin:back_panel")
async def back_to_admin_panel(callback: CallbackQuery, session, state: FSMContext):
    await state.clear()
    await cmd_admin(callback.message, session, state)
    await callback.answer()

# ==================== ۱. ایموجی پریمیوم ====================
@router.callback_query(F.data == "admin:custom_emojis")
async def custom_emojis_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    emojis = get_all_emojis()
    text = "✨ <b>مدیریت ایموجی‌های پریمیوم</b>\n\nلیست ایموجی‌های جایگزین‌شده:\n"
    if not emojis:
        text += "هیچ ایموجی سفارشی ثبت نشده است.\n"
    else:
        for k, v in emojis.items():
            text += f"• پایه: {k} ➔ شناسه: <code>{v}</code>\n"
            
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن / ویرایش ایموجی", callback_data="admin:emoji_add")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:ui")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin:emoji_add")
async def emoji_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomUIStates.waiting_for_base_emoji)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="admin:custom_emojis")]
    ])
    await callback.message.edit_text(
        "1️⃣ لطفاً ابتدا ایموجی ساده (پایه) را بفرستید (مثلاً ❤️ یا 🔥):",
        reply_markup=keyboard
    )
    await callback.answer()

@router.message(CustomUIStates.waiting_for_base_emoji)
async def emoji_receive_base(message: Message, state: FSMContext):
    base_text = (message.text or message.caption or "").strip()
    if not base_text:
        await message.answer("❌ لطفاً یک ایموجی معتبر ارسال کنید.")
        return
    
    await state.update_data(base_emoji=base_text)
    await state.set_state(CustomUIStates.waiting_for_premium_emoji)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="admin:custom_emojis")]
    ])
    await message.answer(
        f"✅ ایموجی پایه ( {base_text} ) دریافت شد.\n\n"
        "2️⃣ حالا ایموجی پریمیوم مورد نظر را ارسال کنید تا جایگزین آن شود:",
        reply_markup=keyboard
    )

@router.message(CustomUIStates.waiting_for_premium_emoji)
async def emoji_receive_premium(message: Message, state: FSMContext):
    custom_emoji_id = None
    if message.entities:
        for entity in message.entities:
            if entity.type == "custom_emoji":
                custom_emoji_id = str(entity.custom_emoji_id)
                break
    
    if not custom_emoji_id and message.text and message.text.strip().isdigit():
        custom_emoji_id = message.text.strip()

    data = await state.get_data()
    base_emoji = data.get("base_emoji")
    
    if custom_emoji_id and base_emoji:
        set_premium_emoji(base_emoji, custom_emoji_id)
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت به لیست ایموجی‌ها", callback_data="admin:custom_emojis")]
        ])
        await message.answer(
            f"✅ ایموجی پریمیوم با موفقیت برای ( {base_emoji} ) ثبت شد!\nشناسه: <code>{custom_emoji_id}</code>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        await message.answer("❌ ایموجی ارسالی پریمیوم نبود! لطفاً یک ایموجی پریمیوم تلگرام (یا شناسه عددی آن) را بفرستید.")

# ==================== ۲. رنگ دکمه‌ها ====================
@router.callback_query(F.data == "admin:colors")
async def custom_colors_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    colors = get_button_colors()
    text = "🎨 <b>مدیریت رنگ دکمه‌ها</b>\n\nلیست رنگ‌های تنظیم‌شده:\n"
    if not colors:
        text += "هیچ رنگی ثبت نشده است.\n"
    else:
        for k, v in colors.items():
            text += f"• دکمه: <code>{k}</code> ➔ رنگ: <b>{v}</b>\n"
            
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن / تغییر رنگ دکمه", callback_data="admin:color_add")],
        [InlineKeyboardButton(text="🗑 حذف همه رنگ‌ها", callback_data="admin:color_clear")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:ui")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

STYLE_ICON = {"primary": "🔵", "success": "🟢", "danger": "🔴"}
STYLE_NAME = {"primary": "آبی", "success": "سبز", "danger": "قرمز"}

def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _btn(text, cb):
    return InlineKeyboardButton(text=text, callback_data=cb)

@router.callback_query(F.data == "admin:color_add")
async def color_add_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    counts = {}
    for _id, key, _label in get_seen_buttons():
        sec = section_of(key)
        counts[sec] = counts.get(sec, 0) + 1
    rows = [[_btn(f"{title} ({counts[sec]})", f"admin:colsec:{sec}")]
            for sec, title, _ in SECTIONS if counts.get(sec)]
    has = len(rows) > 0
    rows.append([_btn("🔙 بازگشت", "admin:colors")])
    text = ("1️⃣ <b>بخش</b> مورد نظر را انتخاب کنید:" if has else
            "هنوز دکمه‌ای ثبت نشده. یک‌بار /start را در ربات بزنید و بعد دوباره بیایید.")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_kb(rows))
    await callback.answer()

@router.callback_query(F.data.regexp(r"^admin:colsec:\w+$"))
async def color_section(callback: CallbackQuery, state: FSMContext):
    sec = callback.data.split(":")[2]
    title = next((t for s_, t, _ in SECTIONS if s_ == sec), sec)
    colors = get_button_colors()
    rows = []
    for bid, key, label in get_seen_buttons():
        if section_of(key) == sec:
            mark = STYLE_ICON.get(colors.get(key), "⚪️")
            rows.append([_btn(f"{mark} {label}", f"admin:colbtn:{bid}")])
    rows.append([_btn("🔙 بازگشت به بخش‌ها", "admin:color_add")])
    await callback.message.edit_text(f"{title}\n\n2️⃣ دکمه را انتخاب کنید:", reply_markup=_kb(rows))
    await callback.answer()

@router.callback_query(F.data.regexp(r"^admin:colbtn:\d+$"))
async def color_pick_button(callback: CallbackQuery, state: FSMContext):
    bid = int(callback.data.split(":")[2])
    row = get_seen_button(bid)
    if not row:
        await callback.answer("دکمه پیدا نشد", show_alert=True)
        return
    _id, key, label = row
    cur = STYLE_NAME.get(get_button_colors().get(key), "پیش‌فرض")
    rows = [
        [_btn("🔵 آبی", f"admin:colset:{bid}:primary")],
        [_btn("🟢 سبز", f"admin:colset:{bid}:success")],
        [_btn("🔴 قرمز", f"admin:colset:{bid}:danger")],
        [_btn("⚪️ پیش‌فرض (حذف رنگ)", f"admin:colset:{bid}:default")],
        [_btn("🔙 بازگشت", f"admin:colsec:{section_of(key)}")],
    ]
    await callback.message.edit_text(
        f"دکمه: <b>{html.escape(label)}</b>\nرنگ فعلی: {cur}\n\n3️⃣ رنگ را انتخاب کنید:",
        parse_mode="HTML", reply_markup=_kb(rows))
    await callback.answer()

@router.callback_query(F.data.regexp(r"^admin:colset:\d+:(primary|success|danger|default)$"))
async def color_apply(callback: CallbackQuery, state: FSMContext):
    _, _, bid, style = callback.data.split(":")
    row = get_seen_button(int(bid))
    if not row:
        await callback.answer("دکمه پیدا نشد", show_alert=True)
        return
    _id, key, label = row
    if style == "default":
        delete_button_color(key)
        msg = f"⚪️ رنگ دکمه <b>{html.escape(label)}</b> به حالت پیش‌فرض برگشت."
    else:
        set_button_color(key, style)
        msg = f"✅ دکمه <b>{html.escape(label)}</b> → {STYLE_ICON[style]} {STYLE_NAME[style]}"
    rows = [[_btn("🔙 بازگشت به همان بخش", f"admin:colsec:{section_of(key)}")],
            [_btn("🎨 مدیریت رنگ‌ها", "admin:colors")]]
    await callback.message.edit_text(msg, parse_mode="HTML", reply_markup=_kb(rows))
    await callback.answer()

@router.callback_query(F.data == "admin:color_clear")
async def color_clear_all(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    db_path = Path("storage/customization.db")
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM button_colors")
            conn.commit()
    await custom_colors_list(callback, state)

# ==================== ۳. تغییر نام دکمه‌ها ====================
@router.callback_query(F.data == "admin:custom_renames")
async def custom_renames_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    renames = get_button_renames()
    text = "✏️ <b>تغییر نام دکمه‌ها</b>\n\nلیست نام‌های سفارشی:\n"
    if not renames:
        text += "هیچ نام سفارشی ثبت نشده است.\n"
    else:
        for k, v in renames.items():
            text += f"• <code>{k}</code> ➔ <code>{v}</code>\n"
            
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ تغییر نام جدید", callback_data="admin:rename_add")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:ui")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin:rename_add")
async def rename_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomUIStates.waiting_for_rename_old)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="admin:custom_renames")]
    ])
    await callback.message.edit_text("1️⃣ لطفاً <b>نام فعلی دکمه</b> را ارسال کنید:", parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@router.message(CustomUIStates.waiting_for_rename_old)
async def rename_receive_old(message: Message, state: FSMContext):
    old_name = (message.text or "").strip()
    if not old_name:
        return
    await state.update_data(old_name=old_name)
    await state.set_state(CustomUIStates.waiting_for_rename_new)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="admin:custom_renames")]
    ])
    await message.answer(f"✅ نام فعلی ( {old_name} ) دریافت شد.\n\n2️⃣ حالا <b>نام جدید</b> دکمه را ارسال کنید:", parse_mode="HTML", reply_markup=keyboard)

@router.message(CustomUIStates.waiting_for_rename_new)
async def rename_receive_new(message: Message, state: FSMContext):
    new_name = (message.text or "").strip()
    data = await state.get_data()
    old_name = data.get("old_name")
    if old_name and new_name:
        set_button_rename(old_name, new_name)
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin:custom_renames")]
        ])
        await message.answer(f"✅ نام دکمه از «{old_name}» به «{new_name}» تغییر یافت.", reply_markup=keyboard)

# ==================== ۴. تغییر متن‌های ربات ====================
@router.callback_query(F.data == "admin:custom_texts")
async def custom_texts_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    replacements = get_text_replacements()
    text = "📝 <b>تغییر متن‌های ربات</b>\n\nلیست جایگزینی متن‌ها:\n"
    if not replacements:
        text += "هیچ قانون جایگزینی ثبت نشده است.\n"
    else:
        for r_id, old_t, new_t in replacements:
            text += f"• [{r_id}] <code>{old_t}</code> ➔ <code>{new_t}</code>\n"
            
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن قانون متن", callback_data="admin:tx_add")],
        [InlineKeyboardButton(text="✍️ ورود دستی متن", callback_data="admin:text_add")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:ui")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin:text_add")
async def text_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomUIStates.waiting_for_text_old)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="admin:custom_texts")]
    ])
    await callback.message.edit_text("1️⃣ لطفاً <b>متن فعلی</b> را بفرستید:", parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@router.message(CustomUIStates.waiting_for_text_old)
async def text_receive_old(message: Message, state: FSMContext):
    old_t = (message.text or "").strip()
    if not old_t:
        return
    await state.update_data(old_t=old_t)
    await state.set_state(CustomUIStates.waiting_for_text_new)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="admin:custom_texts")]
    ])
    await message.answer("✅ متن فعلی دریافت شد.\n\n2️⃣ حالا <b>متن جدید</b> را ارسال کنید:", parse_mode="HTML", reply_markup=keyboard)

@router.message(CustomUIStates.waiting_for_text_new)
async def text_receive_new(message: Message, state: FSMContext):
    new_t = (message.text or "").strip()
    data = await state.get_data()
    old_t = data.get("old_t")
    if old_t and new_t:
        set_text_replacement(old_t, new_t)
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin:custom_texts")]
        ])
        await message.answer("✅ جایگزینی متن با موفقیت ثبت شد.", reply_markup=keyboard)

# ---------- متن خوش‌آمدگویی ----------
WELCOME_DEFAULT_EXAMPLE = "👋 سلام {name}\nبه فروشگاه CAPITAN VPN خوش آمدید.\nاز منوی زیر ادامه دهید."

@router.callback_query(F.data == "admin:welcome")
async def welcome_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    cur = get_ui_config("welcome_text")
    shown = (f"<code>{html.escape(cur)}</code>" if cur else "پیش‌فرض ربات (تغییری داده نشده)")
    rows = [
        [_btn("✏️ تنظیم متن جدید", "admin:welcome_set")],
        [_btn("♻️ بازگشت به پیش‌فرض", "admin:welcome_reset")],
        [_btn("🔙 بازگشت", "adm:ui")],
    ]
    await callback.message.edit_text(
        f"👋 <b>متن خوش‌آمدگویی</b>\n\nمتن فعلی:\n{shown}",
        parse_mode="HTML", reply_markup=_kb(rows))
    await callback.answer()

@router.callback_query(F.data == "admin:welcome_set")
async def welcome_set_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomUIStates.waiting_for_welcome)
    rows = [[_btn("❌ انصراف", "admin:welcome")]]
    await callback.message.edit_text(
        "متن جدید خوش‌آمدگویی را بفرستید.\n\n"
        "• جای اسم کاربر را با <code>{name}</code> بنویسید.\n"
        "• می‌توانید چند خط، ایموجی و فرمت (بولد، ایتالیک) هم بزنید.\n\n"
        "مثال:\n<code>" + html.escape(WELCOME_DEFAULT_EXAMPLE) + "</code>",
        parse_mode="HTML", reply_markup=_kb(rows))
    await callback.answer()

@router.message(CustomUIStates.waiting_for_welcome)
async def welcome_receive(message: Message, state: FSMContext):
    txt = (message.html_text or "").strip()
    if not txt:
        await message.answer("❌ لطفاً یک متن معتبر بفرستید.")
        return
    set_ui_config("welcome_text", txt)
    await state.clear()
    await message.answer("✅ متن خوش‌آمدگویی ذخیره شد. برای دیدنش در ربات /start بزنید.",
                         reply_markup=_kb([[_btn("🔙 بازگشت", "admin:welcome")]]))

@router.callback_query(F.data == "admin:welcome_reset")
async def welcome_reset(callback: CallbackQuery, state: FSMContext):
    set_ui_config("welcome_text", "")
    await callback.answer("به حالت پیش‌فرض برگشت ✅", show_alert=True)
    await welcome_menu(callback, state)

# ---------- انتخاب متن از لیست (بخش‌بندی‌شده) ----------
TX_SECTIONS = [(s_, t_) for s_, t_, _ in SECTIONS if s_ != "admin"]

def _tx_label(line: str) -> str:
    import re as _re
    clean = _re.sub(r"<[^>]+>", "", line).strip()
    return clean[:45] if clean else line[:45]

@router.callback_query(F.data == "admin:tx_add")
async def tx_sections(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    counts = {}
    for _id, sec, _l in get_seen_lines():
        counts[sec] = counts.get(sec, 0) + 1
    rows = [[_btn(f"{t} ({counts[s_]})", f"admin:txsec:{s_}")]
            for s_, t in TX_SECTIONS if counts.get(s_)]
    has = len(rows) > 0
    rows.append([_btn("✍️ ورود دستی متن", "admin:text_add")])
    rows.append([_btn("🔙 بازگشت", "admin:custom_texts")])
    text = ("1️⃣ <b>بخش</b> مورد نظر را انتخاب کنید:" if has else
            "هنوز متنی ثبت نشده. چند صفحه ربات را باز کنید (مثلاً /start، خرید، سرویس‌ها) و دوباره بیایید.")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_kb(rows))
    await callback.answer()

@router.callback_query(F.data.startswith("admin:txsec:"))
async def tx_section(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    sec = callback.data.split(":")[2]
    title = next((t for s_, t in TX_SECTIONS if s_ == sec), sec)
    rows = []
    for lid, lsec, line in get_seen_lines():
        if lsec == sec and len(rows) < 60:
            rows.append([_btn(_tx_label(line), f"admin:txline:{lid}")])
    rows.append([_btn("🔙 بازگشت به بخش‌ها", "admin:tx_add")])
    await callback.message.edit_text(f"{title}\n\n2️⃣ متنی که می‌خواهید عوض شود را انتخاب کنید:",
                                     reply_markup=_kb(rows))
    await callback.answer()

@router.callback_query(F.data.startswith("admin:txline:"))
async def tx_pick_line(callback: CallbackQuery, state: FSMContext):
    lid = int(callback.data.split(":")[2])
    row = get_seen_line(lid)
    if not row:
        await callback.answer("متن پیدا نشد", show_alert=True)
        return
    _id, sec, line = row
    await state.update_data(old_t=line)
    await state.set_state(CustomUIStates.waiting_for_text_new)
    rows = [[_btn("❌ انصراف", f"admin:txsec:{sec}")]]
    await callback.message.edit_text(
        f"متن فعلی:\n<code>{html.escape(line)}</code>\n\n3️⃣ حالا <b>متن جدید</b> را بفرستید:",
        parse_mode="HTML", reply_markup=_kb(rows))
    await callback.answer()

# ==================== ۵. بازنشانی کل ظاهر ====================
@router.callback_query(F.data == "admin:custom_reset")
async def custom_reset_all(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ بله، پاکسازی کامل", callback_data="admin:reset_confirm")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="adm:ui")]
    ])
    await callback.message.edit_text("⚠️ آیا از پاکسازی و بازنشانی تمام تنظیمات ظاهری اطمینان دارید؟", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "admin:reset_confirm")
async def custom_reset_confirmed(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    db_path = Path("storage/customization.db")
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            for tbl in ("premium_emojis", "text_replacements", "button_renames", "ui_config", "button_colors"):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
    await callback.message.edit_text("✅ تمام تنظیمات ظاهری با موفقیت بازنشانی شد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:ui")]
    ]))
    await callback.answer()
