import asyncio
import base64
import html
import http.client
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import socket
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from vplus import VPlusClient, Filters, Update, escape_markdown
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

SOROUSH_BOT_TOKEN = "70838335:Lg8jMdDqIQQpX96ayAsKTA-0-ZPRL1ExuYk"

TELEGRAM_API_ID = 2040
TELEGRAM_API_HASH = "b18441a1ff607e10a989891a5462e627"
TELEGRAM_SESSION_NAME = "news_bridge_session"
PHONE_NUMBER = "+989386341312"
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", "")

PORT = int(os.environ.get("PORT", "10000"))
PING_URL = os.environ.get("RENDER_EXTERNAL_URL", "") or os.environ.get("PING_URL", "")
PING_INTERVAL = 240
STATE_TAG = "NEWSBOT_STATE_V1"
STATE_BACKUP_INTERVAL = 3600
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
DEFAULT_MAX_FILE_MB = 10
GOOGLE_PAGE_SIZE = 10
GOOGLE_COOLDOWN = 5
MAX_PAGE_BYTES = 2 * 1024 * 1024
PAGE_TTL = 300
DOWNLOAD_COOLDOWN = 10
DOWNLOAD_MAX_SECONDS = 1200
PAGE_CACHE_MAX = 30
SEARCH_TOKEN_TTL = 7200
SEARCH_TOKEN_MAX_USES = 600
OPEN_PAGE_AS_WEBAPP = True
MAX_FILE_MB_CEILING = 2000
SEARCH_COOLDOWN = 20
SEED_CHANNELS = ["ir_km"]
USERNAME_RE = re.compile(r"(?:https?://t\.me/|@)?([A-Za-z][A-Za-z0-9_]{3,31})")
SHOW_NO_NEWS_NOTICE = True
SHORT_LINE_LETTERS = 20

CHANNELS = {
    "azad":  {"label": "🕊 ایران آزاد ⭐ بهتر و صحیح‌تر", "username": "IraneAzad_News", "title": "ایران آزاد",       "icon": "🕊", "enabled": True},
    "inter": {"label": "📺 ایران اینترنشنال",              "username": "IranintlTV",     "title": "ایران اینترنشنال", "icon": "📺", "enabled": True},
}

BTN_SWITCH = "🔁 تغییر کانال"
BTN_HELP = "❕ راهنما"
BTN_ADMIN = "🛠 مدیریت"
BTN_SEARCH = "🔎 جستجو"
BTN_GOOGLE = "🌐 گوگل"
BTN_DL = "📥 دانلود فایل"
BTN_DL_CANCEL = "❌ لغو دانلود"
ADM_DL_ON = "📥 فعال کردن دانلود"
ADM_DL_OFF = "📥 غیرفعال کردن دانلود"
BTN_G_MORE = "➡️ بیشتر"
BTN_G_NEW = "🔄 جستجوی جدید"
BTN_G_EXIT = "❌ خروج از گوگل"
BTN_OPEN_PAGE = "🎮 باز کردن صفحه"
BTN_OPEN_SEARCH = "🔎 باز کردن جستجو"
ADM_GOOGLE_ON = "🌐 فعال کردن گوگل"
ADM_GOOGLE_OFF = "🌐 غیرفعال کردن گوگل"
BTN_SEARCH_CANCEL = "❌ انصراف"
ADM_SEARCH_ON = "🔎 فعال کردن جستجو"
ADM_MAXSIZE = "📏 تنظیم حجم فایل"
ADM_SEARCH_OFF = "🔎 غیرفعال کردن جستجو"
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
    ADM_SEARCH_ON, ADM_SEARCH_OFF, ADM_MAXSIZE, ADM_GOOGLE_ON, ADM_GOOGLE_OFF,
    ADM_DL_ON, ADM_DL_OFF,
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
settings: dict = {"footer": "", "search_enabled": False, "google_enabled": False, "download_enabled": False, "max_file_mb": DEFAULT_MAX_FILE_MB}
google_state: dict = {}
last_google: dict = {}
dl_state: dict = {}
last_dl: dict = {}
downloading: set = set()


def _clear_modes(user_id: int):
    search_state.pop(user_id, None)
    google_state.pop(user_id, None)
    dl_state.pop(user_id, None)
search_state: dict = {}
last_search: dict = {}
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
    settings["search_enabled"] = bool(parsed["settings"].get("search_enabled", False))
    settings["google_enabled"] = bool(parsed["settings"].get("google_enabled", False))
    settings["download_enabled"] = bool(parsed["settings"].get("download_enabled", False))
    try:
        mb = float(parsed["settings"].get("max_file_mb", DEFAULT_MAX_FILE_MB))
        if not 0 < mb <= MAX_FILE_MB_CEILING:
            raise ValueError
    except Exception:
        mb = DEFAULT_MAX_FILE_MB
    settings["max_file_mb"] = mb


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


def get_max_file_bytes() -> int:
    return int(float(settings.get("max_file_mb", DEFAULT_MAX_FILE_MB)) * 1024 * 1024)


def fmt_mb(mb) -> str:
    mb = float(mb)
    return fa(int(mb) if mb.is_integer() else round(mb, 2))


def parse_mb(text: str):
    t = text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫,", "01234567890123456789.."))
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        return None
    value = float(t)
    return value if 0 < value <= MAX_FILE_MB_CEILING else None


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
    """نسخه‌ی پشتیبان وضعیت رو تو Saved Messages اکانت تلگرام نگه می‌داره (پیام قبلی ادیت میشه)."""
    global _state_dirty, _state_msg_id
    if not os.path.exists(STATE_FILE) or not tg_client.is_connected():
        return False
    _state_dirty = False
    try:
        if _state_msg_id:
            try:
                await tg_client.edit_message(
                    "me", _state_msg_id, text=STATE_TAG, file=STATE_FILE, force_document=True
                )
                return True
            except Exception as e:
                if type(e).__name__ == "MessageNotModifiedError":
                    return True
                print(f"⚠️ ادیت پیام بکاپ نشد ({type(e).__name__}); پیام جدید می‌فرستم.")
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

    @property
    def size(self) -> int:
        return getattr(getattr(self.msg, "file", None), "size", 0) or 0

    async def media_path(self, limit=None):
        if limit and self.size > limit:
            return None
        async with self._lock:
            if self.path or self.failed:
                return self.path
            try:
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


def build_posts(messages, info: dict) -> list:
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
    posts = build_posts(messages, CHANNELS[ckey])[-count:]
    return posts, newest_id


async def fetch_since(ckey: str, after_id: int):
    messages = await _scan(CHANNELS[ckey]["username"], NEW_SCAN_LIMIT, min_id=after_id)
    newest_id = max((m.id for m in messages), default=after_id)
    posts = build_posts(messages, CHANNELS[ckey])
    return posts, newest_id


# ───────────────────────── ارسال پست‌ها به کاربر ─────────────────────────

async def send_post(chat_id: int, post: Post, user_id=None):
    body = post.text
    footer = get_footer()
    full = compose_post(post.header, body, footer)
    limit = None if user_id == ADMIN_ID else get_max_file_bytes()
    too_big = False

    if post.kind in ("photo", "video"):
        path = await post.media_path(limit)
        if not path and limit and post.size > limit:
            too_big = True
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
            note = "🎬 این پست ویدیو داشت"
            if too_big:
                note += f" (حجمش بیشتر از {fmt_mb(settings.get('max_file_mb'))} مگابایته)"
            body = (note + "\n\n" + body).strip()
            full = compose_post(post.header, body, footer)

    await send_long_plain(chat_id, full)


