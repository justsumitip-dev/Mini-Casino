import json
import math
import sqlite3
import time

import fair
from config import DB_PATH

DB = sqlite3.connect(DB_PATH, check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("PRAGMA journal_mode=WAL")


def db(sql, args=(), fetch=None):
    cur = DB.execute(sql, args)
    DB.commit()
    if fetch == "one":
        return cur.fetchone()
    if fetch == "all":
        return cur.fetchall()
    return cur


# ───────────── TABLES ─────────────
db("""CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, name TEXT, username TEXT,
    balance REAL DEFAULT 0, wagered REAL DEFAULT 0,
    last_win REAL DEFAULT 0, last_game TEXT,
    joined INTEGER, banned INTEGER DEFAULT 0)""")
try:  # old database upgrade
    db("ALTER TABLE users ADD COLUMN last_game TEXT")
except sqlite3.OperationalError:
    pass
db("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
db("CREATE TABLE IF NOT EXISTS games(key TEXT PRIMARY KEY, title TEXT, enabled INTEGER DEFAULT 1, sort INTEGER)")
db("CREATE TABLE IF NOT EXISTS sessions(uid INTEGER PRIMARY KEY, game TEXT, data TEXT)")
db("CREATE TABLE IF NOT EXISTS prefs(uid INTEGER, key TEXT, value TEXT, PRIMARY KEY(uid, key))")
db("CREATE TABLE IF NOT EXISTS history(ts INTEGER, uid INTEGER, game TEXT, bet REAL, payout REAL)")
try:  # game id (jaise AX-DI22C-DYLM4A) history me
    db("ALTER TABLE history ADD COLUMN gid TEXT")
except sqlite3.OperationalError:
    pass
for _col in ("ref_by INTEGER", "ref_ts INTEGER", "ref_pending REAL DEFAULT 0",
             "ref_claimed REAL DEFAULT 0", "wager_req REAL DEFAULT 0"):
    try:  # referral / wagering columns
        db(f"ALTER TABLE users ADD COLUMN {_col}")
    except sqlite3.OperationalError:
        pass
# txns = poora statement (har balance movement). ledger = purana admin-adjust log.
db("CREATE TABLE IF NOT EXISTS txns(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, uid INTEGER, "
   "kind TEXT, amount REAL, balance REAL, note TEXT)")
db("CREATE INDEX IF NOT EXISTS txns_uid ON txns(uid, id)")
db("CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, uid INTEGER, "
   "kind TEXT, amount REAL, asset TEXT, status TEXT, tx TEXT, note TEXT)")
db("CREATE INDEX IF NOT EXISTS pay_uid ON payments(uid, kind, id)")
db("CREATE TABLE IF NOT EXISTS ref_earn(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, referrer INTEGER, "
   "referred INTEGER, kind TEXT, base REAL, amount REAL)")
db("CREATE INDEX IF NOT EXISTS ref_earn_r ON ref_earn(referrer, referred)")
db("CREATE INDEX IF NOT EXISTS history_uid ON history(uid, ts)")
db("CREATE TABLE IF NOT EXISTS links(id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, url TEXT)")
db("CREATE TABLE IF NOT EXISTS ledger(ts INTEGER, uid INTEGER, amount REAL, reason TEXT, admin INTEGER)")
db("""CREATE TABLE IF NOT EXISTS rounds(
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, game TEXT, seed TEXT, seed_hash TEXT,
    nonce INTEGER, bet REAL, payout REAL DEFAULT 0, ts INTEGER, done INTEGER DEFAULT 0)""")

# ───────────── SETTINGS (admin panel se badalte hain) ─────────────
# register(key, default, label, kind, group)
#   kind : text | url | num | edge | mult | int:LO:HI | bool | choice:a,b,c | presets
#   group: brand | card | bets | pay | terms | game:<key>   (admin panel me kis page par dikhe)
DEFAULTS = {}
SPEC = {}


def register(key, default, label, kind="text", group="misc"):
    DEFAULTS.setdefault(key, (default, label))
    SPEC[key] = (kind, group)


register("brand", "YOUR CASINO", "Casino name", "text", "brand")
register("welcome_title", "Your table's ready.", "Welcome title", "text", "brand")
register("welcome_text", "Top up, pick a game, and let the good rolls find you ✨", "Welcome text", "text", "brand")
register("play_btn", "Play Now", "Play button text", "text", "brand")
register("currency", "$", "Currency symbol", "text", "brand")

register("card_enabled", "1", "Start photo card ON/OFF", "bool", "card")
register("card_theme", "teal", "Card theme", "choice:teal,gold,purple,ruby", "card")
register("card_badge", "WELCOME PASS", "Card badge text (new players)", "text", "card")
register("card_footer", "Tap Play Now to pick a game. Play responsibly.", "Card footer text", "text", "card")
register("card_avatar", "1", "Show Telegram profile photo on card", "bool", "card")

register("min_bet", "1", "Min bet", "num", "bets")
register("max_bet", "1000", "Max bet", "num", "bets")
register("bet_presets", "1,5,10,50,100", "Quick bet buttons (max 5, comma separated)", "presets", "bets")
register("house_edge", "3", "House edge % (3 = 3%)", "edge", "bets")
register("max_mult", "500", "Max multiplier cap (auto cashout)", "mult", "bets")

register("deposit_url", "", "Deposit button link (blank = maintenance msg)", "url", "pay")
register("withdraw_url", "", "Withdraw button link (blank = maintenance msg)", "url", "pay")
register("maint_msg", "🛠 This feature is under maintenance. Please try again later.", "Deposit/Withdraw maintenance message", "text", "pay")

register("terms_url", "", "Fair Play & Terms link (optional)", "url", "terms")
register("terms_text", "Terms and fair play rules will be added soon.", "Terms text (used if no link)", "text", "terms")
register("ref_enabled", "1", "Referral system ON/OFF", "bool", "ref")
register("ref_title", "REFER & EARN", "Referral card title", "text", "ref")
register("ref_theme", "cream", "Referral card theme", "choice:cream,night", "ref")
register("ref_wager_pct", "0.3", "Wager share % (of referred players' bets)", "num", "ref")
register("ref_deposit_pct", "0", "Deposit reward % (0 = off)", "num", "ref")
register("ref_claim_mult", "2", "Wager needed on claimed money (x)", "num", "ref")
register("ref_min_claim", "0.01", "Min claim amount", "num", "ref")
register("ref_group_link", "", "Group invite link shown under /refer", "url", "ref")

register("dm_only", "1", "Private commands DM only (group -> DM)", "bool", "stmt")
register("stmt_rows", "8", "Statement rows per page (4-12)", "int:4:12", "stmt")
register("pay_rows", "10", "Payment history rows (3-25)", "int:3:25", "stmt")
register("pay_unit", "USD", "Unit shown in payment history", "text", "stmt")
register("pdf_max_rows", "2000", "Max rows inside one PDF (200-20000)", "int:200:20000", "stmt")
NUMERIC = {"min_bet", "max_bet", "house_edge", "max_mult"}

GROUPS = {  # admin menu me page ka naam
    "brand": "🎨 Branding & Texts",
    "card": "🖼 Start Card Design",
    "bets": "💰 Bets & Payout",
    "pay": "💳 Deposit / Withdraw",
    "terms": "📜 Terms",
    "ref": "👥 Referral System",
    "stmt": "📒 Statement & History",
}


def validate(key, val):
    """True agar val is setting ke liye theek hai."""
    kind = SPEC.get(key, ("text", ""))[0]
    if kind == "text":
        return True
    if kind == "url":
        return val.startswith(("http://", "https://", "tg://"))
    if kind == "bool":
        return val in ("0", "1")
    if kind.startswith("choice:"):
        return val in kind[7:].split(",")
    if kind == "presets":
        try:
            xs = [float(x) for x in val.split(",")]
        except ValueError:
            return False
        return bool(xs) and all(math.isfinite(x) and x > 0 for x in xs)
    if kind.startswith("int:"):
        _, lo, hi = kind.split(":")
        return val.lstrip("-").isdigit() and int(lo) <= int(val) <= int(hi)
    try:
        v = float(val)
    except ValueError:
        return False
    if not math.isfinite(v) or v < 0:
        return False
    if kind == "edge":
        return v <= 50
    if kind == "mult":
        return v >= 1
    return True


# purana single community_url -> links table (ek baar)
_old = db("SELECT value FROM settings WHERE key='community_url'", fetch="one")
if _old and _old["value"] and not db("SELECT 1 FROM links", fetch="one"):
    db("INSERT INTO links(label,url) VALUES(?,?)", ("🌐 Community", _old["value"]))


def get(k):
    r = db("SELECT value FROM settings WHERE key=?", (k,), "one")
    return r["value"] if r else DEFAULTS[k][0]


def put(k, v):
    db("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def reset(k):
    db("DELETE FROM settings WHERE key=?", (k,))


def fget(k, default=0.0):
    try:
        v = float(get(k))
    except (ValueError, TypeError):
        return default
    return v if math.isfinite(v) else default


def edge():
    return min(max(fget("house_edge", 3.0), 0.0), 50.0) / 100


def cap():
    return max(fget("max_mult", 500.0), 1.0)


def fmt(x):
    return f"{get('currency')}{x:,.2f}"


# ───────────── USERS / MONEY ─────────────
def ensure_user(t):
    r = db("SELECT * FROM users WHERE id=?", (t.id,), "one")
    new = r is None
    if new:
        db("INSERT INTO users(id,name,username,joined) VALUES(?,?,?,?)",
           (t.id, t.full_name, t.username, int(time.time())))
    else:
        db("UPDATE users SET name=?, username=? WHERE id=?", (t.full_name, t.username, t.id))
    return db("SELECT * FROM users WHERE id=?", (t.id,), "one"), new


def tier(w):
    return "Bronze" if w < 100 else "Silver" if w < 1000 else "Gold" if w < 10000 else "Platinum"


TIERS = [("Bronze", 0), ("Silver", 100), ("Gold", 1000), ("Platinum", 10000)]


def tier_info(w):
    """-> (naam, is tier ki shuruat, agle tier ki limit, agle tier ka naam). Max par (.., None, None)"""
    cur = 0
    for i, (n, t) in enumerate(TIERS):
        if w >= t:
            cur = i
    nxt = TIERS[cur + 1] if cur + 1 < len(TIERS) else None
    return TIERS[cur][0], TIERS[cur][1], (nxt[1] if nxt else None), (nxt[0] if nxt else None)


def balance(uid):
    r = db("SELECT balance FROM users WHERE id=?", (uid,), "one")
    return r["balance"] if r else 0.0


def tx(uid, kind, amount, note=""):
    """Statement entry (balance abhi ke baad wala)."""
    db("INSERT INTO txns(ts,uid,kind,amount,balance,note) VALUES(?,?,?,?,?,?)",
       (int(time.time()), uid, kind, round(amount, 2), balance(uid), note))


def wager_left(uid):
    r = db("SELECT wager_req FROM users WHERE id=?", (uid,), "one")
    return max(r["wager_req"], 0.0) if r else 0.0


def debit(uid, amt, game=None):
    """Bet lagao. wagered badhta hai, referral share + wagering requirement yahin lagta hai."""
    cur = db("UPDATE users SET balance=ROUND(balance-?,2), wagered=ROUND(wagered+?,2), "
             "wager_req=MAX(ROUND(wager_req-?,2),0) WHERE id=? AND balance>=?", (amt, amt, amt, uid, amt))
    if cur.rowcount != 1:
        return False
    tx(uid, "Game Bet", -amt, game or "")
    ref_accrue(uid, "wager", amt)
    return True


def spend(uid, amt, kind, note=""):
    """Bina wager gine balance ghatao (withdrawal, admin deduct)."""
    cur = db("UPDATE users SET balance=ROUND(balance-?,2) WHERE id=? AND balance>=?", (amt, uid, amt))
    if cur.rowcount != 1:
        return False
    tx(uid, kind, -amt, note)
    return True


def credit(uid, amt, win_game=None, kind="Credit", note=""):
    if win_game:
        db("UPDATE users SET balance=ROUND(balance+?,2), last_win=?, last_game=? WHERE id=?",
           (amt, amt, win_game, uid))
    else:
        db("UPDATE users SET balance=ROUND(balance+?,2) WHERE id=?", (amt, uid))
    tx(uid, kind, amt, note)


def finish(uid, game, bet, payout, rid=None, gid=None):
    """Game khatam: payout (0 = loss), history + round close."""
    payout = round(payout, 2)
    if payout > 0:
        kind = "Game Win" if payout > bet else "Game Refund" if payout == bet else "Game Payout"
        credit(uid, payout, game if payout > bet else None, kind=kind, note=game)
    db("INSERT INTO history(ts,uid,game,bet,payout,gid) VALUES(?,?,?,?,?,?)",
       (int(time.time()), uid, game, bet, payout, gid))
    if rid:
        db("UPDATE rounds SET payout=?, done=1 WHERE id=?", (payout, rid))


# ───────────── REFERRAL (accrual; baaki referral.py me) ─────────────
def ref_accrue(uid, kind, base):
    """uid ke referrer ko share do. kind: 'wager' | 'deposit'."""
    r = db("SELECT ref_by FROM users WHERE id=?", (uid,), "one")
    if not r or not r["ref_by"] or get("ref_enabled") != "1":
        return
    pct = fget("ref_wager_pct" if kind == "wager" else "ref_deposit_pct", 0.0)
    amt = round(base * pct / 100, 4) if pct > 0 else 0
    if amt <= 0:
        return
    db("UPDATE users SET ref_pending=ref_pending+? WHERE id=?", (amt, r["ref_by"]))
    db("INSERT INTO ref_earn(ts,referrer,referred,kind,base,amount) VALUES(?,?,?,?,?,?)",
       (int(time.time()), r["ref_by"], uid, kind, base, amt))


# ───────────── PROVABLY FAIR ROUNDS ─────────────
def new_round(uid, game, bet):
    nonce = db("SELECT COUNT(*) n FROM rounds WHERE uid=?", (uid,), "one")["n"]
    seed = fair.new_seed()
    cur = db("INSERT INTO rounds(uid,game,seed,seed_hash,nonce,bet,ts) VALUES(?,?,?,?,?,?,?)",
             (uid, game, seed, fair.seed_hash(seed), nonce, bet, int(time.time())))
    return cur.lastrowid, seed, nonce


def round_get(rid):
    return db("SELECT * FROM rounds WHERE id=?", (rid,), "one")


# ───────────── COMMUNITY LINKS ─────────────
def links():
    return db("SELECT * FROM links ORDER BY id", fetch="all")


# ───────────── SESSIONS / PREFS ─────────────
def sess_get(uid):
    r = db("SELECT game, data FROM sessions WHERE uid=?", (uid,), "one")
    return (r["game"], json.loads(r["data"])) if r else (None, None)


def sess_set(uid, game, data):
    db("INSERT OR REPLACE INTO sessions VALUES(?,?,?)", (uid, game, json.dumps(data)))


def sess_del(uid):
    db("DELETE FROM sessions WHERE uid=?", (uid,))


def pref(uid, key, default):
    r = db("SELECT value FROM prefs WHERE uid=? AND key=?", (uid, key), "one")
    return r["value"] if r else default


def set_pref(uid, key, value):
    db("INSERT OR REPLACE INTO prefs VALUES(?,?,?)", (uid, key, str(value)))