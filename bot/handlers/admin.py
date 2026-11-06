from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"🆔 آیدی عددی شما: {message.from_user.id}")
