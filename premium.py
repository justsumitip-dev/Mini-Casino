"""Premium (custom) emoji support.

Admin panel me har normal emoji ke liye ek premium emoji ID set hoti hai (table: emoji_map).
Bot ke saare Screen messages / captions / buttons bhejte waqt ui.py yahin se normal emoji ko
premium emoji se badal deta hai. Koi slot khali ho to wahan normal emoji hi dikhta hai.

  html(text)  -> HTML text me emoji ko <tg-emoji emoji-id="..">emoji</tg-emoji> bana do
  lead(text)  -> button text ka pehla emoji alag nikaalo (icon_custom_emoji_id ke liye)
"""
import re
from contextvars import ContextVar

from database import db

db("CREATE TABLE IF NOT EXISTS emoji_map(emoji TEXT PRIMARY KEY, cid TEXT)")

# (emoji, kahan use hota hai) - admin panel me isi order me dikhte hain
EMOJIS = [
    # status / result
    ("❌", "Error, cancel, loss"), ("✅", "Success, selected tick, win"), ("➖", "Draw, Deduct button"),
    ("➕", "Add Link / Add Balance"), ("⚠️", "DM warning"), ("⏳", "Active game warning"),
    ("⌛", "Match timeout"), ("🚫", "Banned, Ban button"), ("🆕", "New user"),
    ("🎉", "Referral joined"), ("✨", "Welcome text"),
    # navigation / buttons
    ("⬅️", "Back button"), ("▶️", "Start Game / Match"), ("🔁", "Play Again"), ("✖️", "Double button"),
    ("✏️", "Custom bet / Rename / Edit"), ("🗑", "Remove link"), ("🔍", "Verify Fairness"),
    ("🔎", "User search"), ("👁", "Preview card"), ("👇", "Join us (Community)"),
    # games
    ("🎲", "Dice title / button"), ("💣", "Mines title / mine"), ("💎", "Mines safe tile"),
    ("💥", "Blast tile"), ("▫️", "Mines opened empty"), ("⬜", "Mines closed tile"),
    ("🗼", "Tower title"), ("🌴", "Tower safe tile"), ("🏝", "Tower empty tile"),
    ("💀", "Tower lost tile"), ("❓", "Tower unopened tile"), ("🟢", "Easy / ON"),
    ("🟡", "Medium"), ("🔴", "Hard / OFF"), ("🎮", "Games / Play button"),
    ("🏆", "Win (dice)"), ("🚩", "Lost (dice)"), ("🤝", "Tie"), ("🤖", "Bot"), ("🎯", "Bets / Wagered"),
    # money / account
    ("💰", "Balance / Cashout / Claim"), ("💳", "Payments / Deposit-Withdraw"), ("💸", "Total payouts"),
    ("🏦", "House profit"), ("📥", "Deposit"), ("📤", "Withdraw / Share / Sending"),
    ("🎁", "Ready to claim"), ("🔐", "Provably fair seed"), ("🔒", "Locked / Wager left"),
    # menu / info
    ("👤", "Profile / user line"), ("🆔", "User ID"), ("👥", "Users / Referral"),
    ("⚙️", "Settings / Preferences"), ("🛠", "Admin panel / disabled"), ("📊", "Stats"),
    ("📒", "Statement"), ("📜", "Terms"), ("📄", "PDF export"), ("🗒", "Recent games"),
    ("🖥", "UI mode"), ("🏷", "Casino name"), ("🎨", "Branding"), ("🖼", "Start card design"),
    ("🌐", "Community"), ("📢", "Broadcast"), ("📩", "DM sent / Open DM"),
]


def norm(s):
    return (s or "").replace("\ufe0f", "")


KEYS = {norm(e): (e, lab) for e, lab in EMOJIS}

_map = {}          # norm(emoji) -> custom emoji id
_enabled = True
_re = None
_ok = ContextVar("premium_ok", default=True)   # False = is request me premium band (fallback)
_err = {"last": ""}
_TAG = re.compile(r"(<[^>]*>)")
_NAME = re.compile(r"</?\s*([a-zA-Z0-9-]+)")


