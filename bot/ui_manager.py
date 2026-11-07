import html
import json
import re
import sqlite3
from pathlib import Path
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendMessage, EditMessageText, SendPhoto, EditMessageCaption, EditMessageReplyMarkup
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

DB_PATH = Path("storage/customization.db")

COLOR_PRESETS = {
    "purple": {"title": "🟣 بنفش نئون", "badge": "🟣", "tg_style": None},
    "green":  {"title": "🟢 سبز نئون", "badge": "🟢", "tg_style": "success"},
    "red":    {"title": "🔴 قرمز ویژه", "badge": "🔴", "tg_style": "danger"},
    "blue":   {"title": "🔵 آبی الماسی", "badge": "🔵", "tg_style": "primary"},
    "gold":   {"title": "🟡 طلایی VIP", "badge": "🟡", "tg_style": None},
    "orange": {"title": "🟠 نارنجی", "badge": "🟠", "tg_style": None},
    "dark":   {"title": "⚫️ مشکی دارک", "badge": "⚫️", "tg_style": None},
    "white":  {"title": "⚪️ سفید نقره‌ای", "badge": "⚪️", "tg_style": None},
}

ALL_BADGES = tuple(v["badge"] for v in COLOR_PRESETS.values())

def strip_color_badge(text: str) -> str:
    t = text.strip()
    for b in ALL_BADGES:
        if t.startswith(b):
            t = t[len(b):].strip()
    return t

