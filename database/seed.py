"""Idempotent seed: default settings. Run after migrations. Existing values are never overwritten."""
import asyncio

from sqlalchemy import select

from config.settings import get_settings
from database.connection import session_scope
from database.models import Setting

DEFAULT_TEXTS = {
    "start_message": "سلام {name} 👋\nبه فروشگاه {shop} خوش آمدید.\nاز منوی زیر ادامه دهید:",
    "invoice_text": "🧾 فاکتور شما\n\nپنل: {panel}\nسرویس: {profile}\nحجم: {gb} گیگابایت\nمدت: {days} روز\nنام کاربری: {username}\n\nمبلغ: {amount} تومان",
    "payment_success_text": "✅ پرداخت شما تأیید شد.",
    "payment_failed_text": "❌ پرداخت شما تأیید نشد.\nدلیل: {reason}",
    "delivery_text": "🎉 سرویس شما با موفقیت ساخته شد!",
}

DEFAULT_LIMITS = {
    "bot_enabled": "1",
    "test_enabled": "0",
    "test_panel_id": "",
    "test_profile_id": "",
    "test_gb": "1",
    "test_hours": "24",
    "test_max_per_user": "1",
    "invoice_ttl_minutes": "60",
    "charge_min": "10000",
    "charge_max": "5000000",
    "unique_extra_min": "1",
    "unique_extra_max": "99",
    "notify_days_before_expiry": "3",
    "notify_channel": "",
}


async def main() -> None:
    s = get_settings()
    defaults = {
        "shop_name": s.seed_shop_name,
        "card_number": s.seed_card_number,
        "card_holder": s.seed_card_holder,
        "support_id": s.seed_support_id,
        **DEFAULT_TEXTS,
        **DEFAULT_LIMITS,
    }
    async with session_scope() as session:
        existing = set((await session.execute(select(Setting.key))).scalars())
        for k, v in defaults.items():
            if k not in existing:
                session.add(Setting(key=k, value=v))
    print("seed done")


if __name__ == "__main__":
    asyncio.run(main())
