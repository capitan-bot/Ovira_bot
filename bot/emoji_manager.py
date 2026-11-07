import html
import re
import sqlite3
from pathlib import Path
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendMessage, EditMessageText, SendPhoto, EditMessageCaption

DB_PATH = Path("storage/emojis.db")

def init_emoji_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_emojis (
                base_emoji TEXT PRIMARY KEY,
                custom_emoji_id TEXT NOT NULL
            )
        """)
        conn.commit()

def set_premium_emoji(base_emoji: str, custom_emoji_id: str) -> None:
    init_emoji_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO premium_emojis (base_emoji, custom_emoji_id)
            VALUES (?, ?)
            ON CONFLICT(base_emoji) DO UPDATE SET custom_emoji_id = excluded.custom_emoji_id
        """, (base_emoji.strip(), custom_emoji_id.strip()))
        conn.commit()

def delete_premium_emoji(base_emoji: str) -> None:
    init_emoji_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM premium_emojis WHERE base_emoji = ?", (base_emoji.strip(),))
        conn.commit()

def get_all_emojis() -> dict[str, str]:
    init_emoji_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT base_emoji, custom_emoji_id FROM premium_emojis")
        return dict(cursor.fetchall())

def apply_premium_emojis(text: str, was_html: bool = False) -> tuple[str, bool]:
    if not text:
        return text, False
    mapping = get_all_emojis()
    if not mapping:
        return text, False
    has_match = any(base in text for base in mapping)
    if not has_match:
        return text, False

    if not was_html and "<tg-emoji" not in text:
        text = html.escape(text, quote=False)

    parts = re.split(r'(<tg-emoji[^>]*>.*?</tg-emoji>)', text, flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        segment = parts[i]
        for base in sorted(mapping.keys(), key=len, reverse=True):
            cid = mapping[base]
            segment = segment.replace(base, f'<tg-emoji emoji-id="{cid}">{base}</tg-emoji>')
        parts[i] = segment
    return "".join(parts), True


class AutoPremiumEmojiMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        if isinstance(method, (SendMessage, EditMessageText)) and getattr(method, "text", None):
            pm = getattr(method, "parse_mode", None)
            was_html = str(pm).upper() == "HTML" if pm else False
            new_text, changed = apply_premium_emojis(method.text, was_html=was_html)
            if changed:
                method.text = new_text
                method.parse_mode = "HTML"
        elif isinstance(method, (SendPhoto, EditMessageCaption)) and getattr(method, "caption", None):
            pm = getattr(method, "parse_mode", None)
            was_html = str(pm).upper() == "HTML" if pm else False
            new_cap, changed = apply_premium_emojis(method.caption, was_html=was_html)
            if changed:
                method.caption = new_cap
                method.parse_mode = "HTML"
        return await make_request(bot, method)
