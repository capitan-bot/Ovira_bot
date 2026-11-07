from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.filters import AdminOnly, not_command
from bot.keyboards.admin import kb
from bot.emoji_manager import init_emoji_db, set_premium_emoji, delete_premium_emoji, get_all_emojis

router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())

init_emoji_db()

class EmojiAdminStates(StatesGroup):
    waiting_base = State()
    waiting_premium = State()
    waiting_delete = State()

def emoji_menu_kb():
    return kb(
        [("➕ افزودن / جایگزینی ایموجی", "adm:emj:add")],
        [("🗑 حذف ایموجی", "adm:emj:del"), ("📋 لیست ایموجی‌ها", "adm:emj:list")],
        [("🔙 بازگشت به پنل مدیریت", "adm:home")],
    )

def cancel_emoji_kb():
    return kb([("🔙 انصراف و بازگشت", "adm:emj")])

@router.callback_query(F.data == "adm:emj")
async def open_emoji_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    emojis = get_all_emojis()
    text = (
        "✨ <b>مدیریت ایموجی‌های پریمیوم ربات</b>\n\n"
        f"📊 تعداد ایموجی‌های جایگزین‌شده فعال: <b>{len(emojis)}</b>\n\n"
        "از طریق دکمه‌های زیر می‌توانید یک ایموجی ساده را با ایموجی پریمیوم دلخواه جایگزین کنید تا در تمام متن‌های ربات به صورت متحرک نمایش داده شود:"
    )
    await call.message.edit_text(text, reply_markup=emoji_menu_kb(), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "adm:emj:add")
async def start_add_emoji(call: CallbackQuery, state: FSMContext):
    await state.set_state(EmojiAdminStates.waiting_base)
    await call.message.edit_text(
        "1️⃣ لطفاً ابتدا <b>ایموجی ساده (پایه)</b> مورد نظر خود را ارسال کنید (مثلاً ❤️ یا 🔥):",
        reply_markup=cancel_emoji_kb(),
        parse_mode="HTML",
    )
    await call.answer()

@router.message(EmojiAdminStates.waiting_base, F.text, not_command)
async def receive_base_emoji(message: Message, state: FSMContext):
    base = message.text.strip()
    if not base or len(base) > 8:
        await message.answer("❌ لطفاً فقط یک ایموجی ساده ارسال کنید:", reply_markup=cancel_emoji_kb())
        return
    await state.update_data(base_emoji=base)
    await state.set_state(EmojiAdminStates.waiting_premium)
    await message.answer(
        f"✅ ایموجی پایه ( {base} ) دریافت شد.\n\n"
        "2️⃣ حالا <b>ایموجی پریمیوم</b> متناظر را ارسال کنید تا جایگزین آن شود:",
        reply_markup=cancel_emoji_kb(),
        parse_mode="HTML",
    )

@router.message(EmojiAdminStates.waiting_premium, not_command)
async def receive_premium_emoji(message: Message, state: FSMContext):
    entities = message.entities or message.caption_entities or []
    custom_id = None
    for ent in entities:
        if ent.type == "custom_emoji" and getattr(ent, "custom_emoji_id", None):
            custom_id = ent.custom_emoji_id
            break

    if not custom_id:
        await message.answer(
            "❌ این پیام حاوی ایموجی پریمیوم تلگرام نیست!\n"
            "لطفاً از بخش ایموجی‌های پریمیوم تلگرام یک ایموجی ارسال کنید:",
            reply_markup=cancel_emoji_kb(),
        )
        return

    data = await state.get_data()
    base = data["base_emoji"]
    set_premium_emoji(base, custom_id)
    await state.clear()

    await message.answer(
        f"🎉 <b>جایگزینی با موفقیت انجام شد!</b>\n\n"
        f"🔹 ایموجی پایه: {base}\n"
        f"🔸 پیش‌نمایش پریمیوم: <tg-emoji emoji-id=\"{custom_id}\">{base}</tg-emoji>\n"
        f"🆔 کد پریمیوم: <code>{custom_id}</code>",
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
    emojis = get_all_emojis()
    if not emojis:
        await call.answer("⚠️ لیستی برای حذف وجود ندارد.", show_alert=True)
        return
    await state.set_state(EmojiAdminStates.waiting_delete)
    await call.message.edit_text(
        "🗑 لطفاً <b>ایموجی ساده (پایه)</b> که می‌خواهید حالت پریمیوم آن حذف شود را ارسال کنید:",
        reply_markup=cancel_emoji_kb(),
        parse_mode="HTML",
    )
    await call.answer()

@router.message(EmojiAdminStates.waiting_delete, F.text, not_command)
async def confirm_delete_emoji(message: Message, state: FSMContext):
    base = message.text.strip()
    delete_premium_emoji(base)
    await state.clear()
    await message.answer(
        f"✅ ایموجی ( {base} ) از لیست پریمیوم حذف شد و به حالت عادی برگشت.",
        reply_markup=emoji_menu_kb(),
    )
