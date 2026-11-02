import asyncio
import json
import os
import re
import signal
import tempfile
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone

from vplus import VPlusClient, Filters, Update, escape_markdown
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

SOROUSH_BOT_TOKEN = "69702802:ifPFaJghWWgRqNbk0e9p2rSbW0RjBkhlmyQ"

TELEGRAM_API_ID = 2040
TELEGRAM_API_HASH = "b18441a1ff607e10a989891a5462e627"
TELEGRAM_SESSION_NAME = "news_bridge_session"
PHONE_NUMBER = "+989386341312"
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", "")

PORT = int(os.environ.get("PORT", "10000"))
PING_URL = os.environ.get("RENDER_EXTERNAL_URL", "") or os.environ.get("PING_URL", "")
PING_INTERVAL = 240
STATE_TAG = "NEWSBOT_STATE_V1"
STATE_BACKUP_INTERVAL = 30
WATCHDOG_INTERVAL = 30
TG_RETRIES = 10 ** 6

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "news_users.json")
MEDIA_DIR = os.path.join(tempfile.gettempdir(), "news_bridge_media")
os.makedirs(MEDIA_DIR, exist_ok=True)

POST_COUNT = 12
FORCED_SWITCH_COUNT = POST_COUNT
BROADCAST_DELAY = 0.15
FOOTER_MAX_LEN = 500
ADMIN_ID = 66009832
CHECK_INTERVAL = 300
RECENT_SCAN_LIMIT = 150
NEW_SCAN_LIMIT = 100
SEND_DELAY = 0.5
MESSAGE_LIMIT = 3500
CAPTION_LIMIT = 1024
MAX_VIDEO_BYTES = 20 * 1024 * 1024
SHOW_NO_NEWS_NOTICE = True
SHORT_LINE_LETTERS = 20

CHANNELS = {
    "azad":  {"label": "🕊 ایران آزاد ⭐ بهتر و صحیح‌تر", "username": "IraneAzad_News", "title": "ایران آزاد",       "icon": "🕊", "enabled": True},
    "inter": {"label": "📺 ایران اینترنشنال",              "username": "IranintlTV",     "title": "ایران اینترنشنال", "icon": "📺", "enabled": True},
}

BTN_SWITCH = "🔁 تغییر کانال"
BTN_HELP = "❕ راهنما"
BTN_ADMIN = "🛠 مدیریت"
ADM_ADD = "➕ افزودن کانال"
ADM_LIST = "📋 لیست کانال‌ها"
ADM_DISABLE = "⏸ غیرفعال کردن کانال"
ADM_ENABLE = "▶️ فعال کردن کانال"
ADM_FOOTER = "✏️ تنظیم فوتر"
ADM_FOOTER_DEL = "🗑 حذف فوتر"
ADM_BROADCAST = "📢 پیام همگانی"
ADM_BACK = "🔙 خروج از مدیریت"
ADM_CANCEL = "❌ لغو"
ADM_SEND = "✅ ارسال"
ADMIN_TEXTS = {
    BTN_ADMIN, ADM_ADD, ADM_LIST, ADM_DISABLE, ADM_ENABLE, ADM_FOOTER,
    ADM_FOOTER_DEL, ADM_BROADCAST, ADM_BACK, ADM_CANCEL, ADM_SEND,
}

DIVIDER = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
DIVIDER_SOFT = "· · · · · · · · · · · ·"
STAR_LINE = "✦ ── ✦ ── ✦ ── ✦ ── ✦"
POST_DIVIDER = "━━━━━━━━━━━━"
IRAN_TZ = timezone(timedelta(hours=3, minutes=30))

bot = VPlusClient(token=SOROUSH_BOT_TOKEN)
tg_client = TelegramClient(
    StringSession(TELEGRAM_SESSION_STRING) if TELEGRAM_SESSION_STRING else TELEGRAM_SESSION_NAME,
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    connection_retries=TG_RETRIES,
    retry_delay=3,
    auto_reconnect=True,
)


def fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def make_header(info: dict, date) -> str:
    head = f"{info['icon']} {info['title']}"
    try:
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        local = date.astimezone(IRAN_TZ)
        clock = fa(local.strftime("%H:%M"))
        if local.date() == datetime.now(IRAN_TZ).date():
            when = f"🕐 {clock}"
        else:
            jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
            jdate = fa(f"{jy}/{jm:02d}/{jd:02d}")
            when = f"📅 {jdate} ┊ 🕐 {clock}"
        return f"{head} ┊ {when}"
    except Exception:
        return head


def compose_post(header: str, body: str, footer: str = "") -> str:
    body = (body or "").strip()
    text = header if not body else f"{header}\n{POST_DIVIDER}\n{body}"
    footer = (footer or "").strip()
    if footer:
        text += f"\n\n{footer}"
    return text


# ───────────────────────── ذخیره‌ی وضعیت (کاربرها، کانال‌ها، فوتر) ─────────────────────────

users: dict = {}
chats: dict = {}
settings: dict = {"footer": ""}
user_gen: dict = {}
user_locks: dict = {}
admin_state: dict = {}
_tasks: set = set()

_state_dirty = False
_state_msg_id = None


