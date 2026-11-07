import html
import base64
"""Small helpers shared by the shop handlers: per-user lock, admin alerts, sending config files."""
import asyncio
import io
import logging
from collections import defaultdict
from urllib.parse import quote

import httpx
from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from adapters.base import ConfigFile
from config.settings import get_settings

log = logging.getLogger(__name__)
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

import re as _re
_CFG_LINE = _re.compile(r"^(vmess|vless|trojan|ss|ssr|hysteria2|hysteria|hy2|tuic)://\S+$", _re.I)


def _cfg_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if _CFG_LINE.match(ln.strip())]


def user_lock(user_id: int) -> asyncio.Lock:
    return _locks[user_id]


async def notify_admins(bot: Bot, text: str) -> None:
    for admin_id in get_settings().admin_telegram_ids:
        try:
            await bot.send_message(admin_id, text[:4000])
        except Exception as e:
            log.warning("Could not alert admin %s: %s", admin_id, e)


def _detect_protocol(text: str, filename: str) -> str:
    t = text.strip().lower()
    fn = filename.lower()
    if t.startswith("vless://"):
        return "VLESS"
    if t.startswith("vmess://"):
        return "VMess"
    if t.startswith("trojan://"):
        return "Trojan"
    if t.startswith("ss://"):
        return "Shadowsocks"
    if t.startswith("wg://") or "[interface]" in t or fn.endswith(".conf"):
        return "WireGuard"
    if ("client" in t and "dev tun" in t) or fn.endswith(".ovpn"):
        return "OpenVPN"
    if "amnezia" in fn or t.startswith("vpn://"):
        return "Amnezia"
    if "cisco" in fn or "anyconnect" in t:
        return "Cisco"
    if t.startswith(("http://", "https://")):
        return "Subscription"
    return "اختصاصی"


def _copy_kb(text_to_copy: str, label: str = "📋 کپی کانفیگ") -> InlineKeyboardMarkup | None:
    try:
        from aiogram.types import CopyTextButton
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=text_to_copy))]
        ])
    except Exception:
        return None


def _rating_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 ⭐️", callback_data="rate_star:1"),
            InlineKeyboardButton(text="2 ⭐️", callback_data="rate_star:2"),
            InlineKeyboardButton(text="3 ⭐️", callback_data="rate_star:3"),
            InlineKeyboardButton(text="4 ⭐️", callback_data="rate_star:4"),
            InlineKeyboardButton(text="5 ⭐️", callback_data="rate_star:5"),
        ]
    ])


async def _make_qr(data: str) -> bytes | None:
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        try:
            url = f"https://api.qrserver.com/v1/create-qr-code/?size=350x350&data={quote(data)}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.content
        except Exception as e:
            log.warning("QR generation failed: %s", e)
    return None


async def _links_from_sub(url: str) -> list[str]:
    """Reads the panel's own subscription page and returns the config links inside it."""
    try:
        async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "v2rayN/6.42"})
        if r.status_code != 200:
            return []
        body = r.text.strip()
    except Exception as e:  # noqa: BLE001
        log.warning("reading subscription page failed: %s", type(e).__name__)
        return []
    if body.lstrip().startswith("<"):
        return []
    if "://" not in body:
        try:
            raw = "".join(body.split()).replace("-", "+").replace("_", "/")
            body = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            return []
    return _cfg_lines(body)


async def send_files(bot: Bot, chat_id: int, files: list[ConfigFile], sub_link: str | None) -> bool:
    """Sends every config link (vmess/vless/...) as its own copyable message, then the subscription link."""
    sent = False
    links: list[str] = []
    others: list[ConfigFile] = []
    for f in files:
        try:
            text = f.content.decode("utf-8")
        except Exception:  # noqa: BLE001
            text = ""
        found = _cfg_lines(text)
        if found:
            links += found
        else:
            others.append(f)
    if not links and sub_link:
        links = await _links_from_sub(sub_link)
    seen = set()
    for ln in links:
        if ln in seen:
            continue
        seen.add(ln)
        try:
            await bot.send_message(chat_id, f"<code>{html.escape(ln)}</code>", parse_mode="HTML")
            sent = True
        except Exception as e:  # noqa: BLE001
            log.warning("sending config link failed: %s", e)
    for f in others:
        try:
            await bot.send_document(chat_id, BufferedInputFile(f.content, filename=f.filename))
            sent = True
        except Exception as e:  # noqa: BLE001
            log.warning("sending %s failed: %s", f.filename, e)
    if sub_link:
        caption = (
            "\U0001f50c نوع پروتکل: لینک هوشمند اشتراک (Subscription)\n\n"
            "\U0001f310 لینک ساب شما:\n"
            f"<code>{html.escape(sub_link)}</code>"
        )
        kb = _copy_kb(sub_link, "\U0001f4cb کپی لینک اشتراک")
        png = await _make_qr(sub_link)
        try:
            if png:
                await bot.send_photo(chat_id, BufferedInputFile(png, filename="sub.png"),
                                     caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
            sent = True
        except Exception as e:  # noqa: BLE001
            log.warning("sending subscription message failed: %s", e)
            await bot.send_message(chat_id, f"\U0001f517 لینک اشتراک:\n{sub_link}")
            sent = True
    return sent
