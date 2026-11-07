from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb


def kb(*rows) -> Kb:
    """rows: lists of (text, callback_data)"""
    return Kb(inline_keyboard=[[Btn(text=t, callback_data=d) for t, d in row] for row in rows])
