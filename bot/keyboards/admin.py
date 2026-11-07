from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb


def kb(*rows) -> Kb:
    """rows: lists of (text, callback_data)"""
    return Kb(inline_keyboard=[[Btn(text=t, callback_data=d) for t, d in row] for row in rows])


def home_kb(bot_on: bool) -> Kb:
    return kb(
        [("📊 آمار ربات", "adm:stats"), ("👥 مدیریت کاربران", "adm:users")],
        [("🛰 مدیریت پنل‌ها", "adm:pn"), ("🧾 رسیدهای در انتظار", "adm:rc")],
        [("📢 پیام همگانی", "adm:bc"), ("🎁 تست رایگان", "adm:ts")],
        [("🎨 تغییرات ظاهری", "adm:ui"), ("⚙️ تنظیمات ربات", "adm:st")],
        [("⏸ خاموش کردن ربات" if bot_on else "▶️ روشن کردن ربات", "adm:bot")],
        [("🏠 منوی کاربری", "menu:main")],
    )
