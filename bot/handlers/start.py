from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from backend.services.settings_service import get_settings_map
from bot.keyboards.menus import main_menu_kb
from bot.utils import edit_or_answer, safe_format

router = Router()


async def _start_text(session, tg_user) -> str:
    cfg = await get_settings_map(session, ["start_message", "shop_name"])
    return safe_format(cfg["start_message"] or "سلام {name} 👋", name=tg_user.first_name or "دوست عزیز",
                       shop=cfg["shop_name"] or "CAPITAN VPN")


@router.message(CommandStart())
async def cmd_start(message: Message, session, state: FSMContext, is_admin: bool = False):
    await state.clear()
    await message.answer(await _start_text(session, message.from_user), reply_markup=main_menu_kb(is_admin))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("لغو شد. برای بازگشت به منو /start را بزنید.")


@router.callback_query(F.data == "menu:main")
async def back_to_main(cb: CallbackQuery, session, state: FSMContext, is_admin: bool = False):
    await state.clear()
    await edit_or_answer(cb, await _start_text(session, cb.from_user), main_menu_kb(is_admin))
    await cb.answer()