async def deliver_posts(chat_id: int, posts: list, user_id: int, gen: int) -> bool:
    for post in posts:
        if user_gen.get(user_id, 0) != gen:
            return False
        try:
            await send_post(chat_id, post, user_id)
        except Exception as e:
            print(f"❌ send_post exception: {type(e).__name__}: {e}")
            traceback.print_exc()
        await asyncio.sleep(SEND_DELAY)
    return True


def cleanup_posts(posts: list):
    for post in posts:
        post.cleanup()


# ───────────────────────── کیبوردها و متن‌ها ─────────────────────────

def _extra_rows(user_id):
    items = []
    if settings.get("search_enabled") or user_id == ADMIN_ID:
        items.append(BTN_SEARCH)
    if settings.get("google_enabled") or user_id == ADMIN_ID:
        items.append(BTN_GOOGLE)
    if settings.get("download_enabled") or user_id == ADMIN_ID:
        items.append(BTN_DL)
    rows = [[{"text": t} for t in items[i:i + 2]] for i in range(0, len(items), 2)]
    if user_id == ADMIN_ID:
        rows.append([{"text": BTN_ADMIN}])
    return rows


def kb_channel_menu(user_id=None):
    rows = [[{"text": CHANNELS[k]["label"]}] for k in enabled_keys()]
    return {"keyboard": rows + _extra_rows(user_id), "resize_keyboard": True}


def kb_chat_menu(user_id=None):
    rows = [[{"text": BTN_SWITCH}, {"text": BTN_HELP}]]
    return {"keyboard": rows + _extra_rows(user_id), "resize_keyboard": True}


def kb_search_cancel():
    return {"keyboard": [[{"text": BTN_SEARCH_CANCEL}]], "resize_keyboard": True}


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
    if settings.get("download_enabled"):
        extra += "\n📥 با دکمه‌ی «دانلود فایل»، لینک مستقیم یه فایل رو بفرست تا برات دانلود و آپلود کنم."
    if settings.get("google_enabled"):
        extra += "\n🌐 با دکمه‌ی «گوگل» هر چی خواستی جستجو کن و صفحه‌ی نتیجه رو همین‌جا باز کن."
    if settings.get("search_enabled"):
        extra += f"\n🔎 با دکمه‌ی «جستجو»، یوزرنیم هر کانال عمومی رو بفرست تا {fa(POST_COUNT)} پست آخرش رو ببینی."
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


def txt_search_prompt() -> str:
    return "🔎 یوزرنیم کانال رو بفرست (مثلاً @username) تا " + fa(POST_COUNT) + " پست آخرش رو نشونت بدم:"


def txt_search_disabled() -> str:
    return "🔎 جستجو فعلاً غیرفعاله."


SEARCH_ERRORS = {
    "notfound": "⚠️ کانالی با این یوزرنیم پیدا نشد. دوباره بفرست یا «انصراف» رو بزن.",
    "notchannel": "⚠️ این یوزرنیم کانال نیست؛ فقط کانال‌ها قابل جستجوان. دوباره بفرست یا «انصراف» رو بزن.",
    "unreadable": "⚠️ نتونستم پست‌های این کانال رو بخونم (شاید خصوصیه). یه کانال عمومی بفرست یا «انصراف» رو بزن.",
}

ADD_ERRORS = {
    "notfound": "⚠️ کانالی با این یوزرنیم پیدا نشد. دوباره بفرست یا «لغو» رو بزن.",
    "notchannel": "⚠️ این یوزرنیم کانال نیست (گروه یا کاربره). یه کانال بفرست یا «لغو» رو بزن.",
    "unreadable": "⚠️ نتونستم پست‌های این کانال رو بخونم. یه کانال عمومی دیگه بفرست یا «لغو» رو بزن.",
}


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
        if user_gen.get(user_id, 0) != gen:
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

        if user_gen.get(user_id, 0) == gen:
            await safe_send(chat_id=chat_id, text=txt_wait_note(), reply_markup=kb_chat_menu(user_id))


async def force_move(user_id: int, chat_id: int, old_key: str, new_key: str):
    old_title = CHANNELS.get(old_key, {}).get("title", "")
    notice = txt_forced_move(old_title, CHANNELS[new_key]["title"])
    await start_channel(user_id, chat_id, new_key, notice=notice, count=FORCED_SWITCH_COUNT)


# ───────────────────────── چک دوره‌ای هر ۵ دقیقه ─────────────────────────

async def deliver_new(user_id: int, ckey: str, gen: int, posts: list, newest_id: int):
    async with get_lock(user_id):
        state = users.get(user_id)
        if not state or state["channel"] != ckey or user_gen.get(user_id, 0) != gen:
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
            [{"text": ADM_SEARCH_OFF if settings.get("search_enabled") else ADM_SEARCH_ON}, {"text": ADM_MAXSIZE}],
            [{"text": ADM_GOOGLE_OFF if settings.get("google_enabled") else ADM_GOOGLE_ON},
             {"text": ADM_DL_OFF if settings.get("download_enabled") else ADM_DL_ON}],
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
        f"✏️ فوتر: {footer_state}\n"
        f"🔎 جستجوی عمومی: {'✅ روشن' if settings.get('search_enabled') else '⛔ خاموش'}\n"
        f"📥 دانلود فایل برای عموم: {'✅ روشن' if settings.get('download_enabled') else '⛔ خاموش'}\n"
        f"🌐 گوگل برای عموم: {'✅ روشن' if settings.get('google_enabled') else '⛔ خاموش'}\n"
        f"📏 حداکثر حجم فایل: {fmt_mb(settings.get('max_file_mb'))} مگابایت (مدیریت بدون محدودیت)"
    )


async def send_panel(chat_id: int, prefix: str = ""):
    text = (prefix + "\n\n" if prefix else "") + txt_admin_panel()
    await plain_send(chat_id, text, reply_markup=kb_admin_panel())


async def validate_channel(username: str):
    """(ok, title, error_code)"""
    try:
        entity = await tg_client.get_entity(username)
    except Exception:
        return False, "", "notfound"
    if not getattr(entity, "broadcast", False):
        return False, "", "notchannel"
    try:
        await tg_client.get_messages(entity, limit=1)
    except Exception:
        return False, "", "unreadable"
    return True, (getattr(entity, "title", "") or username), ""


def add_channel_entry(username: str, title: str) -> str:
    key = "c_" + username.lower()
    label = f"📡 {title}"
    if any(c["label"] == label for c in CHANNELS.values()):
        label = f"📡 {title} ({username})"
    CHANNELS[key] = {"label": label, "username": username, "title": title, "icon": "📡", "enabled": True}
    save_state()
    return key


async def seed_channels():
    for username in SEED_CHANNELS:
        if find_key_by_username(username):
            continue
        ok, title, err = await validate_channel(username)
        if not ok:
            print(f"⚠️ کانال پیش‌فرض @{username} اضافه نشد ({err}).")
            continue
        add_channel_entry(username, title)
        print(f"➕ کانال پیش‌فرض @{username} ({title}) اضافه شد.")


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
    ok, title, err = await validate_channel(username)
    if not ok:
        await plain_send(chat_id, ADD_ERRORS[err], reply_markup=kb_admin_cancel())
        return

    add_channel_entry(username, title)
    admin_state.pop(user_id, None)
    await send_panel(chat_id, f"✅ کانال «{title}» (@{username}) اضافه و فعال شد؛ دکمه‌ش تو منوی کاربرها اومد.")


