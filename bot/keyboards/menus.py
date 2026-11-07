from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb


def main_menu_kb(is_admin: bool = False) -> Kb:
    rows = [
        [Btn(text="🛒 خرید اشتراک", callback_data="menu:buy")],
        [Btn(text="🎁 تست رایگان", callback_data="menu:test")],
        [Btn(text="💳 کیف پول من", callback_data="menu:wallet"),
         Btn(text="📦 سرویس‌های من", callback_data="menu:services")],
        [Btn(text="🎧 پشتیبانی", callback_data="menu:support")],
    ]
    if is_admin:
        rows.append([Btn(text="🛠 پنل مدیریت", callback_data="adm:home")])
    return Kb(inline_keyboard=rows)


def back_kb(to: str = "menu:main") -> Kb:
    return Kb(inline_keyboard=[[Btn(text="🔙 بازگشت", callback_data=to)]])


def wallet_kb() -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text="💳 شارژ کیف پول", callback_data="wallet:charge")],
        [Btn(text="📜 تاریخچه تراکنش‌ها", callback_data="wallet:history")],
        [Btn(text="🔙 بازگشت", callback_data="menu:main")],
    ])


def invoice_kb(invoice_id: int) -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text="🗑 انصراف از فاکتور", callback_data=f"charge:cancel:{invoice_id}")],
        [Btn(text="🔙 کیف پول", callback_data="menu:wallet")],
    ])


def resend_kb(invoice_id: int) -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text="📤 ارسال مجدد رسید", callback_data=f"rcpt:resend:{invoice_id}")],
        [Btn(text="🔙 کیف پول", callback_data="menu:wallet")],
    ])