def parse_state(raw) -> dict:
    out = {"users": {}, "chats": {}, "channels": {}, "settings": {}}
    if not isinstance(raw, dict):
        return out
    new_format = any(k in raw for k in ("users", "chats", "channels", "settings"))
    raw_users = raw.get("users", {}) if new_format else raw

    for key, val in (raw.get("channels") or {}).items() if new_format else []:
        try:
            out["channels"][str(key)] = {
                "label": str(val["label"]),
                "username": str(val["username"]),
                "title": str(val["title"]),
                "icon": str(val.get("icon", "📡")),
                "enabled": bool(val.get("enabled", True)),
            }
        except Exception:
            continue

    for key, val in (raw_users or {}).items():
        try:
            out["users"][int(key)] = {
                "chat_id": int(val["chat_id"]),
                "channel": str(val["channel"]),
                "last_id": int(val.get("last_id", 0)),
            }
        except Exception:
            continue

    if new_format:
        for key, val in (raw.get("chats") or {}).items():
            try:
                out["chats"][int(key)] = int(val)
            except Exception:
                continue
        if isinstance(raw.get("settings"), dict):
            out["settings"] = raw["settings"]
    return out


def apply_state(parsed: dict):
    for key, val in parsed["channels"].items():
        if key in CHANNELS:
            CHANNELS[key]["enabled"] = val["enabled"]
        else:
            CHANNELS[key] = val
    for uid, st in parsed["users"].items():
        if st["channel"] in CHANNELS:
            users[uid] = st
    for uid, cid in parsed["chats"].items():
        chats[uid] = cid
    for uid, st in users.items():
        chats.setdefault(uid, st["chat_id"])
    footer = parsed["settings"].get("footer", "")
    settings["footer"] = footer if isinstance(footer, str) else ""


def _read_state_file() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ خوندن فایل وضعیت نشد: {type(e).__name__}: {e}")
        return {}


def _write_state_file():
    payload = {
        "users": {str(k): v for k, v in users.items()},
        "chats": {str(k): v for k, v in chats.items()},
        "channels": CHANNELS,
        "settings": settings,
    }
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp_path, STATE_FILE)


def save_state():
    global _state_dirty
    try:
        _write_state_file()
        _state_dirty = True
    except Exception as e:
        print(f"⚠️ ذخیره‌ی فایل وضعیت نشد: {type(e).__name__}: {e}")


apply_state(parse_state(_read_state_file()))


def register_chat(user_id: int, chat_id: int):
    if chats.get(user_id) != chat_id:
        chats[user_id] = chat_id
        save_state()


def get_footer() -> str:
    return (settings.get("footer") or "").strip()


def enabled_keys() -> list:
    return [k for k, c in CHANNELS.items() if c.get("enabled", True)]


def fallback_key(exclude=None):
    keys = [k for k in enabled_keys() if k != exclude]
    if "azad" in keys:
        return "azad"
    return keys[0] if keys else None


def label_to_key(text: str, enabled: bool = True):
    for key, c in CHANNELS.items():
        if c["label"] == text and bool(c.get("enabled", True)) == enabled:
            return key
    return None


def find_key_by_username(username: str):
    for key, c in CHANNELS.items():
        if c["username"].lower() == username.lower():
            return key
    return None


async def backup_state() -> bool:
    """نسخه‌ی پشتیبان وضعیت کاربرها رو تو Saved Messages اکانت تلگرام نگه می‌داره."""
    global _state_dirty, _state_msg_id
    if not os.path.exists(STATE_FILE) or not tg_client.is_connected():
        return False
    _state_dirty = False
    try:
        old_id = _state_msg_id
        msg = await tg_client.send_file("me", STATE_FILE, caption=STATE_TAG, force_document=True)
        _state_msg_id = msg.id
        if old_id:
            try:
                await tg_client.delete_messages("me", [old_id])
            except Exception:
                pass
        return True
    except Exception as e:
        _state_dirty = True
        print(f"⚠️ پشتیبان‌گیری وضعیت fail شد: {type(e).__name__}: {e}")
        return False


async def restore_state():
    global _state_msg_id
    try:
        async for m in tg_client.iter_messages("me", limit=60):
            if m.document and (m.message or "").startswith(STATE_TAG):
                _state_msg_id = m.id
                if not users and not chats:
                    data = await tg_client.download_media(m, file=bytes)
                    apply_state(parse_state(json.loads(data.decode("utf-8"))))
                    _write_state_file()
                    print(f"♻️ وضعیت {len(chats)} کاربر و {len(CHANNELS)} کانال از Saved Messages برگشت.")
                break
    except Exception as e:
        print(f"⚠️ بازیابی وضعیت fail شد: {type(e).__name__}: {e}")


async def backup_loop():
    while True:
        await asyncio.sleep(STATE_BACKUP_INTERVAL)
        if _state_dirty:
            await backup_state()


def get_lock(user_id: int) -> asyncio.Lock:
    lock = user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        user_locks[user_id] = lock
    return lock


def bump_gen(user_id: int) -> int:
    user_gen[user_id] = user_gen.get(user_id, 0) + 1
    return user_gen[user_id]