def init_custom_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_emojis (
                base_emoji TEXT PRIMARY KEY,
                custom_emoji_id TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS text_replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                old_text TEXT UNIQUE NOT NULL,
                new_text TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS button_renames (
                old_label TEXT PRIMARY KEY,
                new_label TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS button_colors (
                btn_key TEXT PRIMARY KEY,
                color_code TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ui_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

    # انتقال ایموجی‌های قبلی از دیتابیس قدیمی در صورت وجود
    old_db = Path("storage/emojis.db")
    if old_db.exists():
        try:
            with sqlite3.connect(old_db) as oconn:
                rows = oconn.execute("SELECT base_emoji, custom_emoji_id FROM premium_emojis").fetchall()
            if rows:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.executemany(
                        "INSERT OR IGNORE INTO premium_emojis (base_emoji, custom_emoji_id) VALUES (?, ?)",
                        rows
                    )
                    conn.commit()
        except Exception:
            pass

# --- توابع ایموجی پریمیوم ---
def set_premium_emoji(base_emoji: str, custom_emoji_id: str) -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO premium_emojis (base_emoji, custom_emoji_id)
            VALUES (?, ?)
            ON CONFLICT(base_emoji) DO UPDATE SET custom_emoji_id = excluded.custom_emoji_id
        """, (base_emoji.strip(), custom_emoji_id.strip()))
        conn.commit()

def delete_premium_emoji(base_emoji: str) -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM premium_emojis WHERE base_emoji = ?", (base_emoji.strip(),))
        conn.commit()

def get_all_emojis() -> dict[str, str]:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        return dict(conn.execute("SELECT base_emoji, custom_emoji_id FROM premium_emojis").fetchall())

# --- توابع جایگزینی متن‌های ربات ---
def set_text_replacement(old_text: str, new_text: str) -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO text_replacements (old_text, new_text)
            VALUES (?, ?)
            ON CONFLICT(old_text) DO UPDATE SET new_text = excluded.new_text
        """, (old_text.strip(), new_text.strip()))
        conn.commit()

def delete_text_replacement(rule_id: int) -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM text_replacements WHERE id = ?", (rule_id,))
        conn.commit()

def get_text_replacements() -> list[tuple[int, str, str]]:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT id, old_text, new_text FROM text_replacements ORDER BY id DESC").fetchall()

# --- توابع تغییر نام دکمه‌ها ---
def set_button_rename(old_label: str, new_label: str) -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO button_renames (old_label, new_label)
            VALUES (?, ?)
            ON CONFLICT(old_label) DO UPDATE SET new_label = excluded.new_label
        """, (old_label.strip(), new_label.strip()))
        conn.commit()

def delete_button_rename(old_label: str) -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM button_renames WHERE old_label = ?", (old_label.strip(),))
        conn.commit()

def get_button_renames() -> dict[str, str]:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        return dict(conn.execute("SELECT old_label, new_label FROM button_renames").fetchall())

# --- توابع رنگ دکمه‌ها ---
def set_button_color(btn_key: str, color_code: str) -> None:
    init_custom_db()
    clean_key = strip_color_badge(btn_key)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO button_colors (btn_key, color_code)
            VALUES (?, ?)
            ON CONFLICT(btn_key) DO UPDATE SET color_code = excluded.color_code
        """, (clean_key, color_code.strip()))
        conn.commit()

def delete_button_color(btn_key: str) -> None:
    init_custom_db()
    clean_key = strip_color_badge(btn_key)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM button_colors WHERE btn_key = ? OR btn_key = ?", (btn_key.strip(), clean_key))
        conn.commit()

def clear_all_button_colors() -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM button_colors")
        conn.commit()

def get_button_colors() -> dict[str, str]:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        return dict(conn.execute("SELECT btn_key, color_code FROM button_colors").fetchall())

# --- تنظیمات کلی UI ---
def set_ui_config(key: str, value: str) -> None:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO ui_config (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()

def get_ui_config(key: str, default: str = "") -> str:
    init_custom_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT value FROM ui_config WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

# --- پردازشگر متن و ایموجی ---
def process_outgoing_text(text: str, was_html: bool = False) -> tuple[str, bool]:
    if not text:
        return text, False

    if any(k in text for k in ("مدیریت تغییرات ظاهری", "مدیریت ایموجی‌های پریمیوم", "مدیریت رنگ دکمه‌های ربات", "تغییر جایگاه و چیدمان")):
        return text, was_html

    replacements = get_text_replacements()
    for _, old_t, new_t in replacements:
        if old_t in text:
            text = text.replace(old_t, new_t)

    mapping = get_all_emojis()
    if not mapping:
        return text, was_html

    has_match = any(base in text for base in mapping)
    if not has_match:
        return text, was_html

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

def _apply_color_to_btn(btn, color_code: str) -> None:
    preset = COLOR_PRESETS.get(color_code)
    if not preset:
        return
    badge = preset["badge"]
    clean_text = strip_color_badge(btn.text)
    btn.text = f"{badge} {clean_text}"
    try:
        if preset.get("tg_style"):
            object.__setattr__(btn, "style", preset["tg_style"])
    except Exception:
        pass

# --- پردازشگر کیبورد، چیدمان، نام و رنگ دکمه‌ها ---
def process_reply_markup(markup):
    if not markup:
        return markup

    renames = get_button_renames()
    colors = get_button_colors()

    if isinstance(markup, InlineKeyboardMarkup) and markup.inline_keyboard:
        all_cbs = [getattr(b, "callback_data", "") or "" for row in markup.inline_keyboard for b in row]
        is_admin_kb = any(cb.startswith("adm:") for cb in all_cbs)

        if not is_admin_kb and len(all_cbs) >= 3:
            flat_btns = [{"text": strip_color_badge(b.text), "cb": b.callback_data} for row in markup.inline_keyboard for b in row if b.callback_data]
            if any("menu:" in x["cb"] or "buy" in x["cb"] or "service" in x["cb"] or "test" in x["cb"] or "charge" in x["cb"] for x in flat_btns):
                if not get_ui_config("detected_main_buttons"):
                    set_ui_config("detected_main_buttons", json.dumps(flat_btns, ensure_ascii=False))

                custom_layout_raw = get_ui_config("custom_main_layout")
                if custom_layout_raw:
                    try:
                        layout_grid = json.loads(custom_layout_raw)
                        btn_map = {b.callback_data: b for row in markup.inline_keyboard for b in row if b.callback_data}
                        layout_cbs = [cb for r in layout_grid for cb in r]
                        if set(layout_cbs).issubset(set(btn_map.keys())) and len(btn_map) == len(layout_cbs):
                            new_rows = []
                            for r in layout_grid:
                                row_objs = [btn_map[cb] for cb in r if cb in btn_map]
                                if row_objs:
                                    new_rows.append(row_objs)
                            markup.inline_keyboard = new_rows
                    except Exception:
                        pass

        if not is_admin_kb:
            for row in markup.inline_keyboard:
                for btn in row:
                    orig_clean = strip_color_badge(btn.text)
                    cb_data = getattr(btn, "callback_data", "") or ""
                    if btn.text in renames:
                        btn.text = renames[btn.text]
                    elif orig_clean in renames:
                        btn.text = renames[orig_clean]
                    matched_color = colors.get(cb_data) or colors.get(orig_clean) or colors.get(strip_color_badge(btn.text))
                    if matched_color:
                        _apply_color_to_btn(btn, matched_color)

    elif isinstance(markup, ReplyKeyboardMarkup) and markup.keyboard:
        for row in markup.keyboard:
            for btn in row:
                orig_clean = strip_color_badge(btn.text)
                if btn.text in renames:
                    btn.text = renames[btn.text]
                elif orig_clean in renames:
                    btn.text = renames[orig_clean]
                matched_color = colors.get(orig_clean) or colors.get(strip_color_badge(btn.text))
                if matched_color:
                    _apply_color_to_btn(btn, matched_color)

    return markup


class CustomizationMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        if isinstance(method, (SendMessage, EditMessageText)):
            if getattr(method, "text", None):
                pm = getattr(method, "parse_mode", None)
                was_html = str(pm).upper() == "HTML" if pm else False
                new_text, use_html = process_outgoing_text(method.text, was_html=was_html)
                method.text = new_text
                if use_html:
                    method.parse_mode = "HTML"
            if getattr(method, "reply_markup", None):
                method.reply_markup = process_reply_markup(method.reply_markup)

        elif isinstance(method, (SendPhoto, EditMessageCaption)):
            if getattr(method, "caption", None):
                pm = getattr(method, "parse_mode", None)
                was_html = str(pm).upper() == "HTML" if pm else False
                new_cap, use_html = process_outgoing_text(method.caption, was_html=was_html)
                method.caption = new_cap
                if use_html:
                    method.parse_mode = "HTML"
            if getattr(method, "reply_markup", None):
                method.reply_markup = process_reply_markup(method.reply_markup)

        elif isinstance(method, EditMessageReplyMarkup):
            if getattr(method, "reply_markup", None):
                method.reply_markup = process_reply_markup(method.reply_markup)

        return await make_request(bot, method)
