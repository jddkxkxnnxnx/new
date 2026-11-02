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
    "azad":  {"label": "🕊 ایران آزاد ⭐ بهتر و صحیح‌تر", "username": "IraneAzad_News", "title": "ایران آزاد",       "icon": "🕊"},
    "inter": {"label": "📺 ایران اینترنشنال",              "username": "IranintlTV",     "title": "ایران اینترنشنال", "icon": "📺"},
}
LABEL_TO_KEY = {c["label"]: key for key, c in CHANNELS.items()}

BTN_SWITCH = "🔁 تغییر کانال"
BTN_HELP = "❕ راهنما"

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


def compose_post(header: str, body: str) -> str:
    body = (body or "").strip()
    if not body:
        return header
    return f"{header}\n{POST_DIVIDER}\n{body}"


# ───────────────────────── ذخیره‌ی وضعیت کاربرها ─────────────────────────

def parse_users(raw) -> dict:
    result = {}
    if not isinstance(raw, dict):
        return result
    for key, val in raw.items():
        try:
            if val.get("channel") in CHANNELS:
                result[int(key)] = {
                    "chat_id": int(val["chat_id"]),
                    "channel": val["channel"],
                    "last_id": int(val.get("last_id", 0)),
                }
        except Exception:
            continue
    return result


def load_users() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ خوندن فایل وضعیت نشد: {type(e).__name__}: {e}")
        return {}
    return parse_users(raw)


users: dict = load_users()
user_gen: dict = {}
user_locks: dict = {}
_tasks: set = set()


_state_dirty = False
_state_msg_id = None


def _write_state_file():
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in users.items()}, f, ensure_ascii=False)
    os.replace(tmp_path, STATE_FILE)


def save_users():
    global _state_dirty
    try:
        _write_state_file()
        _state_dirty = True
    except Exception as e:
        print(f"⚠️ ذخیره‌ی فایل وضعیت نشد: {type(e).__name__}: {e}")


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
                if not users:
                    data = await tg_client.download_media(m, file=bytes)
                    restored = parse_users(json.loads(data.decode("utf-8")))
                    users.update(restored)
                    _write_state_file()
                    print(f"♻️ وضعیت {len(restored)} کاربر از Saved Messages برگشت.")
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


async def fetch_recent(ckey: str):
    messages = await _scan(CHANNELS[ckey]["username"], RECENT_SCAN_LIMIT)
    newest_id = max((m.id for m in messages), default=0)
    posts = build_posts(messages, ckey)[-POST_COUNT:]
    return posts, newest_id


async def fetch_since(ckey: str, after_id: int):
    messages = await _scan(CHANNELS[ckey]["username"], NEW_SCAN_LIMIT, min_id=after_id)
    newest_id = max((m.id for m in messages), default=after_id)
    posts = build_posts(messages, ckey)
    return posts, newest_id


# ───────────────────────── ارسال پست‌ها به کاربر ─────────────────────────

async def send_post(chat_id: int, post: Post):
    body = post.text
    full = compose_post(post.header, body)

    if post.kind in ("photo", "video"):
        path = await post.media_path()
        if path:
            if len(full) <= CAPTION_LIMIT:
                caption, rest = full, ""
            else:
                caption, rest = post.header, body
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
            full = compose_post(post.header, body)

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

def kb_channel_menu():
    return {
        "keyboard": [[{"text": c["label"]}] for c in CHANNELS.values()],
        "resize_keyboard": True,
    }


def kb_chat_menu():
    return {
        "keyboard": [[{"text": BTN_SWITCH}, {"text": BTN_HELP}]],
        "resize_keyboard": True,
    }


def txt_wait_note() -> str:
    return (
        "⏱ اخبار جدید تا ۵ دقیقه‌ی بعد ارسال میشه، اگه باشه 🔔\n"
        "اگه نبود هم بهت میگم نبود؛ نگران نباش، صبر می‌کنم ببینم پست گذاشتن یا نه 🙂"
    )


def txt_welcome(name: str) -> str:
    safe_name = escape_markdown(name)
    return f"""✨ *اخبار ایران* ✨
{POST_DIVIDER}
سلام {safe_name} 👋
یه کانال انتخاب کن تا {fa(POST_COUNT)} پست آخرش رو بگیری؛ بعدش هر ۵ دقیقه خبرهای تازه خودکار میاد 🔔

🕊 *ایران آزاد* ⭐ پیشنهادی، اخبارش صحیح‌تره
📺 *ایران اینترنشنال*
{POST_DIVIDER}
⏱ خبر جدید تا ۵ دقیقه‌ی بعد ارسال میشه؛ اگه نبود هم بهت میگم، نگران نباش صبر می‌کنم 🙂

👇 یکی رو بزن"""