async def run_search(user_id: int, chat_id: int, username: str):
    if user_id != ADMIN_ID:
        wait = SEARCH_COOLDOWN - (time.monotonic() - last_search.get(user_id, -10 ** 9))
        if wait > 0:
            search_state[user_id] = True
            await plain_send(chat_id, f"⏳ {fa(int(wait) + 1)} ثانیه‌ی دیگه دوباره امتحان کن.", reply_markup=kb_search_cancel())
            return
        last_search[user_id] = time.monotonic()

    ok, title, err = await validate_channel(username)
    if not ok:
        search_state[user_id] = True
        await plain_send(chat_id, SEARCH_ERRORS[err], reply_markup=kb_search_cancel())
        return

    info = {"icon": "🔎", "title": title}
    posts = []
    try:
        messages = await _scan(username, RECENT_SCAN_LIMIT)
        posts = build_posts(messages, info)[-POST_COUNT:]
    except Exception as e:
        print(f"❌ search fetch exception: {type(e).__name__}: {e}")
        await plain_send(chat_id, txt_fetch_error(), reply_markup=kb_user_menu(user_id))
        return

    async with get_lock(user_id):
        gen = user_gen.get(user_id, 0)
        try:
            await plain_send(chat_id, f"🔎 {fa(len(posts))} پست آخر «{title}»:", reply_markup=kb_user_menu(user_id))
            if posts:
                await deliver_posts(chat_id, posts, user_id, gen)
            else:
                await plain_send(chat_id, txt_no_posts())
        finally:
            cleanup_posts(posts)
        await plain_send(chat_id, "✅ جستجو تموم شد؛ هر وقت خواستی دوباره جستجو کن.", reply_markup=kb_user_menu(user_id))


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
        _clear_modes(user_id)
        await send_panel(chat_id)
        return True

    if text in (ADM_DL_ON, ADM_DL_OFF):
        enable = text == ADM_DL_ON
        settings["download_enabled"] = enable
        save_state()
        await send_panel(
            chat_id,
            "📥 دانلود فایل برای عموم فعال شد ✅ (دکمه‌ی «دانلود فایل» به منوی کاربرها اضافه میشه)"
            if enable else "📥 دانلود فایل برای عموم غیرفعال شد ⛔",
        )
        return True

    if text in (ADM_GOOGLE_ON, ADM_GOOGLE_OFF):
        enable = text == ADM_GOOGLE_ON
        settings["google_enabled"] = enable
        save_state()
        await send_panel(
            chat_id,
            "🌐 گوگل برای عموم فعال شد ✅ (دکمه‌ی «گوگل» به منوی کاربرها اضافه میشه)"
            if enable else "🌐 گوگل برای عموم غیرفعال شد ⛔",
        )
        return True

    if text == ADM_MAXSIZE:
        admin_state[user_id] = {"mode": "maxsize"}
        await plain_send(
            chat_id,
            f"📏 حداکثر حجم فایل رو به مگابایت بفرست؛ مثلاً 2 یعنی دو مگابایت.\n"
            f"مقدار فعلی: {fmt_mb(settings.get('max_file_mb'))} مگابایت",
            reply_markup=kb_admin_cancel(),
        )
        return True

    if text in (ADM_SEARCH_ON, ADM_SEARCH_OFF):
        enable = text == ADM_SEARCH_ON
        settings["search_enabled"] = enable
        save_state()
        await send_panel(
            chat_id,
            "🔎 جستجو برای عموم فعال شد ✅ (دکمه‌ی «جستجو» به منوی کاربرها اضافه میشه)"
            if enable else "🔎 جستجو برای عموم غیرفعال شد ⛔",
        )
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

    if mode == "maxsize":
        value = parse_mb(text)
        if value is None:
            await plain_send(
                chat_id,
                f"⚠️ یه عدد بین 0 تا {fa(MAX_FILE_MB_CEILING)} بفرست (مثلاً 2 یا 0.5) یا «لغو» رو بزن.",
                reply_markup=kb_admin_cancel(),
            )
            return True
        settings["max_file_mb"] = value
        save_state()
        admin_state.pop(user_id, None)
        await send_panel(chat_id, f"✅ حداکثر حجم فایل روی {fmt_mb(value)} مگابایت تنظیم شد.")
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


# ───────────────────────── گوگل + نمایش صفحه ─────────────────────────

_net_sem = asyncio.Semaphore(4)
page_cache: dict = {}
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0"


class UnsafeAddress(OSError):
    def __str__(self):
        return "unsafe address"


def _ip_blocked(ip) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(
        (not ip.is_global) or ip.is_multicast or ip.is_loopback
        or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    )


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
        if not infos:
            return False
        return not any(_ip_blocked(ipaddress.ip_address(i[4][0].split("%")[0])) for i in infos)
    except Exception:
        return False


def _safe_create_connection(host, port, timeout):
    last = None
    for family, socktype, proto, _canon, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        if _ip_blocked(ipaddress.ip_address(sockaddr[0].split("%")[0])):
            last = UnsafeAddress()
            continue
        sock = socket.socket(family, socktype, proto)
        try:
            if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            last = e
            sock.close()
    raise last or OSError("no address")


class _SafeHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = _safe_create_connection(self.host, self.port, self.timeout)


class _SafeHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        sock = _safe_create_connection(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_SafeHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_SafeHTTPSConnection, req, context=self._context)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_safe_url(newurl):
            raise urllib.error.URLError("redirect to unsafe address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _make_safe_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _SafeHTTPHandler, _SafeHTTPSHandler, _SafeRedirect
    )


def _http_get(url: str, headers=None, data=None, timeout=15, max_bytes=MAX_PAGE_BYTES, safe=False):
    if safe and not _is_safe_url(url):
        raise ValueError("unsafe url")
    opener = _make_safe_opener() if safe else urllib.request.build_opener()
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("response too large")
        return resp.geturl(), resp.headers.get("Content-Type", ""), raw


def _decode_bytes(raw: bytes, content_type: str) -> str:
    charset = None
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        charset = m.group(1)
    else:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", raw[:4096], re.I)
        if m:
            charset = m.group(1).decode("ascii", errors="ignore")
    for enc in (charset, "utf-8"):
        if not enc:
            continue
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


# ── پارسرهای نتایج جستجو

class _DDGParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.cur = None
        self.mode = None
        self.mode_tag = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and ("result__a" in cls or "result-link" in cls):
            href = a.get("href") or ""
            if href.startswith("//"):
                href = "https:" + href
            url = href
            if "duckduckgo.com/l/" in href:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg") or [""]
                url = q[0]
            if "duckduckgo.com/y.js" in href or not url.startswith(("http://", "https://")):
                self.cur = None
                return
            self.cur = {"url": url, "title": "", "snippet": ""}
            self.results.append(self.cur)
            self.mode, self.mode_tag = "title", "a"
        elif tag in ("a", "div", "td") and ("result__snippet" in cls or "result-snippet" in cls) and self.cur is not None:
            self.mode, self.mode_tag = "snippet", tag

    def handle_endtag(self, tag):
        if self.mode and tag == self.mode_tag:
            self.mode = None
            self.mode_tag = None

    def handle_data(self, data):
        if self.cur is None or not self.mode:
            return
        if self.mode == "title":
            self.cur["title"] += data
        else:
            self.cur["snippet"] += data


class _BingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.cur = None
        self.in_h2 = False
        self.in_title = False
        self.in_snip = False
        self.snip_tag = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "li" and "b_algo" in cls:
            self.cur = {"url": "", "title": "", "snippet": ""}
            self.results.append(self.cur)
            self.in_h2 = self.in_title = self.in_snip = False
            return
        if self.cur is None:
            return
        if tag == "h2":
            self.in_h2 = True
        elif tag == "a" and self.in_h2 and not self.cur["url"]:
            self.cur["url"] = _bing_real_url(a.get("href") or "")
            self.in_title = True
        elif (tag == "p" or (tag in ("div", "span") and any(c.startswith("b_lineclamp") for c in cls))) and not self.in_snip:
            self.in_snip = True
            self.snip_tag = tag

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_title = False
        elif tag == "h2":
            self.in_h2 = False
        elif self.in_snip and tag == self.snip_tag:
            self.in_snip = False

    def handle_data(self, data):
        if self.cur is None:
            return
        if self.in_title:
            self.cur["title"] += data
        elif self.in_snip and len(self.cur["snippet"]) < 300:
            self.cur["snippet"] += data


