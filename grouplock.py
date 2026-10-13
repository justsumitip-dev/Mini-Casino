"""Group control (bina ui/aiogram-router ke, taaki ui.py isse import kar sake).

1. APPROVED GROUPS: bot sirf un groups me chalta hai jo admin ne allow kiye ho.
     - Admin bot ko group me add kare  -> group apne aap allow ho jata hai
     - ya group me admin /allow bheje  (/disallow se band)
     - baaki sab groups me bot chup rehta hai. Private chat (DM) hamesha chalta hai.
2. OWNER LOCK: group me jo user command (/play, /mines, /profile ...) bhejta hai, bot ka wo message
   (aur uske saare buttons) sirf usi ke hain. Dusra user button dabaye to alert aata hai ki apna command bhejo.
"""
import time
from contextvars import ContextVar

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from database import db

db("CREATE TABLE IF NOT EXISTS allowed_groups(chat_id INTEGER PRIMARY KEY, title TEXT, ts INTEGER)")
db("CREATE TABLE IF NOT EXISTS msg_owner(chat_id INTEGER, mid INTEGER, uid INTEGER, ts INTEGER, PRIMARY KEY(chat_id, mid))")

GROUP_TYPES = ("group", "supergroup")
cur_user = ContextVar("cur_user", default=None)   # abhi jis user ka update chal raha hai
_allowed = {r["chat_id"] for r in db("SELECT chat_id FROM allowed_groups", fetch="all")}
_PUBLIC_CB = ("noop", "fair:")                    # ye buttons koi bhi dabaye to chalega
_last_clean = [0]


# ───────────── approved groups ─────────────
def is_allowed(chat_id):
    return chat_id in _allowed


def allow(chat_id, title=""):
    _allowed.add(chat_id)
    db("INSERT INTO allowed_groups VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
       (chat_id, (title or "")[:80], int(time.time())))


def disallow(chat_id):
    _allowed.discard(chat_id)
    db("DELETE FROM allowed_groups WHERE chat_id=?", (chat_id,))


def groups():
    return db("SELECT chat_id,title FROM allowed_groups ORDER BY ts DESC", fetch="all")


# ───────────── message owner ─────────────
def note(chat_id, result):
    """ui.py: group me bheje gaye har naye message ka owner = jiska update chal raha hai."""
    uid = cur_user.get()
    if uid is None or chat_id >= 0 or not isinstance(result, dict):
        return
    mid = result.get("message_id")
    if not mid:
        return
    try:
        db("INSERT OR REPLACE INTO msg_owner VALUES(?,?,?,?)", (chat_id, mid, uid, int(time.time())))
        now = time.time()
        if now - _last_clean[0] > 3600:   # purane records saaf (7 din)
            _last_clean[0] = now
            db("DELETE FROM msg_owner WHERE ts<?", (int(now) - 7 * 86400,))
    except Exception:
        pass


def owner_of(msg):
    r = db("SELECT uid FROM msg_owner WHERE chat_id=? AND mid=?", (msg.chat.id, msg.message_id), "one")
    if r:
        return r["uid"]
    rep = getattr(msg, "reply_to_message", None)   # fallback: bot ne command ka reply kiya tha
    u = getattr(rep, "from_user", None)
    return u.id if u and not u.is_bot else None


def _cmd(m: Message):
    t = (m.text or "").split(maxsplit=1)
    return t[0][1:].split("@")[0].lower() if t and t[0].startswith("/") else ""


class GroupMW(BaseMiddleware):
    """Outer middleware (dp.message / dp.callback_query): approved-group check + owner lock."""

    async def __call__(self, handler, event, data):
        chat = event.chat if isinstance(event, Message) else (event.message.chat if event.message else None)
        u = event.from_user
        if chat is not None and chat.type in GROUP_TYPES and u is not None:
            if not is_allowed(chat.id):
                if isinstance(event, Message) and u.id in ADMIN_IDS and _cmd(event) in ("allow", "disallow"):
                    pass  # admin group ko approve kar sakta hai
                else:
                    if isinstance(event, CallbackQuery):
                        try:
                            await event.answer()
                        except Exception:
                            pass
                    return
            elif isinstance(event, CallbackQuery) and not (event.data or "").startswith(_PUBLIC_CB):
                owner = owner_of(event.message)
                if owner and owner != u.id:
                    try:
                        await event.answer("🚫 This isn't your game/menu.\nSend the command yourself to play "
                                           "(e.g. /play, /mines).", show_alert=True)
                    except Exception:
                        pass
                    return
        tok = cur_user.set(u.id if u else None)
        try:
            return await handler(event, data)
        finally:
            cur_user.reset(tok)