def reload():
    global _map, _enabled, _re
    _map = {r["emoji"]: r["cid"] for r in db("SELECT emoji,cid FROM emoji_map", fetch="all")}
    r = db("SELECT value FROM settings WHERE key='premium_on'", fetch="one")
    _enabled = not (r and r["value"] == "0")
    if _map:
        alt = "|".join(re.escape(k) for k in sorted(_map, key=len, reverse=True))
        _re = re.compile("(?:" + alt + ")\ufe0f?")
    else:
        _re = None


reload()

# Pehli baar chalne par ye default premium emoji set ho jaate hain (admin panel se badal / hata sakte ho,
# hatane ke baad wapas nahi aate).
SEED = {"💥": "5425004944270850753"}   # blast tile (Tower + Mines)
if not db("SELECT 1 FROM settings WHERE key='premium_seed1'", fetch="one"):
    for _e, _c in SEED.items():
        db("INSERT INTO emoji_map VALUES(?,?) ON CONFLICT(emoji) DO NOTHING", (norm(_e), _c))
    db("INSERT INTO settings VALUES('premium_seed1','1') ON CONFLICT(key) DO NOTHING")
    reload()


# ───────────── admin API ─────────────
def enabled():
    return _enabled


def set_enabled(flag):
    db("INSERT INTO settings VALUES('premium_on',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       ("1" if flag else "0",))
    reload()


def mapped():
    return dict(_map)


def cid_of(emoji):
    return _map.get(norm(emoji))


def has(emoji):
    return norm(emoji) in _map


def set_many(pairs):
    """pairs: {emoji: custom_emoji_id}. Sirf EMOJIS list wale emoji aur numeric ID accept hote hain."""
    n = 0
    for e, cid in pairs.items():
        k = norm(e)
        if k in KEYS and str(cid).isdigit():
            db("INSERT INTO emoji_map VALUES(?,?) ON CONFLICT(emoji) DO UPDATE SET cid=excluded.cid", (k, str(cid)))
            n += 1
    reload()
    return n


def remove(emoji):
    db("DELETE FROM emoji_map WHERE emoji=?", (norm(emoji),))
    reload()


def clear():
    db("DELETE FROM emoji_map")
    reload()


def note_error(desc):
    _err["last"] = (desc or "")[:200]


def last_error():
    return _err["last"]


def clear_error():
    _err["last"] = ""


# ───────────── used by ui.py ─────────────
def on():
    return _enabled and bool(_map) and _ok.get()


def suspend():
    return _ok.set(False)


def resume(token):
    _ok.reset(token)


def html(text):
    """HTML text me mapped emoji -> <tg-emoji>. Tags, <code>, <pre> ke andar kuch nahi badalta."""
    if not text or not on():
        return text
    out, depth = [], 0

    def sub(m):
        return f'<tg-emoji emoji-id="{_map[norm(m.group(0))]}">{m.group(0)}</tg-emoji>'

    for tok in _TAG.split(text):
        if tok.startswith("<") and tok.endswith(">"):
            m = _NAME.match(tok)
            if m and m.group(1).lower() in ("code", "pre", "tg-emoji"):
                depth += -1 if tok.startswith("</") else 1
            out.append(tok)
        else:
            out.append(_re.sub(sub, tok) if depth <= 0 else tok)
    return "".join(out)


def lead(text):
    """Button text ka pehla emoji mapped ho to (custom_emoji_id, baaki text), warna (None, text).
    Sirf emoji wale button (jaise game tiles) me text khali nahi ho sakta, isliye invisible char (U+2800) lagta hai.
    Agar Telegram ye reject kare to ui._guard normal emoji ke saath wapas bhej deta hai."""
    if not text or not on():
        return None, text
    m = _re.match(text)
    if not m:
        return None, text
    rest = text[m.end():].lstrip() or "\u2800"
    return _map[norm(m.group(0))], rest