def _bing_real_url(href: str) -> str:
    if "/ck/a" in href:
        u = (urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("u") or [""])[0]
        if u.startswith("a1"):
            b = u[2:]
            b += "=" * (-len(b) % 4)
            try:
                href = base64.urlsafe_b64decode(b).decode("utf-8", "replace")
            except Exception:
                return ""
        else:
            return ""
    return href if href.startswith(("http://", "https://")) else ""


class _MojeekParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.cur = None
        self.mode = None
        self.mode_tag = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "a" and "title" in cls:
            href = a.get("href") or ""
            if not href.startswith(("http://", "https://")):
                self.cur = None
                return
            self.cur = {"url": href, "title": "", "snippet": ""}
            self.results.append(self.cur)
            self.mode, self.mode_tag = "title", "a"
        elif tag == "p" and "s" in cls and self.cur is not None:
            self.mode, self.mode_tag = "snippet", "p"

    def handle_endtag(self, tag):
        if self.mode and tag == self.mode_tag:
            self.mode = self.mode_tag = None

    def handle_data(self, data):
        if self.cur is None or not self.mode:
            return
        self.cur["title" if self.mode == "title" else "snippet"] += data


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def _normalize_results(raw_results: list) -> list:
    out, seen = [], set()
    for r in raw_results:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        title = _clean_text(r.get("h3") or r.get("title") or "")
        if not title:
            continue
        seen.add(url)
        out.append({"url": url, "title": title, "snippet": _clean_text(r.get("snippet") or "")})
    return out


def _ddg_post(url: str, query: str, offset: int) -> str:
    data = urllib.parse.urlencode({"q": query, "s": offset, "kl": "wt-wt"}).encode()
    _, ctype, raw = _http_get(
        url, data=data,
        headers={"User-Agent": _BROWSER_UA, "Content-Type": "application/x-www-form-urlencoded",
                 "Accept-Language": "fa,en;q=0.8", "Referer": "https://duckduckgo.com/"}, timeout=15,
    )
    return _decode_bytes(raw, ctype)


def _search_ddg_html(query: str, offset: int) -> list:
    text = _ddg_post("https://html.duckduckgo.com/html/", query, offset)
    if "anomaly" in text[:6000].lower() and "result__a" not in text:
        raise RuntimeError("duckduckgo asked for captcha")
    parser = _DDGParser()
    parser.feed(text)
    return _normalize_results(parser.results)


def _search_ddg_lite(query: str, offset: int) -> list:
    text = _ddg_post("https://lite.duckduckgo.com/lite/", query, offset)
    parser = _DDGParser()
    parser.feed(text)
    return _normalize_results(parser.results)


def _get_search_html(url: str) -> str:
    _, ctype, raw = _http_get(
        url,
        headers={"User-Agent": _BROWSER_UA, "Accept": "text/html,application/xhtml+xml",
                 "Accept-Language": "en-US,en;q=0.8,fa;q=0.6"},
        timeout=15,
    )
    return _decode_bytes(raw, ctype)


def _search_bing(query: str, offset: int) -> list:
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": query, "first": offset + 1, "count": GOOGLE_PAGE_SIZE, "setlang": "en"}
    )
    parser = _BingParser()
    parser.feed(_get_search_html(url))
    return _normalize_results(parser.results)


def _search_mojeek(query: str, offset: int) -> list:
    params = {"q": query}
    if offset:
        params["s"] = offset + 1
    parser = _MojeekParser()
    parser.feed(_get_search_html("https://www.mojeek.com/search?" + urllib.parse.urlencode(params)))
    return _normalize_results(parser.results)


_engine_down: dict = {}


def search_web_sync(query: str, offset: int):
    """(results, source) — تلاش به ترتیب: DuckDuckGo، Bing، Mojeek"""
    engines = [
        ("duckduckgo", _search_ddg_html),
        ("bing", _search_bing),
        ("mojeek", _search_mojeek),
        ("duckduckgo", _search_ddg_lite),
    ]
    for source, func in engines:
        if _engine_down.get(source, 0) > time.time():
            continue
        try:
            results = func(query, offset)
            if results:
                return results, source
            print(f"⚠️ جستجو ({func.__name__}) نتیجه‌ای نداد.")
        except Exception as e:
            print(f"⚠️ جستجو ({func.__name__}) fail شد: {type(e).__name__}: {e}")
            if "captcha" in str(e):
                _engine_down[source] = time.time() + 600
    return [], ""


# ── دانلود صفحه و سرو کردنش از سرور خودمون

# ── صفحه‌ی جستجوی HTML (مثل صفحه‌ی اول گوگل) + باز کردن سایت‌ها

search_tokens: dict = {}


def new_search_token(user_id: int) -> str:
    now = time.time()
    for t in [t for t, e in search_tokens.items() if e["exp"] < now]:
        search_tokens.pop(t, None)
    while len(search_tokens) >= 500:
        search_tokens.pop(min(search_tokens, key=lambda t: search_tokens[t]["exp"]), None)
    tok = secrets.token_urlsafe(12)
    search_tokens[tok] = {"uid": user_id, "exp": now + SEARCH_TOKEN_TTL, "n": 0}
    return tok


def check_search_token(tok: str, count: bool = True) -> bool:
    e = search_tokens.get(tok or "")
    if not e or e["exp"] < time.time():
        search_tokens.pop(tok or "", None)
        return False
    if count:
        e["n"] += 1
        if e["n"] > SEARCH_TOKEN_MAX_USES:
            return False
    return True


def _proxy_inject(token: str) -> str:
    return (
        "<style>#__bk{position:fixed;left:12px;bottom:12px;z-index:2147483647;background:#1a73e8;color:#fff;"
        "font:600 14px Tahoma,sans-serif;padding:10px 16px;border-radius:22px;"
        "box-shadow:0 2px 10px rgba(0,0,0,.35);cursor:pointer}</style>"
        '<script>(function(){var T="' + token + '";'
        'document.addEventListener("click",function(e){var a=e.target.closest&&e.target.closest("a");if(!a)return;'
        'var h=a.getAttribute("href");if(!h||h.charAt(0)==="#"||/^(javascript|mailto|tel):/i.test(h))return;'
        'var u=a.href;if(!/^https?:/i.test(u))return;e.preventDefault();'
        'location.href="/s/go?t="+T+"&u="+encodeURIComponent(u);},true);'
        'document.addEventListener("DOMContentLoaded",function(){var b=document.createElement("div");b.id="__bk";'
        'b.textContent="\u21a9 \u0646\u062a\u0627\u06cc\u062c";'
        'b.onclick=function(){if(history.length>1)history.back();else location.href="/s?t="+T;};'
        "document.body.appendChild(b);});})();</script>"
    )


