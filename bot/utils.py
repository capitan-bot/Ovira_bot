import logging
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

log = logging.getLogger(__name__)


class _Safe(defaultdict):
    def __missing__(self, key):
        return "{" + key + "}"


def safe_format(template: str, **values) -> str:
    """Admin-editable texts may contain typos; never crash on them."""
    try:
        return template.format_map(_Safe(str, **values))
    except (ValueError, IndexError, KeyError):
        return template


def fmt_money(n: int) -> str:
    return f"{n:,}"


async def edit_or_answer(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        # message can't be edited (e.g. it's a photo) -> send a new one
        await cb.message.answer(text, reply_markup=kb)


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def parse_amount(text: str) -> int | None:
    t = (text or "").translate(_DIGITS)
    for ch in (",", "،", " ", "٬", "."):
        t = t.replace(ch, "")
    return int(t) if t.isdigit() and len(t) <= 12 else None


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M")


def fmt_card(number: str) -> str:
    n = "".join(c for c in number if c.isdigit())
    return " ".join(n[i:i + 4] for i in range(0, len(n), 4)) if n else number
