import html
import json
import re
import sqlite3
from pathlib import Path
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendMessage, EditMessageText, SendPhoto, EditMessageCaption, EditMessageReplyMarkup
from aiogram.types import InlineKeyboardMarkup

DB_PATH = Path("storage/customization.db")

COLOR_PRESETS = {}

DEFAULT_KNOWN_BUTTONS = [
    {"text": "Multi protocol", "cb": "menu:multi"},
    {"text": "CIP FASTEST", "cb": "menu:fastest"},
    {"text": "دریافت کانفیگ", "cb": "menu:config"},
    {"text": "ارسال گزارش", "cb": "menu:report"},
    {"text": "لغو", "cb": "menu:cancel"},
    {"text": "بازگشت", "cb": "menu:back"},
    {"text": "سرویس‌های من", "cb": "menu:my_services"},
    {"text": "کیف پول", "cb": "menu:wallet"},
    {"text": "پشتیبانی", "cb": "menu:support"}
]

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
            CREATE TABLE IF NOT EXISTS ui_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

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

# توابع نمایشی و خالی برای جلوگیری از خطای ایمپورت در بخش رنگ دکمه‌ها
def set_button_color(btn_key: str, color_code: str) -> None:
    with closing(_color_db()) as conn:
        conn.execute("INSERT INTO button_colors (btn_key, color) VALUES (?, ?) "
                     "ON CONFLICT(btn_key) DO UPDATE SET color = excluded.color", (btn_key, color_code))
        conn.commit()

def delete_button_color(btn_key: str) -> None:
    with closing(_color_db()) as conn:
        conn.execute("DELETE FROM button_colors WHERE btn_key = ?", (btn_key,))
        conn.commit()

def clear_all_button_colors() -> None:
    with closing(_color_db()) as conn:
        conn.execute("DELETE FROM button_colors")
        conn.commit()

def get_button_colors() -> dict[str, str]:
    with closing(_color_db()) as conn:
        return dict(conn.execute("SELECT btn_key, color FROM button_colors").fetchall())

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

