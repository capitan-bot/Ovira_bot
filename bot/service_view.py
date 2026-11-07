"""Rendering of the customer's service screen (shared by my_services and service_actions)."""
from backend.services.shop import GB
from bot.keyboards.shop import kb
from bot.utils import fmt_dt
from database.models import Service, ServiceStatus

STATUS = {
    ServiceStatus.ACTIVE: "🟢 فعال", ServiceStatus.EXPIRED: "⌛️ منقضی", ServiceStatus.DISABLED: "⛔️ خاموش",
    ServiceStatus.DEPLETED: "📉 حجم تمام شده", ServiceStatus.DELETED: "🗑 حذف شده",
}


def detail(svc: Service, panel_name: str):
    used, total = svc.used_bytes / GB, svc.total_bytes / GB
    left = max(0.0, total - used)
    text = (
        f"📦 {svc.username}{' (تست)' if svc.is_test else ''}\n\n"
        f"🛰 {panel_name}\n"
        f"وضعیت: {STATUS.get(svc.status, svc.status.value)}\n"
        f"📊 مصرف: {used:.2f} از {total:.2f} گیگابایت\n"
        f"💾 باقی‌مانده: {left:.2f} گیگابایت\n"
        f"⏳ انقضا: {fmt_dt(svc.expires_at)}\n"
        f"🔄 آخرین به‌روزرسانی: {fmt_dt(svc.last_synced_at)}"
    )
    i = svc.id
    rows = [
        [("📥 دریافت کانفیگ", f"svc:c:{i}"), ("📷 QR کد", f"svc:q:{i}")],
    ]
    if not svc.is_test:
        rows.append([("➕ تمدید / خرید حجم اضافه", f"svc:x:{i}")])
    rows.append([("🔁 دریافت لینک جدید", f"svc:n:{i}")])
    if svc.status == ServiceStatus.ACTIVE:
        rows.append([("⏸ خاموش کردن", f"svc:t:{i}"), ("🗑 حذف سرویس", f"svc:d:{i}")])
    elif svc.status == ServiceStatus.DISABLED:
        rows.append([("▶️ روشن کردن", f"svc:t:{i}"), ("🗑 حذف سرویس", f"svc:d:{i}")])
    else:
        rows.append([("🗑 حذف سرویس", f"svc:d:{i}")])
    rows.append([("🔄 به‌روزرسانی", f"svc:r:{i}")])
    rows.append([("🔙 سرویس‌ها", "menu:services")])
    return text, kb(*rows)