def spawn(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


# ───────────────────────── ارسال پیام به سروش پلاس ─────────────────────────

async def safe_send(chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", **kwargs)
    except Exception as e1:
        print(f"⚠️ send_message (Markdown) failed: {type(e1).__name__}: {e1}")
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e2:
            print(f"❌ send_message (plain) failed too: {type(e2).__name__}: {e2}")
            return None


async def plain_send(chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except Exception as e:
        print(f"❌ plain_send failed: {type(e).__name__}: {e}")
        return None


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list:
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


async def send_long_plain(chat_id: int, text: str):
    for chunk in split_text(text):
        await plain_send(chat_id, chunk)


async def plain_send_photo(chat_id: int, path: str, caption: str = ""):
    try:
        with open(path, "rb") as photo_file:
            return await bot.send_photo(chat_id=chat_id, photo=photo_file, caption=caption)
    except Exception as e:
        print(f"❌ send_photo failed: {type(e).__name__}: {e}")
        return None


async def plain_send_video(chat_id: int, path: str, caption: str = ""):
    sender = getattr(bot, "send_video", None)
    if sender is None:
        return None
    try:
        with open(path, "rb") as video_file:
            return await sender(chat_id=chat_id, video=video_file, caption=caption)
    except Exception as e:
        print(f"❌ send_video failed: {type(e).__name__}: {e}")
        return None


# ───────────────────────── پاک‌کردن لینک از متن پست‌ها ─────────────────────────

LINK_MARK = "\ue000"
TXTURL_OPEN = "\ue001"
TXTURL_CLOSE = "\ue002"

_URL_RE = re.compile(
    r"[\(\[]?(?:https?://|ftp://|tg://|www\.|t\.me/|telegram\.me/|telegram\.dog/)\S*",
    re.I,
)
_DOMAIN_RE = re.compile(
    r"(?<![\w@./-])(?:[a-z0-9\-]+\.)+(?:com|org|net|ir|io|me|co|info|tv|news|app|link|ly|gl|be|gg|xyz|site|online)\b(?:/\S*)?",
    re.I,
)
_MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{4,}")
_TXTURL_BLOCK_RE = re.compile(TXTURL_OPEN + r".*?" + TXTURL_CLOSE, re.S)
_LETTER_RE = re.compile(r"[^\W_]")


def _letters(s: str) -> int:
    return len(_LETTER_RE.findall(s))


def _mark_entities(raw: str, entities) -> str:
    if not entities:
        return raw
    data = raw.encode("utf-16-le", errors="surrogatepass")
    edits = []
    for ent in entities:
        name = type(ent).__name__
        start = ent.offset * 2
        end = start + ent.length * 2
        if name in ("MessageEntityUrl", "MessageEntityMention"):
            edits.append((start, end, True))
        elif name == "MessageEntityTextUrl":
            edits.append((start, end, False))
    for start, end, remove in sorted(edits, key=lambda x: x[0], reverse=True):
        if remove:
            data = data[:start] + LINK_MARK.encode("utf-16-le") + data[end:]
        else:
            data = (
                data[:start]
                + TXTURL_OPEN.encode("utf-16-le")
                + data[start:end]
                + TXTURL_CLOSE.encode("utf-16-le")
                + data[end:]
            )
    return data.decode("utf-16-le", errors="ignore")


def clean_post_text(raw: str, entities=None) -> str:
    text = _mark_entities(raw or "", entities)
    text = _URL_RE.sub(LINK_MARK, text)
    text = _DOMAIN_RE.sub(LINK_MARK, text)
    text = _MENTION_RE.sub(LINK_MARK, text)

    out_lines = []
    for line in text.split("\n"):
        had_link = LINK_MARK in line
        had_txturl = TXTURL_OPEN in line
        clean = line.replace(LINK_MARK, "").replace(TXTURL_OPEN, "").replace(TXTURL_CLOSE, "")
        if had_link and _letters(clean) < SHORT_LINE_LETTERS:
            continue
        if had_txturl:
            outside = _TXTURL_BLOCK_RE.sub("", line).replace(LINK_MARK, "")
            if _letters(outside) < 8:
                continue
        clean = re.sub(r"[\(\[]\s*[\)\]]", "", clean)
        clean = re.sub(r"[ \t]{2,}", " ", clean)
        out_lines.append(clean.rstrip())

    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ───────────────────────── گرفتن پست‌ها از تلگرام ─────────────────────────

class Post:
    def __init__(self, msg, text: str, kind, header: str = ""):
        self.msg = msg
        self.id = msg.id
        self.text = text
        self.kind = kind
        self.header = header
        self.path = None
        self.failed = False
        self._lock = asyncio.Lock()

    async def media_path(self):
        async with self._lock:
            if self.path or self.failed:
                return self.path
            try:
                if self.kind == "video":
                    size = getattr(getattr(self.msg, "file", None), "size", 0) or 0
                    if size > MAX_VIDEO_BYTES:
                        self.failed = True
                        return None
                self.path = await tg_client.download_media(self.msg, file=MEDIA_DIR)
            except Exception as e:
                print(f"❌ دانلود مدیا fail شد: {type(e).__name__}: {e}")
                self.path = None
            if not self.path:
                self.failed = True
            return self.path

    def cleanup(self):
        if self.path:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.path = None


def _media_kind(msg):
    if getattr(msg, "photo", None):
        return "photo"
    doc = getattr(msg, "document", None)
    if doc:
        mime = getattr(doc, "mime_type", "") or ""
        if mime.startswith("image/"):
            return "photo"
        if getattr(msg, "video", None) or mime.startswith("video/"):
            return "video"
    return None


def build_posts(messages, ckey: str) -> list:
    info = CHANNELS[ckey]
    posts = []
    for msg in reversed(messages):
        if getattr(msg, "action", None):
            continue
        kind = _media_kind(msg)
        text = clean_post_text(msg.raw_text or "", msg.entities)
        if not text and not kind:
            continue
        posts.append(Post(msg, text, kind, make_header(info, msg.date)))
    return posts


async def _scan(channel: str, limit: int, **kwargs) -> list:
    for _ in range(2):
        try:
            return [m async for m in tg_client.iter_messages(channel, limit=limit, **kwargs)]
        except FloodWaitError as e:
            print(f"⏳ FloodWait {e.seconds}s روی {channel}")
            await asyncio.sleep(e.seconds + 1)
    raise RuntimeError("FloodWait تموم نشد")


async def fetch_recent(ckey: str, count: int = POST_COUNT):
    messages = await _scan(CHANNELS[ckey]["username"], RECENT_SCAN_LIMIT)
    newest_id = max((m.id for m in messages), default=0)
    posts = build_posts(messages, ckey)[-count:]
    return posts, newest_id


async def fetch_since(ckey: str, after_id: int):
    messages = await _scan(CHANNELS[ckey]["username"], NEW_SCAN_LIMIT, min_id=after_id)
    newest_id = max((m.id for m in messages), default=after_id)
    posts = build_posts(messages, ckey)
    return posts, newest_id


# ───────────────────────── ارسال پست‌ها به کاربر ─────────────────────────

async def send_post(chat_id: int, post: Post):
    body = post.text
    footer = get_footer()
    full = compose_post(post.header, body, footer)

    if post.kind in ("photo", "video"):
        path = await post.media_path()
        if path:
            if len(full) <= CAPTION_LIMIT:
                caption, rest = full, ""
            else:
                caption = post.header
                rest = (body + (f"\n\n{footer}" if footer else "")).strip()
            if post.kind == "photo":
                sent = await plain_send_photo(chat_id, path, caption)
            else:
                sent = await plain_send_video(chat_id, path, caption)
            if sent is not None:
                if rest:
                    await send_long_plain(chat_id, rest)
                return
        if post.kind == "video":
            body = ("🎬 این پست ویدیو داشت\n\n" + body).strip()
            full = compose_post(post.header, body, footer)

    await send_long_plain(chat_id, full)


async def deliver_posts(chat_id: int, posts: list, user_id: int, gen: int) -> bool:
    for post in posts:
        if user_gen.get(user_id) != gen:
            return False
        try:
            await send_post(chat_id, post)
        except Exception as e:
            print(f"❌ send_post exception: {type(e).__name__}: {e}")
            traceback.print_exc()
        await asyncio.sleep(SEND_DELAY)
    return True


def cleanup_posts(posts: list):
    for post in posts:
        post.cleanup()


# ───────────────────────── کیبوردها و متن‌ها ─────────────────────────

def _admin_row(user_id):
    return [[{"text": BTN_ADMIN}]] if user_id == ADMIN_ID else []


def kb_channel_menu(user_id=None):
    rows = [[{"text": CHANNELS[k]["label"]}] for k in enabled_keys()]
    return {"keyboard": rows + _admin_row(user_id), "resize_keyboard": True}


def kb_chat_menu(user_id=None):
    rows = [[{"text": BTN_SWITCH}, {"text": BTN_HELP}]]
    return {"keyboard": rows + _admin_row(user_id), "resize_keyboard": True}


def kb_user_menu(user_id: int):
    return kb_chat_menu(user_id) if user_id in users else kb_channel_menu(user_id)


def txt_wait_note() -> str:
    return (
        "⏱ اخبار جدید تا ۵ دقیقه‌ی بعد ارسال میشه، اگه باشه 🔔\n"
        "اگه نبود هم بهت میگم نبود؛ نگران نباش، صبر می‌کنم ببینم پست گذاشتن یا نه 🙂"
    )


def txt_welcome(name: str) -> str:
    safe_name = escape_markdown(name)
    lines = []
    for key in enabled_keys():
        c = CHANNELS[key]
        title = escape_markdown(c["title"])
        if key == "azad":
            lines.append(f"🕊 *{title}* ⭐ پیشنهادی، اخبارش صحیح‌تره")
        else:
            lines.append(f"{c['icon']} *{title}*")
    channels_block = "\n".join(lines)
    return f"""✨ *اخبار ایران* ✨
{POST_DIVIDER}
سلام {safe_name} 👋
یه کانال انتخاب کن تا {fa(POST_COUNT)} پست آخرش رو بگیری؛ بعدش هر ۵ دقیقه خبرهای تازه خودکار میاد 🔔

{channels_block}
{POST_DIVIDER}
⏱ خبر جدید تا ۵ دقیقه‌ی بعد ارسال میشه؛ اگه نبود هم بهت میگم، نگران نباش صبر می‌کنم 🙂

👇 یکی رو بزن"""


def txt_pick_channel() -> str:
    return "🔽 لطفاً از دکمه‌های پایین یکی از کانال‌ها رو انتخاب کن"


def txt_loading(title: str) -> str:
    return f"""┏━━━━━━━━━━━━━━━━━━┓
   ✅ *کانال فعال: {escape_markdown(title)}*
┗━━━━━━━━━━━━━━━━━━┛
{DIVIDER_SOFT}
⏳ دارم {fa(POST_COUNT)} پست آخر رو می‌گیرم، چند لحظه صبر کن..."""


def txt_fetch_error() -> str:
    return "⚠️ نتونستم پست‌ها رو از کانال بگیرم — چند لحظه‌ی دیگه دوباره دکمه‌ی کانال رو بزن 🙏"


def txt_no_posts() -> str:
    return "📭 فعلاً پستی تو این کانال پیدا نکردم."


def txt_no_news() -> str:
    return (
        "📭 خبر جدیدی نبود\n"
        "نگران نباش، صبر می‌کنم ببینم پست گذاشتن یا نه 🙂"
    )


def txt_help() -> str:
    extra = ""
    if CHANNELS.get("azad", {}).get("enabled"):
        extra = "\n⭐ ایران آزاد اخبارش صحیح‌تره و پیشنهاد ما همونه."
    return f"""❕ 《 *راهنمای استفاده* 》
{DIVIDER}
1️⃣  یکی از کانال‌ها رو انتخاب کن
2️⃣  {fa(POST_COUNT)} پست آخر همون لحظه برات فرستاده میشه
3️⃣  بعدش هر ۵ دقیقه چک می‌کنم و اگه خبر جدید بود خودکار برات می‌فرستم

🔁 هر وقت خواستی با دکمه‌ی «تغییر کانال» بین کانال‌ها سوییچ کن؛ با سوییچ، {fa(POST_COUNT)} پست آخر کانال جدید هم فرستاده میشه.{extra}"""


def txt_forced_move(old_title: str, new_title: str) -> str:
    return (
        f"⚠️ کانال *{escape_markdown(old_title)}* توسط مدیریت غیرفعال شد.\n"
        f"↪️ خودکار رفتی روی *{escape_markdown(new_title)}* و آخرین پست‌هاش رو برات می‌فرستم؛ "
        "هر وقت خواستی با «تغییر کانال» عوضش کن."
    )


def txt_channel_disabled() -> str:
    return "⛔ این کانال فعلاً غیرفعاله؛ یکی از کانال‌های فعال رو انتخاب کن."


# ───────────────────────── انتخاب و سوییچ کانال ─────────────────────────

async def start_channel(user_id: int, chat_id: int, ckey: str, notice=None, count: int = POST_COUNT):
    info = CHANNELS.get(ckey)
    if not info or not info.get("enabled", True):
        await safe_send(chat_id=chat_id, text=txt_channel_disabled(), reply_markup=kb_channel_menu(user_id))
        return

    gen = bump_gen(user_id)
    if notice:
        await safe_send(chat_id=chat_id, text=notice, reply_markup=kb_chat_menu(user_id))
    else:
        await safe_send(chat_id=chat_id, text=txt_loading(info["title"]), reply_markup=kb_chat_menu(user_id))

    posts = []
    async with get_lock(user_id):
        if user_gen.get(user_id) != gen:
            return
        try:
            posts, newest_id = await fetch_recent(ckey, count)
        except Exception as e:
            print(f"❌ fetch_recent exception: {type(e).__name__}: {e}")
            traceback.print_exc()
            await safe_send(chat_id=chat_id, text=txt_fetch_error(), reply_markup=kb_chat_menu(user_id))
            return

        users[user_id] = {"chat_id": chat_id, "channel": ckey, "last_id": newest_id}
        save_state()

        try:
            if not posts:
                await safe_send(chat_id=chat_id, text=txt_no_posts())
            else:
                await deliver_posts(chat_id, posts, user_id, gen)
        finally:
            cleanup_posts(posts)

        if user_gen.get(user_id) == gen:
            await safe_send(chat_id=chat_id, text=txt_wait_note(), reply_markup=kb_chat_menu(user_id))


async def force_move(user_id: int, chat_id: int, old_key: str, new_key: str):
    old_title = CHANNELS.get(old_key, {}).get("title", "")
    notice = txt_forced_move(old_title, CHANNELS[new_key]["title"])
    await start_channel(user_id, chat_id, new_key, notice=notice, count=FORCED_SWITCH_COUNT)


# ───────────────────────── چک دوره‌ای هر ۵ دقیقه ─────────────────────────

async def deliver_new(user_id: int, ckey: str, gen: int, posts: list, newest_id: int):
    async with get_lock(user_id):
        state = users.get(user_id)
        if not state or state["channel"] != ckey or user_gen.get(user_id) != gen:
            return
        chat_id = state["chat_id"]
        fresh = [p for p in posts if p.id > state["last_id"]]

        if not fresh:
            if newest_id > state["last_id"]:
                state["last_id"] = newest_id
                save_state()
            if SHOW_NO_NEWS_NOTICE:
                await safe_send(chat_id=chat_id, text=txt_no_news())
            return

        ok = await deliver_posts(chat_id, fresh, user_id, gen)
        if ok:
            state["last_id"] = max(state["last_id"], newest_id)
            save_state()


async def check_all():
    by_channel: dict = {}
    for user_id, state in list(users.items()):
        ckey = state["channel"]
        if not CHANNELS.get(ckey, {}).get("enabled", False):
            fb = fallback_key()
            if fb:
                spawn(force_move(user_id, state["chat_id"], ckey, fb))
            continue
        by_channel.setdefault(ckey, []).append((user_id, user_gen.get(user_id, 0)))

    for ckey, members in by_channel.items():
        username = CHANNELS[ckey]["username"]
        min_last = min(users[uid]["last_id"] for uid, _ in members if uid in users)
        try:
            posts, newest_id = await fetch_since(ckey, min_last)
        except Exception as e:
            print(f"❌ fetch_since({username}) exception: {type(e).__name__}: {e}")
            traceback.print_exc()
            continue
        print(f"🔎 {username}: {len(posts)} پست جدید برای {len(members)} کاربر")
        try:
            await asyncio.gather(
                *[deliver_new(uid, ckey, gen, posts, newest_id) for uid, gen in members],
                return_exceptions=True,
            )
        finally:
            cleanup_posts(posts)


async def news_loop():
    await asyncio.sleep(CHECK_INTERVAL)
    while True:
        try:
            await check_all()
        except Exception as e:
            print(f"❌ news_loop exception: {type(e).__name__}: {e}")
            traceback.print_exc()
        await asyncio.sleep(CHECK_INTERVAL)


# ───────────────────────── پنل مدیریت ─────────────────────────

def kb_admin_panel():
    return {
        "keyboard": [
            [{"text": ADM_ADD}, {"text": ADM_LIST}],
            [{"text": ADM_DISABLE}, {"text": ADM_ENABLE}],
            [{"text": ADM_FOOTER}, {"text": ADM_FOOTER_DEL}],
            [{"text": ADM_BROADCAST}],
            [{"text": ADM_BACK}],
        ],
        "resize_keyboard": True,
    }


def kb_admin_cancel():
    return {"keyboard": [[{"text": ADM_CANCEL}]], "resize_keyboard": True}


def kb_admin_confirm():
    return {"keyboard": [[{"text": ADM_SEND}, {"text": ADM_CANCEL}]], "resize_keyboard": True}


def kb_admin_pick(buttons: list):
    rows = [[{"text": t}] for t in buttons] + [[{"text": ADM_CANCEL}]]
    return {"keyboard": rows, "resize_keyboard": True}


def txt_admin_panel() -> str:
    footer_state = "✅ روشن" if get_footer() else "⛔ خاموش"
    return (
        f"🛠 پنل مدیریت\n{POST_DIVIDER}\n"
        f"👥 کل کاربرها: {fa(len(chats))}\n"
        f"📨 دارای کانال فعال: {fa(len(users))}\n"
        f"📡 کانال‌های فعال: {fa(len(enabled_keys()))} از {fa(len(CHANNELS))}\n"
        f"✏️ فوتر: {footer_state}"
    )


async def send_panel(chat_id: int, prefix: str = ""):
    text = (prefix + "\n\n" if prefix else "") + txt_admin_panel()
    await plain_send(chat_id, text, reply_markup=kb_admin_panel())


async def validate_channel(username: str):
    try:
        entity = await tg_client.get_entity(username)
    except Exception:
        return False, "⚠️ کانالی با این یوزرنیم پیدا نشد. دوباره بفرست یا «لغو» رو بزن."
    if not getattr(entity, "broadcast", False):
        return False, "⚠️ این یوزرنیم کانال نیست (گروه یا کاربره). یه کانال بفرست یا «لغو» رو بزن."
    try:
        await tg_client.get_messages(entity, limit=1)
    except Exception:
        return False, "⚠️ نتونستم پست‌های این کانال رو بخونم. یه کانال عمومی دیگه بفرست یا «لغو» رو بزن."
    return True, (getattr(entity, "title", "") or username)


async def admin_add_channel(chat_id: int, user_id: int, text: str):
    match = re.fullmatch(r"@([A-Za-z][A-Za-z0-9_]{3,31})", text.strip())
    if not match:
        await plain_send(chat_id, "⚠️ فرمت درست نیست. یوزرنیم رو مثل @username بفرست.", reply_markup=kb_admin_cancel())
        return
    username = match.group(1)

    existing = find_key_by_username(username)
    if existing:
        admin_state.pop(user_id, None)
        status = "فعاله ✅" if CHANNELS[existing]["enabled"] else "غیرفعاله ⛔ (از «فعال کردن کانال» روشنش کن)"
        await send_panel(chat_id, f"ℹ️ این کانال از قبل تو لیسته و {status}")
        return

    await plain_send(chat_id, "⏳ دارم کانال رو چک می‌کنم...", reply_markup=kb_admin_cancel())
    ok, result = await validate_channel(username)
    if not ok:
        await plain_send(chat_id, result, reply_markup=kb_admin_cancel())
        return

    title = result
    key = "c_" + username.lower()
    label = f"📡 {title}"
    if any(c["label"] == label for c in CHANNELS.values()):
        label = f"📡 {title} ({username})"
    CHANNELS[key] = {"label": label, "username": username, "title": title, "icon": "📡", "enabled": True}
    save_state()
    admin_state.pop(user_id, None)
    await send_panel(chat_id, f"✅ کانال «{title}» (@{username}) اضافه و فعال شد؛ دکمه‌ش تو منوی کاربرها اومد.")


async def admin_toggle_channel(chat_id: int, key: str, enable: bool):
    info = CHANNELS[key]
    if enable:
        info["enabled"] = True
        save_state()
        await send_panel(chat_id, f"✅ کانال «{info['title']}» فعال شد و دکمه‌ش به منو برگشت.")
        return

    if len(enabled_keys()) <= 1:
        await send_panel(chat_id, "⚠️ این آخرین کانال فعاله؛ نمیشه غیرفعالش کرد.")
        return

    info["enabled"] = False
    fb = fallback_key()
    movers = [(uid, st["chat_id"]) for uid, st in users.items() if st["channel"] == key]
    save_state()
    for uid, cid in movers:
        spawn(force_move(uid, cid, key, fb))
    await send_panel(
        chat_id,
        f"⛔ کانال «{info['title']}» غیرفعال شد و دکمه‌ش از منو حذف شد.\n"
        f"↪️ {fa(len(movers))} نفر که روش بودن خودکار رفتن روی «{CHANNELS[fb]['title']}».",
    )


async def do_broadcast(admin_chat_id: int, text: str):
    chunks = split_text(f"📢 پیام از طرف مدیریت\n{POST_DIVIDER}\n{text}")
    ok = fail = 0
    for _uid, cid in list(chats.items()):
        first = None
        for i, chunk in enumerate(chunks):
            result = await plain_send(cid, chunk)
            if i == 0:
                first = result
        if first is not None:
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(BROADCAST_DELAY)
    await send_panel(admin_chat_id, f"✅ پیام همگانی ارسال شد\n📬 موفق: {fa(ok)}\n⚠️ ناموفق: {fa(fail)}")


async def admin_handle(text: str, chat_id: int, user_id: int) -> bool:
    state = admin_state.get(user_id)

    if text == BTN_ADMIN or text == ADM_CANCEL:
        admin_state.pop(user_id, None)
        await send_panel(chat_id)
        return True

    if text == ADM_BACK:
        admin_state.pop(user_id, None)
        await plain_send(chat_id, "🔙 از پنل مدیریت خارج شدی.", reply_markup=kb_user_menu(user_id))
        return True

    if text == ADM_ADD:
        admin_state[user_id] = {"mode": "add"}
        await plain_send(chat_id, "➕ یوزرنیم کانال رو با فرمت @username بفرست:", reply_markup=kb_admin_cancel())
        return True

    if text == ADM_LIST:
        lines = []
        for key, c in CHANNELS.items():
            count = sum(1 for st in users.values() if st["channel"] == key)
            mark = "✅" if c["enabled"] else "⛔"
            lines.append(f"{mark} {c['title']} — @{c['username']} — 👥 {fa(count)}")
        await plain_send(chat_id, "📋 کانال‌ها\n" + POST_DIVIDER + "\n" + "\n".join(lines), reply_markup=kb_admin_panel())
        return True

    if text in (ADM_DISABLE, ADM_ENABLE):
        enable = text == ADM_ENABLE
        keys = [k for k, c in CHANNELS.items() if bool(c["enabled"]) != enable]
        if not enable and len(enabled_keys()) <= 1:
            await send_panel(chat_id, "⚠️ فقط یه کانال فعال مونده؛ نمیشه غیرفعالش کرد.")
            return True
        if not keys:
            await send_panel(chat_id, "ℹ️ کانال غیرفعالی وجود نداره." if enable else "ℹ️ کانالی برای غیرفعال کردن نیست.")
            return True
        prefix = "▶️" if enable else "⏸"
        mapping = {f"{prefix} {CHANNELS[k]['title']} — {CHANNELS[k]['username']}": k for k in keys}
        admin_state[user_id] = {"mode": "enable" if enable else "disable", "map": mapping}
        question = "▶️ کدوم کانال فعال بشه؟" if enable else "⏸ کدوم کانال غیرفعال بشه؟"
        await plain_send(chat_id, question, reply_markup=kb_admin_pick(list(mapping.keys())))
        return True

    if text == ADM_FOOTER:
        admin_state[user_id] = {"mode": "footer"}
        current = get_footer()
        hint = f"\n\nفوتر فعلی:\n{current}" if current else ""
        await plain_send(
            chat_id,
            f"✏️ متن فوتر رو بفرست؛ زیر هر خبر قرار می‌گیره (حداکثر {fa(FOOTER_MAX_LEN)} کاراکتر).{hint}",
            reply_markup=kb_admin_cancel(),
        )
        return True

    if text == ADM_FOOTER_DEL:
        settings["footer"] = ""
        save_state()
        await send_panel(chat_id, "🗑 فوتر حذف شد.")
        return True

    if text == ADM_BROADCAST:
        admin_state[user_id] = {"mode": "broadcast"}
        await plain_send(chat_id, "📢 متن پیام همگانی رو بفرست:", reply_markup=kb_admin_cancel())
        return True

    if text == ADM_SEND:
        if state and state.get("mode") == "confirm":
            admin_state.pop(user_id, None)
            spawn(do_broadcast(chat_id, state["text"]))
            await plain_send(chat_id, f"⏳ دارم برای {fa(len(chats))} نفر می‌فرستم...", reply_markup=kb_admin_panel())
        else:
            await send_panel(chat_id)
        return True

    if not state:
        return False

    mode = state.get("mode")

    if mode == "add":
        await admin_add_channel(chat_id, user_id, text)
        return True

    if mode in ("enable", "disable"):
        key = state["map"].get(text)
        if key is None:
            match = re.fullmatch(r"@?([A-Za-z][A-Za-z0-9_]{3,31})", text)
            cand = find_key_by_username(match.group(1)) if match else None
            key = cand if cand in state["map"].values() else None
        if key is None:
            await plain_send(chat_id, "⚠️ یکی از دکمه‌ها رو بزن یا «لغو».", reply_markup=kb_admin_pick(list(state["map"].keys())))
            return True
        admin_state.pop(user_id, None)
        await admin_toggle_channel(chat_id, key, enable=(mode == "enable"))
        return True

    if mode == "footer":
        if len(text) > FOOTER_MAX_LEN:
            await plain_send(chat_id, f"⚠️ فوتر خیلی بلنده (حداکثر {fa(FOOTER_MAX_LEN)} کاراکتر). کوتاه‌ترش کن.", reply_markup=kb_admin_cancel())
            return True
        settings["footer"] = text
        save_state()
        admin_state.pop(user_id, None)
        await plain_send(chat_id, "✅ فوتر ذخیره شد؛ از الان زیر هر خبر میاد:\n" + POST_DIVIDER + "\n" + text, reply_markup=kb_admin_panel())
        return True

    if mode == "broadcast":
        admin_state[user_id] = {"mode": "confirm", "text": text}
        preview = f"📢 پیش‌نمایش (برای {fa(len(chats))} نفر ارسال میشه):\n{POST_DIVIDER}\n📢 پیام از طرف مدیریت\n{POST_DIVIDER}\n{text}"
        await plain_send(chat_id, preview, reply_markup=kb_admin_confirm())
        return True

    if mode == "confirm":
        await plain_send(chat_id, "یکی از دکمه‌ها رو بزن: «ارسال» یا «لغو».", reply_markup=kb_admin_confirm())
        return True

    return False


# ───────────────────────── هندلرهای ربات ─────────────────────────

@bot.on(Filters.command("start"))
async def start_handler(update: Update):
    message = update.message
    user = message.from_user
    name = user.first_name or "دوست من"
    register_chat(user.id, message.chat.id)
    admin_state.pop(user.id, None)
    await safe_send(chat_id=message.chat.id, text=txt_welcome(name), reply_markup=kb_channel_menu(user.id))


@bot.on(Filters.command("help"))
async def help_handler(update: Update):
    user_id = update.message.from_user.id
    register_chat(user_id, update.message.chat.id)
    await safe_send(chat_id=update.message.chat.id, text=txt_help(), reply_markup=kb_user_menu(user_id))


@bot.on(Filters.text)
async def text_handler(update: Update):
    message = update.message
    text = (message.text or "").strip()
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not text or text.startswith("/"):
        return

    register_chat(user_id, chat_id)

    if user_id == ADMIN_ID:
        try:
            if await admin_handle(text, chat_id, user_id):
                return
        except Exception as e:
            print(f"❌ admin_handle exception: {type(e).__name__}: {e}")
            traceback.print_exc()
            admin_state.pop(user_id, None)
            await plain_send(chat_id, "⚠️ تو پنل مدیریت خطایی پیش اومد، دوباره امتحان کن.", reply_markup=kb_admin_panel())
            return
    elif text in ADMIN_TEXTS:
        return

    key = label_to_key(text)
    if key:
        spawn(start_channel(user_id, chat_id, key))
        return

    if label_to_key(text, enabled=False):
        await safe_send(chat_id=chat_id, text=txt_channel_disabled(), reply_markup=kb_user_menu(user_id))
        return

    if text == BTN_SWITCH:
        await safe_send(chat_id=chat_id, text=txt_pick_channel(), reply_markup=kb_channel_menu(user_id))
        return

    if text == BTN_HELP:
        await safe_send(chat_id=chat_id, text=txt_help(), reply_markup=kb_user_menu(user_id))
        return

    await safe_send(chat_id=chat_id, text=txt_pick_channel(), reply_markup=kb_user_menu(user_id))


# ───────────────────────── سرور سلامت + پینگ (برای Render) ─────────────────────────

async def _handle_http(reader, writer):
    try:
        data = await asyncio.wait_for(reader.read(1024), timeout=5)
    except Exception:
        data = b""
    is_head = data.startswith(b"HEAD")
    body = b"OK"
    head = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
        + b"Content-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n"
    )
    try:
        writer.write(head if is_head else head + body)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def start_health_server():
    server = await asyncio.start_server(_handle_http, "0.0.0.0", PORT)
    print(f"🌐 سرور سلامت روی پورت {PORT} بالا اومد.")
    async with server:
        await server.serve_forever()


def _ping_once(url: str) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "keep-alive-ping"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


async def ping_loop():
    if not PING_URL:
        print("⚠️ RENDER_EXTERNAL_URL / PING_URL تنظیم نشده — پینگ خودکار غیرفعاله.")
        while True:
            await asyncio.sleep(3600)
    loop = asyncio.get_running_loop()
    await asyncio.sleep(60)
    while True:
        for _ in range(3):
            try:
                status = await loop.run_in_executor(None, _ping_once, PING_URL)
                print(f"🏓 پینگ {PING_URL} → {status}")
                break
            except Exception as e:
                print(f"⚠️ پینگ fail شد: {type(e).__name__}: {e}")
                await asyncio.sleep(5)
        await asyncio.sleep(PING_INTERVAL)


# ───────────────────────── نگهبان‌ها: هیچ بخشی نباید بمیره ─────────────────────────

async def supervise(name: str, factory, base_delay: int = 3, max_delay: int = 60):
    delay = base_delay
    while True:
        started = time.monotonic()
        try:
            await factory()
            print(f"⚠️ بخش «{name}» تموم شد؛ دوباره راه می‌اندازمش.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ بخش «{name}» کرش کرد: {type(e).__name__}: {e}")
            traceback.print_exc()
        if time.monotonic() - started > 120:
            delay = base_delay
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)


async def tg_watchdog():
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL)
        if not tg_client.is_connected():
            print("⚠️ اتصال تلگرام قطع شده؛ دوباره وصل می‌شم...")
            await tg_client.connect()