SEARCH_PAGE_HTML = r"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>جستجو</title>
<style>
:root{--bg:#fff;--fg:#202124;--mut:#5f6368;--lnk:#1a0dab;--url:#188038;--bar:#fff;--bd:#dfe1e5;--sh:0 1px 6px rgba(32,33,36,.28)}
@media (prefers-color-scheme:dark){:root{--bg:#202124;--fg:#e8eaed;--mut:#9aa0a6;--lnk:#8ab4f8;--url:#81c995;--bar:#303134;--bd:#5f6368;--sh:0 1px 6px rgba(0,0,0,.6)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Vazirmatn,Tahoma,system-ui,sans-serif;min-height:100vh}
#top{padding:14px 12px;background:var(--bg);z-index:5}
body.home #top{margin-top:24vh;text-align:center}
body.res #top{position:sticky;top:0;box-shadow:0 1px 0 var(--bd)}
#logo{font-size:46px;font-weight:800;margin-bottom:20px;background:linear-gradient(90deg,#4285f4,#ea4335,#fbbc05,#34a853);-webkit-background-clip:text;background-clip:text;color:transparent}
body.res #logo{display:none}
#box{display:flex;align-items:center;gap:8px;max-width:640px;margin:0 auto;background:var(--bar);border:1px solid var(--bd);border-radius:26px;padding:0 14px;height:48px}
#box:focus-within{box-shadow:var(--sh);border-color:transparent}
#q{flex:1;min-width:0;border:0;outline:0;background:transparent;color:var(--fg);font-size:16px;font-family:inherit}
#x{border:0;background:transparent;color:var(--mut);font-size:18px;cursor:pointer;padding:4px}
#hint{color:var(--mut);font-size:13px;margin-top:16px}
body.res #hint{display:none}
#res{max-width:640px;margin:0 auto;padding:4px 14px 48px}
.r{display:block;padding:12px 0;text-decoration:none;color:inherit}
.d{color:var(--url);font-size:13px;direction:ltr;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.t{color:var(--lnk);font-size:18px;margin:3px 0;line-height:1.55}
.s{color:var(--mut);font-size:14px;line-height:1.8}
.msg{color:var(--mut);text-align:center;padding:36px 0}
.more{display:block;width:100%;margin:14px 0;padding:12px;border:1px solid var(--bd);border-radius:24px;background:var(--bar);color:var(--fg);font-size:15px;font-family:inherit;cursor:pointer}
</style></head>
<body class="home">
<header id="top">
<div id="logo">جستجو</div>
<form id="f" autocomplete="off"><div id="box"><span>🔎</span>
<input id="q" type="search" placeholder="جستجو کن یا آدرس سایت بنویس" enterkeyhint="search" autocapitalize="off" autocorrect="off">
<button type="button" id="x" hidden>✕</button></div></form>
<div id="hint">نتیجه رو بزن تا سایتش همین‌جا باز بشه</div>
</header>
<main id="res"></main>
<script>
var T="__TOKEN__",q=document.getElementById("q"),res=document.getElementById("res"),xb=document.getElementById("x");
var st={q:"",items:[],more:false,msg:"",busy:false};
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function go(u){location.href="/s/go?t="+T+"&u="+encodeURIComponent(u)}
function isUrl(s){return /^https?:\/\/\S+$/i.test(s)||/^[a-z0-9-]+(\.[a-z0-9-]+)+(\/\S*)?$/i.test(s)}
function save(){try{sessionStorage.setItem("s_"+T,JSON.stringify({q:st.q,items:st.items,more:st.more}))}catch(e){}}
function render(){
  var h="";
  st.items.forEach(function(r){
    h+='<a class="r" href="/s/go?t='+T+'&u='+encodeURIComponent(r.url)+'"><div class="d">'+esc(r.domain)+'</div><div class="t">'+esc(r.title)+'</div>'+(r.snippet?'<div class="s">'+esc(r.snippet)+'</div>':'')+'</a>';
  });
  if(st.msg)h+='<div class="msg">'+esc(st.msg)+'</div>';
  if(st.more&&!st.busy)h+='<button class="more" id="more">نمایش نتایج بیشتر</button>';
  res.innerHTML=h;
  document.body.className=(st.items.length||st.msg)?"res":"home";
  var m=document.getElementById("more");if(m)m.onclick=function(){search(true)};
}
async function search(more){
  if(st.busy)return;
  if(!more){
    var term=q.value.trim();if(!term)return;
    if(isUrl(term)){go(/^https?:/i.test(term)?term:"https://"+term);return}
    st={q:term,items:[],more:false,msg:"در حال جستجو…",busy:true};
  }else{st.busy=true;st.msg="در حال دریافت…";}
  render();
  try{
    var r=await fetch("/s/api?t="+T+"&q="+encodeURIComponent(st.q)+"&o="+st.items.length);
    var j=await r.json();
    if(!j.ok)throw new Error(j.error||"err");
    var seen={};st.items.forEach(function(i){seen[i.url]=1});
    var fresh=j.results.filter(function(i){return!seen[i.url]});
    st.items=st.items.concat(fresh);
    st.more=fresh.length>0;
    st.msg=st.items.length?"":"نتیجه‌ای پیدا نشد. یه عبارت دیگه امتحان کن.";
  }catch(e){
    st.msg=st.items.length?"نتیجه‌ی بیشتری نیست.":"جستجو جواب نداد؛ چند لحظه‌ی دیگه دوباره امتحان کن.";
    st.more=false;
  }
  st.busy=false;render();save();
}
document.getElementById("f").addEventListener("submit",function(e){e.preventDefault();q.blur();search(false)});
q.addEventListener("input",function(){xb.hidden=!q.value});
xb.onclick=function(){q.value="";xb.hidden=true;q.focus()};
try{var old=JSON.parse(sessionStorage.getItem("s_"+T)||"null");
  if(old&&old.items&&old.items.length){st={q:old.q,items:old.items,more:!!old.more,msg:"",busy:false};q.value=old.q;xb.hidden=!old.q;render();}}catch(e){}
</script></body></html>"""


def _msg_page(text: str, token: str = "") -> bytes:
    back = f'<p><a href="/s?t={html.escape(token, quote=True)}">↩ برگشت به جستجو</a></p>' if token else ""
    return (
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>body{font-family:Tahoma,sans-serif;padding:32px 20px;text-align:center;line-height:2}'
        'a{color:#1a73e8;font-size:18px}</style></head><body>'
        f"<p>{html.escape(text)}</p>{back}</body></html>"
    ).encode("utf-8")


async def handle_search_route(route: str, qs: dict):
    """(status, content_type, body, extra_headers)"""
    token = (qs.get("t") or [""])[0]
    nostore = "Cache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nX-Robots-Tag: noindex\r\n"
    html_type = "text/html; charset=utf-8"
    if not check_search_token(token, count=(route != "/s")):
        return "403 Forbidden", html_type, _msg_page("این لینک منقضی شده؛ دوباره از داخل ربات «گوگل» رو بزن."), nostore

    if route == "/s":
        return "200 OK", html_type, SEARCH_PAGE_HTML.replace("__TOKEN__", token).encode("utf-8"), nostore

    if route == "/s/api":
        term = ((qs.get("q") or [""])[0]).strip()[:200]
        try:
            offset = max(0, min(200, int((qs.get("o") or ["0"])[0])))
        except ValueError:
            offset = 0
        out = {"ok": False, "results": []}
        if term:
            try:
                results, _src = await run_net(search_web_sync, term, offset)
                out = {"ok": True, "results": [
                    {"url": r["url"], "title": r["title"], "snippet": _clip(r["snippet"], 220), "domain": _domain(r["url"])}
                    for r in results
                ]}
            except Exception as e:
                print(f"❌ search api exception: {type(e).__name__}: {e}")
                out["error"] = "fail"
        return "200 OK", "application/json; charset=utf-8", json.dumps(out, ensure_ascii=False).encode("utf-8"), nostore

    if route == "/s/go":
        url = ((qs.get("u") or [""])[0]).strip()
        if not url.lower().startswith(("http://", "https://")):
            return "400 Bad Request", html_type, _msg_page("آدرس معتبر نیست.", token), nostore
        try:
            _final, _title, body = await run_net(fetch_page_sync, url, token)
            return "200 OK", html_type, body, nostore
        except (ValueError, urllib.error.URLError) as e:
            reason = "این آدرس مجاز نیست." if "unsafe" in str(e).lower() else "این صفحه HTML نبود یا خیلی بزرگه."
            return "200 OK", html_type, _msg_page("⚠️ " + reason, token), nostore
        except Exception as e:
            print(f"❌ proxy fetch exception: {type(e).__name__}: {e}")
            return "200 OK", html_type, _msg_page("⚠️ نتونستم صفحه رو باز کنم (سایت جواب نداد).", token), nostore

    return "404 Not Found", html_type, _msg_page("پیدا نشد."), nostore


def prepare_html(text: str, base_url: str, token: str = "") -> str:
    base_tag = f'<base href="{html.escape(base_url, quote=True)}">'
    extras = '<meta charset="utf-8">'
    if not re.search(r"<meta[^>]+name=[\"']viewport", text, re.I):
        extras += '<meta name="viewport" content="width=device-width, initial-scale=1">'
    inject = extras + base_tag + (_proxy_inject(token) if token else "")
    m = re.search(r"<head[^>]*>", text, re.I)
    if m:
        return text[:m.end()] + inject + text[m.end():]
    m = re.search(r"<html[^>]*>", text, re.I)
    if m:
        return text[:m.end()] + "<head>" + inject + "</head>" + text[m.end():]
    return "<!doctype html><html><head>" + inject + "</head><body>" + text + "</body></html>"


def fetch_page_sync(url: str, token: str = ""):
    """(final_url, title, html_bytes)"""
    final_url, ctype, raw = _http_get(
        url,
        headers={"User-Agent": _BROWSER_UA, "Accept": "text/html,application/xhtml+xml",
                 "Accept-Language": "fa,en;q=0.8", "Accept-Encoding": "identity"},
        timeout=15, max_bytes=MAX_PAGE_BYTES, safe=True,
    )
    low = (ctype or "").lower()
    if "html" not in low and "xml" not in low:
        raise ValueError("not html")
    text = _decode_bytes(raw, ctype)
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = _clean_text(m.group(1)) if m else ""
    return final_url, title, prepare_html(text, final_url, token).encode("utf-8")


def cache_page(body: bytes) -> str:
    now = time.time()
    for token in [t for t, e in page_cache.items() if e["exp"] < now]:
        page_cache.pop(token, None)
    while len(page_cache) >= PAGE_CACHE_MAX:
        oldest = min(page_cache, key=lambda t: page_cache[t]["exp"])
        page_cache.pop(oldest, None)
    token = secrets.token_urlsafe(16)
    page_cache[token] = {"body": body, "exp": now + PAGE_TTL}
    return token


def get_cached_page(token: str):
    entry = page_cache.get(token)
    if not entry:
        return None
    if entry["exp"] < time.time():
        page_cache.pop(token, None)
        return None
    return entry["body"]


def page_url(token: str) -> str:
    return PING_URL.rstrip("/") + "/p/" + token


# ── متن‌ها و کیبوردهای گوگل

def _clip(text: str, limit: int) -> str:
    text = _clean_text(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _domain(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def format_results(query: str, results: list, first_index: int, source: str) -> str:
    lines = [f"🔎 نتایج «{_clip(query, 60)}»", POST_DIVIDER]
    for i, r in enumerate(results):
        block = f"{fa(first_index + i)} ┊ {_clip(r['title'], 90)}\n🌐 {_domain(r['url'])}"
        snippet = _clip(r["snippet"], 140)
        if snippet:
            block += f"\n{snippet}"
        lines.append(block)
        lines.append(POST_DIVIDER)
    lines.append("👇 شماره‌ی نتیجه رو بزن تا صفحه‌ش همین‌جا باز بشه، یا «بیشتر» رو بزن.")
    return "\n".join(lines)


def kb_google_prompt():
    return {"keyboard": [[{"text": BTN_G_EXIT}]], "resize_keyboard": True}


def kb_google_results(first: int, last: int):
    nums = [{"text": fa(i)} for i in range(first, last + 1)]
    rows = [nums[i:i + 5] for i in range(0, len(nums), 5)]
    rows.append([{"text": BTN_G_MORE}])
    rows.append([{"text": BTN_G_NEW}, {"text": BTN_G_EXIT}])
    return {"keyboard": rows, "resize_keyboard": True}


async def send_with_kb(chat_id: int, text: str, kb: dict):
    chunks = split_text(text)
    for chunk in chunks[:-1]:
        await plain_send(chat_id, chunk)
    await plain_send(chat_id, chunks[-1], reply_markup=kb)


async def run_net(func, *args):
    async with _net_sem:
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


def _google_wait(user_id: int) -> int:
    if user_id == ADMIN_ID:
        return 0
    wait = GOOGLE_COOLDOWN - (time.monotonic() - last_google.get(user_id, -10 ** 9))
    if wait > 0:
        return int(wait) + 1
    last_google[user_id] = time.monotonic()
    return 0


def parse_result_number(text: str):
    t = text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    m = re.fullmatch(r"(?:نتیجه\s*)?(\d{1,3})", t)
    return int(m.group(1)) if m else None


def _is_menu_button(text: str) -> bool:
    return bool(
        label_to_key(text) or label_to_key(text, enabled=False)
        or text in (BTN_SWITCH, BTN_HELP, BTN_SEARCH, BTN_GOOGLE, BTN_DL, BTN_ADMIN)
    )


def txt_google_prompt() -> str:
    return "🌐 متن مورد نظرت رو بفرست تا جستجو کنم:"


def txt_google_disabled() -> str:
    return "🌐 گوگل فعلاً غیرفعاله."


async def google_search(user_id: int, chat_id: int, query: str):
    st = google_state.get(user_id)
    if st is None:
        return
    wait = _google_wait(user_id)
    if wait:
        await plain_send(chat_id, f"⏳ {fa(wait)} ثانیه‌ی دیگه دوباره امتحان کن.", reply_markup=kb_google_prompt())
        return
    await plain_send(chat_id, "⏳ دارم می‌گردم...")
    try:
        results, source = await run_net(search_web_sync, query, 0)
    except Exception as e:
        print(f"❌ google_search exception: {type(e).__name__}: {e}")
        results, source = [], ""
    if not results:
        st.update(mode="query", results=[])
        await plain_send(chat_id, "📭 نتیجه‌ای پیدا نشد. یه متن دیگه بفرست یا از گوگل خارج شو.", reply_markup=kb_google_prompt())
        return
    st.update(mode="results", query=query, results=results, source=source, first=1, last=len(results))
    await send_with_kb(chat_id, format_results(query, results, 1, source), kb_google_results(1, len(results)))


async def google_more(user_id: int, chat_id: int):
    st = google_state.get(user_id)
    if not st or st.get("mode") != "results":
        return
    wait = _google_wait(user_id)
    if wait:
        await plain_send(chat_id, f"⏳ {fa(wait)} ثانیه‌ی دیگه دوباره امتحان کن.", reply_markup=kb_google_results(st["first"], st["last"]))
        return
    known = {r["url"] for r in st["results"]}
    try:
        results, source = await run_net(search_web_sync, st["query"], len(st["results"]))
    except Exception as e:
        print(f"❌ google_more exception: {type(e).__name__}: {e}")
        results, source = [], ""
    results = [r for r in results if r["url"] not in known]
    if not results:
        await plain_send(chat_id, "📭 نتیجه‌ی بیشتری پیدا نشد.", reply_markup=kb_google_results(st["first"], st["last"]))
        return
    first = len(st["results"]) + 1
    st["results"].extend(results)
    st.update(first=first, last=len(st["results"]), source=source)
    await send_with_kb(chat_id, format_results(st["query"], results, first, source), kb_google_results(first, st["last"]))


async def send_page_card(chat_id: int, text: str, url: str, label: str = ""):
    label = label or BTN_OPEN_PAGE
    markups = []
    if OPEN_PAGE_AS_WEBAPP:
        markups.append({"inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]})
    markups.append({"inline_keyboard": [[{"text": label, "url": url}]]})
    for markup in markups:
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
            return
        except Exception as e:
            print(f"⚠️ ارسال دکمه‌ی صفحه fail شد: {type(e).__name__}: {e}")
    await plain_send(chat_id, text + "\n\n" + url)


async def send_search_card(chat_id: int, user_id: int):
    url = PING_URL.rstrip("/") + "/s?t=" + new_search_token(user_id)
    card = (
        "🌐 صفحه‌ی جستجو آماده‌ست\n" + POST_DIVIDER + "\n"
        "دکمه‌ی پایین رو بزن؛ یه صفحه‌ی جستجو مثل گوگل باز میشه. هر چی خواستی بنویس، نتیجه‌ها همون‌جا میاد و با زدن روی هر کدوم سایتش باز میشه.\n"
        f"⏱ این لینک {fa(SEARCH_TOKEN_TTL // 3600)} ساعت معتبره."
    )
    await send_page_card(chat_id, card, url, BTN_OPEN_SEARCH)


async def google_open(user_id: int, chat_id: int, number: int):
    st = google_state.get(user_id)
    if not st or st.get("mode") != "results":
        return
    results = st["results"]
    if not 1 <= number <= len(results):
        await plain_send(chat_id, f"⚠️ نتیجه‌ای با شماره‌ی {fa(number)} نیست (۱ تا {fa(len(results))}).",
                         reply_markup=kb_google_results(st["first"], st["last"]))
        return
    if not PING_URL:
        await plain_send(chat_id, "⚠️ آدرس عمومی سرویس تنظیم نشده (RENDER_EXTERNAL_URL)؛ نمیشه صفحه رو باز کرد.")
        return
    item = results[number - 1]
    await plain_send(chat_id, f"⏳ دارم صفحه‌ی نتیجه‌ی {fa(number)} رو دانلود می‌کنم...")
    try:
        final_url, title, body = await run_net(fetch_page_sync, item["url"])
    except (ValueError, urllib.error.URLError) as e:
        reason = "این آدرس مجاز نیست." if "unsafe" in str(e).lower() else "صفحه HTML نبود یا خیلی بزرگه."
        await plain_send(chat_id, f"⚠️ {reason}", reply_markup=kb_google_results(st["first"], st["last"]))
        return
    except Exception as e:
        print(f"❌ fetch_page exception: {type(e).__name__}: {e}")
        await plain_send(chat_id, "⚠️ نتونستم صفحه رو دانلود کنم (سایت جواب نداد).",
                         reply_markup=kb_google_results(st["first"], st["last"]))
        return
    token = cache_page(body)
    card = (
        f"🌐 {_clip(title or item['title'], 80)}\n"
        f"{_domain(final_url)}\n{POST_DIVIDER}\n"
        f"✅ صفحه آماده‌ست؛ دکمه‌ی پایین رو بزن تا همین‌جا باز بشه.\n"
        f"⏱ این صفحه {fa(PAGE_TTL // 60)} دقیقه معتبره."
    )
    await send_page_card(chat_id, card, page_url(token))


async def google_handle(text: str, chat_id: int, user_id: int) -> bool:
    st = google_state[user_id]
    if _is_menu_button(text):
        google_state.pop(user_id, None)
        return False
    if text == BTN_G_EXIT:
        google_state.pop(user_id, None)
        await safe_send(chat_id=chat_id, text=txt_pick_channel(), reply_markup=kb_user_menu(user_id))
        return True
    if text == BTN_G_NEW:
        st.update(mode="query", results=[])
        await plain_send(chat_id, txt_google_prompt(), reply_markup=kb_google_prompt())
        return True
    if text == BTN_G_MORE:
        if st.get("mode") == "results":
            spawn(google_more(user_id, chat_id))
        else:
            await plain_send(chat_id, txt_google_prompt(), reply_markup=kb_google_prompt())
        return True
    number = parse_result_number(text)
    if st.get("mode") == "results" and number is not None:
        spawn(google_open(user_id, chat_id, number))
        return True
    spawn(google_search(user_id, chat_id, text[:200]))
    return True


# ───────────────────────── دانلود فایل از لینک و آپلود برای کاربر ─────────────────────────

_dl_sem = asyncio.Semaphore(2)
URL_FIND_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


class DownloadTooBig(Exception):
    def __init__(self, size: int):
        super().__init__(f"too big: {size}")
        self.size = size


def _filename_from_response(headers, url: str) -> str:
    cd = headers.get("Content-Disposition", "") or ""
    name = None
    m = re.search(r"filename\*\s*=\s*[\w\-]+'[^']*'([^;]+)", cd, re.I)
    if m:
        name = urllib.parse.unquote(m.group(1).strip().strip('"'))
    if not name:
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
        if m:
            name = m.group(1).strip()
    if not name:
        name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").strip(" .")
    if not name:
        name = "file"
    if "." not in name:
        try:
            ext = mimetypes.guess_extension(headers.get_content_type() or "") or ""
        except Exception:
            ext = ""
        name += ext
    return name[:120]


def download_file_sync(url: str, dest_dir: str, limit_bytes):
    """(path, filename, size) — استریم روی دیسک؛ limit_bytes=None یعنی بدون محدودیت"""
    if not _is_safe_url(url):
        raise ValueError("unsafe url")
    req = urllib.request.Request(
        url, headers={"User-Agent": _BROWSER_UA, "Accept": "*/*", "Accept-Encoding": "identity"}
    )
    deadline = time.monotonic() + DOWNLOAD_MAX_SECONDS
    with _make_safe_opener().open(req, timeout=20) as resp:
        length = resp.headers.get("Content-Length", "")
        if limit_bytes and length.isdigit() and int(length) > limit_bytes:
            raise DownloadTooBig(int(length))
        name = _filename_from_response(resp.headers, resp.geturl())
        path = os.path.join(dest_dir, name)
        total = 0
        with open(path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if limit_bytes and total > limit_bytes:
                    raise DownloadTooBig(total)
                if time.monotonic() > deadline:
                    raise TimeoutError("download too slow")
                f.write(chunk)
    if total == 0:
        raise ValueError("empty file")
    return path, name, total


async def plain_send_document(chat_id: int, path: str, caption: str = ""):
    try:
        with open(path, "rb") as doc_file:
            return await bot.send_document(chat_id=chat_id, document=doc_file, caption=caption)
    except Exception as e:
        print(f"❌ send_document failed: {type(e).__name__}: {e}")
        return None


def fmt_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{fa(round(num_bytes / (1024 * 1024), 1))} مگابایت"
    return f"{fa(max(1, round(num_bytes / 1024)))} کیلوبایت"


def txt_dl_prompt(user_id: int) -> str:
    limit = ""
    if user_id != ADMIN_ID:
        limit = f"\nحداکثر حجم: {fmt_mb(settings.get('max_file_mb'))} مگابایت"
    return f"📥 لینک مستقیم فایل (http/https) رو بفرست تا دانلود و برات آپلود کنم.{limit}"


def txt_dl_disabled() -> str:
    return "📥 دانلود فایل فعلاً غیرفعاله."


def kb_dl_cancel():
    return {"keyboard": [[{"text": BTN_DL_CANCEL}]], "resize_keyboard": True}


async def run_download(user_id: int, chat_id: int, url: str):
    def retry_state():
        dl_state[user_id] = True

    if user_id in downloading:
        await plain_send(chat_id, "⏳ یه دانلود دیگه‌ت در حال انجامه؛ صبر کن تموم بشه.", reply_markup=kb_user_menu(user_id))
        return
    if user_id != ADMIN_ID:
        wait = DOWNLOAD_COOLDOWN - (time.monotonic() - last_dl.get(user_id, -10 ** 9))
        if wait > 0:
            retry_state()
            await plain_send(chat_id, f"⏳ {fa(int(wait) + 1)} ثانیه‌ی دیگه دوباره امتحان کن.", reply_markup=kb_dl_cancel())
            return
        last_dl[user_id] = time.monotonic()

    downloading.add(user_id)
    tmp_dir = tempfile.mkdtemp(prefix="dl_", dir=MEDIA_DIR)
    try:
        await plain_send(chat_id, "⏳ دارم فایل رو دانلود می‌کنم...")
        limit = None if user_id == ADMIN_ID else get_max_file_bytes()
        try:
            async with _dl_sem:
                path, name, size = await asyncio.get_running_loop().run_in_executor(
                    None, download_file_sync, url, tmp_dir, limit
                )
        except DownloadTooBig as e:
            retry_state()
            await plain_send(
                chat_id,
                f"⚠️ حجم فایل بیشتر از حد مجازه ({fmt_size(e.size)} در برابر {fmt_mb(settings.get('max_file_mb'))} مگابایت).",
                reply_markup=kb_dl_cancel(),
            )
            return
        except urllib.error.HTTPError as e:
            retry_state()
            await plain_send(chat_id, f"⚠️ سرور فایل خطا داد (کد {fa(e.code)}).", reply_markup=kb_dl_cancel())
            return
        except (ValueError, urllib.error.URLError, OSError) as e:
            retry_state()
            msg = "⚠️ این آدرس مجاز نیست." if "unsafe" in str(e).lower() else "⚠️ نتونستم فایل رو دانلود کنم (لینک مستقیم نیست یا سرور جواب نداد)."
            await plain_send(chat_id, msg, reply_markup=kb_dl_cancel())
            return
        except Exception as e:
            print(f"❌ download exception: {type(e).__name__}: {e}")
            retry_state()
            await plain_send(chat_id, "⚠️ دانلود ناموفق بود.", reply_markup=kb_dl_cancel())
            return

        await plain_send(chat_id, f"📤 دارم آپلود می‌کنم... ({fmt_size(size)})")
        sent = await plain_send_document(chat_id, path, caption=name)
        if sent is None:
            await plain_send(chat_id, "⚠️ آپلود فایل ناموفق بود (شاید حجمش برای سروش زیاده).", reply_markup=kb_user_menu(user_id))
        else:
            await plain_send(chat_id, "✅ فایل ارسال شد.", reply_markup=kb_user_menu(user_id))
    finally:
        downloading.discard(user_id)
        shutil.rmtree(tmp_dir, ignore_errors=True)


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

    if text == BTN_DL:
        if not (settings.get("download_enabled") or user_id == ADMIN_ID):
            await safe_send(chat_id=chat_id, text=txt_dl_disabled(), reply_markup=kb_user_menu(user_id))
            return
        _clear_modes(user_id)
        dl_state[user_id] = True
        await plain_send(chat_id, txt_dl_prompt(user_id), reply_markup=kb_dl_cancel())
        return

    if text == BTN_GOOGLE:
        if not (settings.get("google_enabled") or user_id == ADMIN_ID):
            await safe_send(chat_id=chat_id, text=txt_google_disabled(), reply_markup=kb_user_menu(user_id))
            return
        _clear_modes(user_id)
        google_state[user_id] = {"mode": "query", "query": "", "results": [], "first": 1, "last": 0, "source": ""}
        if PING_URL:
            await send_search_card(chat_id, user_id)
            await plain_send(chat_id, "یا همین‌جا تو چت متنت رو بفرست تا نتایج رو برات بیارم 👇", reply_markup=kb_google_prompt())
        else:
            await plain_send(chat_id, txt_google_prompt(), reply_markup=kb_google_prompt())
        return

    if text == BTN_SEARCH:
        _clear_modes(user_id)
        if not (settings.get("search_enabled") or user_id == ADMIN_ID):
            await safe_send(chat_id=chat_id, text=txt_search_disabled(), reply_markup=kb_user_menu(user_id))
            return
        search_state[user_id] = True
        await plain_send(chat_id, txt_search_prompt(), reply_markup=kb_search_cancel())
        return

    if user_id in dl_state:
        if text == BTN_DL_CANCEL:
            dl_state.pop(user_id, None)
            await safe_send(chat_id=chat_id, text=txt_pick_channel(), reply_markup=kb_user_menu(user_id))
            return
        if _is_menu_button(text):
            dl_state.pop(user_id, None)
        else:
            found = URL_FIND_RE.search(text)
            if found:
                dl_state.pop(user_id, None)
                spawn(run_download(user_id, chat_id, found.group(0).rstrip(".,;)")))
            else:
                await plain_send(chat_id, "⚠️ لینک http یا https بفرست، یا «لغو دانلود» رو بزن.", reply_markup=kb_dl_cancel())
            return

    if user_id in google_state:
        if await google_handle(text, chat_id, user_id):
            return

    if user_id in search_state:
        if text == BTN_SEARCH_CANCEL:
            search_state.pop(user_id, None)
            await safe_send(chat_id=chat_id, text=txt_pick_channel(), reply_markup=kb_user_menu(user_id))
            return
        match = USERNAME_RE.fullmatch(text)
        if match:
            search_state.pop(user_id, None)
            spawn(run_search(user_id, chat_id, match.group(1)))
            return
        if label_to_key(text) or label_to_key(text, enabled=False) or text in (BTN_SWITCH, BTN_HELP):
            search_state.pop(user_id, None)
        else:
            await plain_send(chat_id, "⚠️ فرمت درست نیست. یوزرنیم رو مثل @username بفرست یا «انصراف» رو بزن.", reply_markup=kb_search_cancel())
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
        data = await asyncio.wait_for(reader.read(16384), timeout=5)
    except Exception:
        data = b""
    first = data.split(b"\r\n", 1)[0].decode("latin-1", errors="ignore")
    parts = first.split(" ")
    method = parts[0] if parts else "GET"
    path = parts[1] if len(parts) > 1 else "/"

    status, ctype, body, extra = "200 OK", "text/plain; charset=utf-8", b"OK", ""
    route = path.split("?")[0].split("#")[0]
    if route in ("/s", "/s/api", "/s/go"):
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        try:
            status, ctype, body, extra = await handle_search_route(route, qs)
        except Exception as e:
            print(f"❌ search route exception: {type(e).__name__}: {e}")
            status, body = "500 Internal Server Error", "خطا".encode("utf-8")
    elif path.startswith("/p/"):
        token = path[3:].split("?")[0].split("#")[0]
        page = get_cached_page(token)
        if page is not None:
            ctype = "text/html; charset=utf-8"
            body = page
            extra = "Cache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nX-Robots-Tag: noindex\r\n"
        else:
            status = "404 Not Found"
            body = "صفحه پیدا نشد یا منقضی شده.".encode("utf-8")

    head = (
        f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
        f"{extra}Connection: close\r\n\r\n"
    ).encode("utf-8")
    try:
        writer.write(head if method == "HEAD" else head + body)
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
    await seed_channels()

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
