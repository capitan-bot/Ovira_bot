import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.services.errors import NoFreeAmount, NotFound
from backend.services.invoices import create_invoice, submit_receipt
from backend.services.payments import (
    cancel_invoice, cancel_open_charge_invoices, get_charge_limits, get_receipt_bundle,
)
from backend.services.settings_service import get_settings_map
from bot.keyboards.menus import back_kb, invoice_kb
from bot.receipts import send_receipt_to_admins
from bot.states.states import ChargeStates
from bot.utils import edit_or_answer, fmt_card, fmt_money, parse_amount
from database.base import utcnow
from database.models import Invoice, InvoiceKind, InvoiceStatus

log = logging.getLogger(__name__)
router = Router()


def invoice_text(inv: Invoice, card: str, holder: str, ttl: int) -> str:
    return (
        f"🧾 فاکتور شارژ #{inv.id}\n\n"
        f"💰 مبلغ شارژ کیف پول: {fmt_money(inv.base_amount)} تومان\n"
        f"🔢 مبلغ قابل پرداخت: {fmt_money(inv.payable_amount)} تومان\n\n"
        "⚠️ دقیقاً همین مبلغ (با همین ارقام) را واریز کنید. "
        "مبلغ اضافه فقط برای شناسایی پرداخت شماست و به کیف پول اضافه نمی‌شود؛ "
        f"فقط {fmt_money(inv.base_amount)} تومان شارژ می‌شود.\n\n"
        f"💳 شماره کارت:\n{fmt_card(card)}\n"
        f"👤 به نام: {holder or '—'}\n\n"
        f"⏳ اعتبار فاکتور: {ttl} دقیقه\n"
        "📸 بعد از واریز، «تصویر رسید» را همین‌جا ارسال کنید."
    )


@router.callback_query(F.data == "wallet:charge")
async def charge_start(cb: CallbackQuery, session, state: FSMContext):
    cfg = await get_settings_map(session, ["card_number"])
    if not cfg["card_number"]:
        await cb.answer("شارژ کیف پول موقتاً در دسترس نیست. با پشتیبانی تماس بگیرید.", show_alert=True)
        return
    lim = await get_charge_limits(session)
    await state.set_state(ChargeStates.amount)
    await edit_or_answer(
        cb,
        "💳 شارژ کیف پول\n\n"
        f"مبلغ موردنظر را به «تومان» و به صورت عدد ارسال کنید.\n"
        f"حداقل: {fmt_money(lim['charge_min'])} — حداکثر: {fmt_money(lim['charge_max'])} تومان",
        back_kb("menu:wallet"),
    )
    await cb.answer()


@router.message(ChargeStates.amount, F.text, ~F.text.startswith("/"))
async def charge_amount(message: Message, session, state: FSMContext, db_user):
    amount = parse_amount(message.text)
    lim = await get_charge_limits(session)
    if amount is None or not lim["charge_min"] <= amount <= lim["charge_max"]:
        await message.answer(
            f"❌ مبلغ نامعتبر است. یک عدد بین {fmt_money(lim['charge_min'])} و {fmt_money(lim['charge_max'])} تومان بفرستید.")
        return
    await cancel_open_charge_invoices(session, db_user.id)
    try:
        inv = await create_invoice(
            session, user_id=db_user.id, kind=InvoiceKind.WALLET_CHARGE, base_amount=amount,
            extra_min=lim["unique_extra_min"], extra_max=lim["unique_extra_max"],
            ttl_minutes=lim["invoice_ttl_minutes"],
        )
    except NoFreeAmount:
        await message.answer("⏳ هم‌اکنون فاکتورهای زیادی باز است. چند دقیقه بعد دوباره تلاش کنید.")
        return
    cfg = await get_settings_map(session, ["card_number", "card_holder"])
    await state.set_state(ChargeStates.receipt)
    await state.update_data(invoice_id=inv.id)
    await message.answer(invoice_text(inv, cfg["card_number"], cfg["card_holder"], lim["invoice_ttl_minutes"]),
                         reply_markup=invoice_kb(inv.id))


@router.message(ChargeStates.amount)
async def amount_wrong_type(message: Message):
    await message.answer("لطفاً مبلغ را فقط به صورت عدد بفرستید. (انصراف: /cancel)")


@router.message(ChargeStates.receipt, F.photo)
async def receipt_photo(message: Message, session, state: FSMContext, db_user, bot: Bot):
    data = await state.get_data()
    invoice_id = data.get("invoice_id")
    photo = message.photo[-1]
    try:
        async with session.begin_nested():
            receipt = await submit_receipt(
                session, invoice_id=invoice_id, user_id=db_user.id,
                file_id=photo.file_id, file_unique_id=photo.file_unique_id,
            )
    except NotFound:
        await state.clear()
        await message.answer("⌛️ این فاکتور منقضی یا بسته شده است. از «کیف پول من» یک فاکتور جدید بسازید.")
        return
    except IntegrityError:
        await message.answer("❌ این تصویر قبلاً ثبت شده است. لطفاً رسید جدید و معتبر بفرستید.")
        return

    bundle = await get_receipt_bundle(session, receipt.id)
    _, inv, user = bundle
    await state.clear()
    sent = await send_receipt_to_admins(bot, receipt, inv, user)
    if sent == 0:
        log.error("Receipt %s saved but no admin could be notified", receipt.id)
    await message.answer(
        "✅ رسید شما ثبت شد و برای بررسی به مدیر ارسال شد.\n"
        "پس از تأیید، موجودی کیف پول شما افزایش می‌یابد و به شما اطلاع می‌دهیم.",
        reply_markup=back_kb("menu:wallet"),
    )


@router.message(ChargeStates.receipt, ~F.text.startswith("/"))
async def receipt_wrong_type(message: Message):
    await message.answer("📸 لطفاً «تصویر» رسید را ارسال کنید. (انصراف: /cancel)")


@router.callback_query(F.data.startswith("charge:cancel:"))
async def charge_cancel(cb: CallbackQuery, session, state: FSMContext, db_user):
    invoice_id = int(cb.data.rsplit(":", 1)[1])
    ok = await cancel_invoice(session, invoice_id, db_user.id)
    await state.clear()
    await edit_or_answer(cb, "🗑 فاکتور لغو شد." if ok else "این فاکتور دیگر قابل لغو نیست.", back_kb("menu:wallet"))
    await cb.answer()


@router.callback_query(F.data.startswith("rcpt:resend:"))
async def resend(cb: CallbackQuery, session, state: FSMContext, db_user):
    invoice_id = int(cb.data.rsplit(":", 1)[1])
    inv = (await session.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == db_user.id)
    )).scalar_one_or_none()
    if inv is None or inv.status != InvoiceStatus.PENDING:
        await cb.answer("این فاکتور دیگر فعال نیست. یک فاکتور جدید بسازید.", show_alert=True)
        return
    await state.set_state(ChargeStates.receipt)
    await state.update_data(invoice_id=inv.id)
    await cb.message.answer(
        f"📸 تصویر رسید فاکتور #{inv.id} را ارسال کنید.\n"
        f"مبلغ قابل پرداخت: {fmt_money(inv.payable_amount)} تومان")
    await cb.answer()