async def connect_telegram() -> bool:
    delay = 3
    while True:
        try:
            if TELEGRAM_SESSION_STRING:
                await tg_client.connect()
                if not await tg_client.is_user_authorized():
                    print("❌ TELEGRAM_SESSION_STRING معتبر نیست؛ دوباره بسازش و تو Environment بذار.")
                    return False
            else:
                await tg_client.start(phone=PHONE_NUMBER)
            return True
        except Exception as e:
            print(f"⚠️ اتصال به تلگرام نشد: {type(e).__name__}: {e} — {delay} ثانیه دیگه دوباره...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


async def main():
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(
        lambda _loop, ctx: print(f"⚠️ asyncio: {ctx.get('message')} {ctx.get('exception')!r}")
    )

    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    runners = [
        spawn(supervise("health", start_health_server)),
        spawn(supervise("ping", ping_loop)),
    ]

    print("🔌 در حال اتصال به تلگرام (Telethon)...")
    if not await connect_telegram():
        raise SystemExit(1)
    print("✅ اتصال تلگرام برقرار شد.")
    await restore_state()

    print("📰 ربات خبری سروش پلاس در حال اجراست...")
    runners += [
        spawn(supervise("bot", bot.run_polling)),
        spawn(supervise("watchdog", tg_watchdog)),
        spawn(supervise("news", news_loop)),
        spawn(supervise("backup", backup_loop)),
    ]

    await stop_event.wait()
    print("🛑 سیگنال خاموشی گرفتم؛ وضعیت کاربرها رو ذخیره می‌کنم...")
    try:
        _write_state_file()
        await asyncio.wait_for(backup_state(), timeout=15)
    except Exception as e:
        print(f"⚠️ ذخیره‌ی نهایی نشد: {type(e).__name__}: {e}")
    for task in runners:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