def process_outgoing_text(text: str, was_html: bool = False) -> tuple[str, bool]:
    if not text:
        return text, False
    if any(k in text for k in ("مدیریت تغییرات ظاهری", "مدیریت ایموجی‌های پریمیوم")):
        return text, was_html

    for _, old_t, new_t in get_text_replacements():
        if old_t in text:
            text = text.replace(old_t, new_t)

    mapping = get_all_emojis()
    if not mapping or not any(base in text for base in mapping):
        return text, was_html

    if not was_html and "<tg-emoji" not in text:
        text = html.escape(text, quote=False)

    parts = re.split(r'(<tg-emoji[^>]*>.*?</tg-emoji>)', text, flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        for base in sorted(mapping.keys(), key=len, reverse=True):
            seg = seg.replace(base, f'<tg-emoji emoji-id="{mapping[base]}">{base}</tg-emoji>')
        parts[i] = seg
    return "".join(parts), True

def _apply_button_emojis(markup) -> None:
    """Moves a registered premium emoji out of the button text into icon_custom_emoji_id (Bot API 9.4+)."""
    if not isinstance(markup, InlineKeyboardMarkup) or not markup.inline_keyboard:
        return
    mapping = get_all_emojis()
    if not mapping:
        return
    keys = sorted(mapping.keys(), key=len, reverse=True)
    for row in markup.inline_keyboard:
        for btn in row:
            if "icon_custom_emoji_id" not in type(btn).model_fields or getattr(btn, "icon_custom_emoji_id", None):
                continue
            for base in keys:
                for variant in (base, base.replace("\ufe0f", "")):
                    if variant and variant in btn.text:
                        rest = " ".join(btn.text.replace(variant, "", 1).replace("\ufe0f", "").split())
                        if rest:
                            btn.text = rest
                            btn.icon_custom_emoji_id = mapping[base]
                        break
                else:
                    continue
                break

from contextlib import closing

SECTIONS = [
    ("admin", "🛠 پنل مدیریت", ("adm:", "admin:")),
    ("main", "🏠 صفحهٔ اصلی و منوها", ("menu:",)),
    ("services", "📦 اشتراک و سرویس‌ها", ("svc:", "test:")),
    ("wallet", "💳 کیف پول و پرداخت", ("wallet:", "charge:", "rcpt:")),
    ("other", "🧩 سایر", ()),
]
_VALID_STYLES = ("primary", "success", "danger")


def section_of(key: str) -> str:
    for sec, _title, prefixes in SECTIONS:
        if prefixes and key.startswith(prefixes):
            return sec
    return "other"


def button_key(cb: str) -> str:
    """svc:q:12 and svc:q:97 are the same button type: drop the numeric parts."""
    parts = [p for p in str(cb).split(":") if not p.lstrip("-").isdigit()]
    return ":".join(parts) or str(cb)


def _color_db():
    init_custom_db()
    conn = sqlite3.connect(DB_PATH)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(button_colors)")]
    if cols and "btn_key" not in cols:
        conn.execute("DROP TABLE button_colors")
    conn.execute("CREATE TABLE IF NOT EXISTS button_colors (btn_key TEXT PRIMARY KEY, color TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS seen_buttons "
                 "(id INTEGER PRIMARY KEY AUTOINCREMENT, btn_key TEXT UNIQUE NOT NULL, label TEXT NOT NULL)")
    return conn


def record_seen_buttons(items: list) -> None:
    if not items:
        return
    with closing(_color_db()) as conn:
        conn.executemany("INSERT INTO seen_buttons (btn_key, label) VALUES (?, ?) "
                         "ON CONFLICT(btn_key) DO UPDATE SET label = excluded.label", items)
        conn.commit()


def get_seen_buttons() -> list:
    with closing(_color_db()) as conn:
        return conn.execute("SELECT id, btn_key, label FROM seen_buttons ORDER BY id").fetchall()


def get_seen_button(button_id: int):
    with closing(_color_db()) as conn:
        return conn.execute("SELECT id, btn_key, label FROM seen_buttons WHERE id = ?", (button_id,)).fetchone()


def _apply_button_colors(markup) -> None:
    """Sets the Bot API 9.4 button style (primary / success / danger) and remembers every button it sees."""
    if not isinstance(markup, InlineKeyboardMarkup) or not markup.inline_keyboard:
        return
    colors = get_button_colors()
    seen = {}
    for row in markup.inline_keyboard:
        for btn in row:
            cb = getattr(btn, "callback_data", None)
            if not cb:
                continue
            key = button_key(cb)
            if key.startswith("admin:col"):
                continue
            seen[key] = (btn.text or "")[:60]
            color = colors.get(key)
            if color in _VALID_STYLES and not getattr(btn, "style", None) and "style" in type(btn).model_fields:
                btn.style = color
    record_seen_buttons(list(seen.items()))


def process_reply_markup(markup):
    if not markup:
        return markup

    renames = get_button_renames()

    if isinstance(markup, InlineKeyboardMarkup) and markup.inline_keyboard:
        all_cbs = [getattr(b, "callback_data", "") or "" for row in markup.inline_keyboard for b in row]
        is_admin_kb = any(cb.startswith("adm:") for cb in all_cbs)

        existing_raw = get_ui_config("detected_main_buttons")
        existing_list = json.loads(existing_raw) if existing_raw else []
        seen_cbs = {item["cb"] for item in existing_list}
        
        updated = False
        for row in markup.inline_keyboard:
            for b in row:
                if b.callback_data and not b.callback_data.startswith("adm:") and not b.callback_data.startswith("menu:buy") and not b.callback_data.startswith("menu:free_test"):
                    clean_t = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', b.text).strip()
                    if b.callback_data not in seen_cbs:
                        existing_list.append({"text": clean_t or b.text, "cb": b.callback_data})
                        seen_cbs.add(b.callback_data)
                        updated = True

        for kb_item in DEFAULT_KNOWN_BUTTONS:
            if kb_item["cb"] not in seen_cbs:
                existing_list.append(kb_item)
                seen_cbs.add(kb_item["cb"])
                updated = True

        if updated or not existing_raw:
            set_ui_config("detected_main_buttons", json.dumps(existing_list, ensure_ascii=False))

        if not is_admin_kb:
            for row in markup.inline_keyboard:
                for btn in row:
                    clean_text = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', btn.text).strip()
                    if btn.text in renames:
                        btn.text = renames[btn.text]
                    elif clean_text in renames:
                        btn.text = renames[clean_text]

    _apply_button_emojis(markup)
    _apply_button_colors(markup)
    return markup

class CustomizationMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        if isinstance(method, (SendMessage, EditMessageText)):
            if getattr(method, "text", None):
                pm = getattr(method, "parse_mode", None)
                was_html = str(pm).upper() == "HTML" if pm else False
                record_seen_text(method.text, getattr(method, 'reply_markup', None))
                method.text, was_html = apply_welcome(method.text, getattr(method, 'reply_markup', None), was_html)
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
                record_seen_text(method.caption, getattr(method, 'reply_markup', None))
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


def _text_db():
    conn = _color_db()
    conn.execute("CREATE TABLE IF NOT EXISTS seen_lines "
                 "(id INTEGER PRIMARY KEY AUTOINCREMENT, sec TEXT NOT NULL, line TEXT UNIQUE NOT NULL)")
    return conn


def record_seen_text(text, markup=None) -> None:
    """Remembers every static line (no digits) of outgoing messages, grouped by section."""
    try:
        if not text:
            return
        sec = "other"
        if isinstance(markup, InlineKeyboardMarkup):
            found = False
            for row in markup.inline_keyboard:
                for b in row:
                    cb = getattr(b, "callback_data", None)
                    if cb:
                        sec = section_of(button_key(cb))
                        found = True
                        break
                if found:
                    break
        if sec == "admin":
            return
        items = []
        for line in text.split("\n"):
            ln = line.strip()
            if 2 <= len(ln) <= 200 and not re.search(r"\d", ln):
                items.append((sec, ln))
        if not items:
            return
        with closing(_text_db()) as conn:
            conn.executemany("INSERT OR IGNORE INTO seen_lines (sec, line) VALUES (?, ?)", items)
            conn.commit()
    except Exception:
        pass


def get_seen_lines() -> list:
    with closing(_text_db()) as conn:
        return conn.execute("SELECT id, sec, line FROM seen_lines ORDER BY id").fetchall()


def get_seen_line(line_id: int):
    with closing(_text_db()) as conn:
        return conn.execute("SELECT id, sec, line FROM seen_lines WHERE id = ?", (line_id,)).fetchone()


def apply_welcome(text, markup, was_html):
    """Replaces the main-menu welcome message with the admin-defined template ({name} = user's name)."""
    try:
        tpl = get_ui_config("welcome_text")
        if not tpl or not text or not isinstance(markup, InlineKeyboardMarkup):
            return text, was_html
        cbs = {getattr(b, "callback_data", "") for row in markup.inline_keyboard for b in row}
        if "menu:buy" not in cbs or "menu:wallet" not in cbs:
            return text, was_html
        plain = re.sub(r"<[^>]+>", "", text)
        if "خوش آمدید" not in plain:
            return text, was_html
        m = re.search(r"سلام\s+(.+)", plain)
        name = m.group(1).strip() if m else ""
        if not was_html:
            name = html.escape(name)
        return tpl.replace("{name}", name), True
    except Exception:
        return text, was_html