def txt_pick_channel() -> str:
    return "🔽 لطفاً از دکمه‌های پایین یکی از کانال‌ها رو انتخاب کن"


def txt_loading(title: str) -> str:
    return f"""┏━━━━━━━━━━━━━━━━━━┓
   ✅ *کانال فعال: {title}*
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
    return f"""❕ 《 *راهنمای استفاده* 》
{DIVIDER}
1️⃣  یکی از دو کانال رو انتخاب کن (ایران آزاد یا ایران اینترنشنال)
2️⃣  {fa(POST_COUNT)} پست آخر همون لحظه برات فرستاده میشه
3️⃣  بعدش هر ۵ دقیقه چک می‌کنم و اگه خبر جدید بود خودکار برات می‌فرستم

🔁 هر وقت خواستی با دکمه‌ی «تغییر کانال» بین کانال‌ها سوییچ کن؛ با سوییچ، {fa(POST_COUNT)} پست آخر کانال جدید هم فرستاده میشه.
⭐ ایران آزاد اخبارش صحیح‌تره و پیشنهاد ما همونه."""


# ───────────────────────── انتخاب و سوییچ کانال ─────────────────────────

async def start_channel(user_id: int, chat_id: int, ckey: str):
    gen = bump_gen(user_id)
    info = CHANNELS[ckey]
    await safe_send(chat_id=chat_id, text=txt_loading(info["title"]), reply_markup=kb_chat_menu())

    posts = []
    async with get_lock(user_id):
        if user_gen.get(user_id) != gen:
            return
        try:
            posts, newest_id = await fetch_recent(ckey)
        except Exception as e:
            print(f"❌ fetch_recent exception: {type(e).__name__}: {e}")
            traceback.print_exc()
            await safe_send(chat_id=chat_id, text=txt_fetch_error(), reply_markup=kb_chat_menu())
            return

        users[user_id] = {"chat_id": chat_id, "channel": ckey, "last_id": newest_id}
        save_users()

        try:
            if not posts:
                await safe_send(chat_id=chat_id, text=txt_no_posts())
            else:
                await deliver_posts(chat_id, posts, user_id, gen)
        finally:
            cleanup_posts(posts)

        if user_gen.get(user_id) == gen:
            await safe_send(chat_id=chat_id, text=txt_wait_note(), reply_markup=kb_chat_menu())


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
                save_users()
            if SHOW_NO_NEWS_NOTICE:
                await safe_send(chat_id=chat_id, text=txt_no_news())
            return

        ok = await deliver_posts(chat_id, fresh, user_id, gen)
        if ok:
            state["last_id"] = max(state["last_id"], newest_id)
            save_users()


async def check_all():
    by_channel: dict = {}
    for user_id, state in list(users.items()):
        by_channel.setdefault(state["channel"], []).append((user_id, user_gen.get(user_id, 0)))

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


# ───────────────────────── هندلرهای ربات ─────────────────────────

@bot.on(Filters.command("start"))
async def start_handler(update: Update):
    message = update.message
    user = message.from_user
    name = user.first_name or "دوست من"
    await safe_send(chat_id=message.chat.id, text=txt_welcome(name), reply_markup=kb_channel_menu())


@bot.on(Filters.command("help"))
async def help_handler(update: Update):
    user_id = update.message.from_user.id
    kb = kb_chat_menu() if user_id in users else kb_channel_menu()
    await safe_send(chat_id=update.message.chat.id, text=txt_help(), reply_markup=kb)


@bot.on(Filters.text)
async def text_handler(update: Update):
    message = update.message
    text = (message.text or "").strip()
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not text or text.startswith("/"):
        return

    if text in LABEL_TO_KEY:
        spawn(start_channel(user_id, chat_id, LABEL_TO_KEY[text]))
        return

    if text == BTN_SWITCH:
        await safe_send(chat_id=chat_id, text=txt_pick_channel(), reply_markup=kb_channel_menu())
        return

    if text == BTN_HELP:
        kb = kb_chat_menu() if user_id in users else kb_channel_menu()
        await safe_send(chat_id=chat_id, text=txt_help(), reply_markup=kb)
        return

    kb = kb_chat_menu() if user_id in users else kb_channel_menu()
    await safe_send(chat_id=chat_id, text=txt_pick_channel(), reply_markup=kb)


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
