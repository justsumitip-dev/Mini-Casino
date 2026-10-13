"""Sab games ka shared code: bet system, custom bet, fairness popup, game open."""
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database import balance, db, edge, ensure_user, fget, fmt, get, pref, round_get, sess_get, set_pref
from ui import Btn, Screen, edit, esc, send, show

from .registry import GAMES

router = Router(name="common")
NOT_ENOUGH = "❌ Not enough balance."
NO_GAME = "❌ This game isn't active."
DISABLED = "🛠 This game is disabled."


class U(StatesGroup):
    custom = State()


# ═════════════════ PER-GAME LIMITS / EDGE ═════════════════
def _opt(key):
    """Game override (blank = None)."""
    try:
        v = float(get(key))
    except (ValueError, TypeError, KeyError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def limits(game=None):
    lo = fget("min_bet", 1.0)
    hi = max(fget("max_bet", 1000.0), lo)
    if game:
        glo, ghi = _opt(f"{game}_min"), _opt(f"{game}_max")
        lo = glo if glo is not None else lo
        hi = ghi if ghi is not None else hi
        hi = max(hi, lo)
    return lo, hi


def edge_for(game):
    v = _opt(f"{game}_edge")
    return edge() if v is None or v > 50 else v / 100


# ═════════════════ BET SYSTEM ═════════════════
def get_bet(uid, game=None):
    lo, hi = limits(game)
    try:
        b = float(pref(uid, "bet", "1"))
    except ValueError:
        b = lo
    if not math.isfinite(b):
        b = lo
    return min(max(b, lo), hi)


def presets():
    out = []
    for x in get("bet_presets").split(","):
        try:
            v = float(x)
        except ValueError:
            continue
        if v > 0 and math.isfinite(v):
            out.append(v)
    return out[:5] or [1.0]


def bet_rows(game, uid):
    bet = get_bet(uid, game)
    row = []
    for p in presets():
        sel = abs(p - bet) < 1e-9
        row.append(Btn(("✅ " if sel else "") + f"{p:g}", f"bet:{game}:{p:g}", style="success" if sel else "primary"))
    return [row, [Btn("½", f"bet:{game}:half", style="danger"),
                  Btn("✏️ Custom", f"cust:{game}", style="primary"),
                  Btn("2×", f"bet:{game}:dbl", style="success")]]


def parse_bet(txt, uid):
    t = txt.lower().replace(",", "")
    if t == "all":
        v = balance(uid)
    elif t == "half":
        v = balance(uid) / 2
    else:
        try:
            v = float(t)
        except ValueError:
            return None
    return round(v, 2) if math.isfinite(v) else None


def bet_error(bet, game=None):
    lo, hi = limits(game)
    if bet is None:
        return "❌ Invalid bet. Example: <code>/tower 2</code>"
    if bet < lo or bet > hi:
        return f"❌ Bet must be between {esc(fmt(lo))} and {esc(fmt(hi))}."
    return None


def is_on(key):
    g = db("SELECT enabled FROM games WHERE key=?", (key,), "one")
    return bool(g and g["enabled"])


def own_session(c, game, rid):
    g, s = sess_get(c.from_user.id)
    return s if g == game and s.get("rid") == rid else None


def active_screen(uid):
    """Chalta hua (resume ho sakne wala) game hai to uski screen."""
    g, s = sess_get(uid)
    if g in GAMES and GAMES[g].resume:
        return GAMES[g].resume(uid, s)
    return None


def busy_msg(uid):
    """Koi aur game chal raha hai (jo resume nahi ho sakta, jaise dice match) to error text."""
    g, _ = sess_get(uid)
    if g:
        return f"⏳ You have an active {esc(GAMES[g].title if g in GAMES else g)} game. Finish it first."
    return None


async def reply_err(m, txt):
    await send(m.chat.id, Screen(rich=False, body=[txt]), reply_to=m.message_id)


async def alert(c, txt):
    await c.answer(txt.replace("<code>", "").replace("</code>", "").replace("<b>", "").replace("</b>", ""), show_alert=True)


# ═════════════════ HANDLERS ═════════════════
@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data.startswith("bet:"))
async def set_bet(c: CallbackQuery):
    _, game, val = c.data.split(":")
    if game not in GAMES:
        return await c.answer()
    uid = c.from_user.id
    now = get_bet(uid, game)
    try:
        nb = now / 2 if val == "half" else now * 2 if val == "dbl" else float(val)
    except ValueError:
        return await c.answer()
    lo, hi = limits(game)
    set_pref(uid, "bet", round(min(max(nb, lo), hi), 2))
    await show(c, GAMES[game].build(uid))


@router.callback_query(F.data.startswith("cust:"))
async def custom_bet(c: CallbackQuery, state: FSMContext):
    game = c.data[5:]
    lo, hi = limits(game)
    await state.set_state(U.custom)
    await state.update_data(game=game, chat=c.message.chat.id, mid=c.message.message_id)
    await send(c.message.chat.id, Screen(rich=False, body=[
        f"✏️ Send your bet amount ({esc(fmt(lo))} – {esc(fmt(hi))}).\n/cancel to stop."]))
    await c.answer()


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❌ Cancelled.")


@router.callback_query(F.data.startswith("fair:"))
async def fair_cb(c: CallbackQuery):
    r = round_get(int(c.data[5:]))
    if not r or not r["done"]:
        return await c.answer("🔐 Seed is revealed after the round ends.", show_alert=True)
    body = [
        f"🔐 <b>Provably Fair</b> · Round #{r['id']} ({esc(r['game'])})",
        f"Server seed:\n<code>{r['seed']}</code>",
        f"SHA-256 (shown before the game):\n<code>{r['seed_hash']}</code>",
        f"Player ID: <code>{r['uid']}</code> · Nonce: <code>{r['nonce']}</code>",
        "Each random number = <code>int(HMAC_SHA256(seed, \"uid:nonce:tag\")[:13], 16) mod N</code>\n"
        "Tower tag: <code>tower:FLOOR-1</code> (N = columns), Mines: Fisher-Yates with tag <code>mines:i</code>.",
    ]
    await send(c.message.chat.id, Screen(rich=False, body=["\n\n".join(body)]), reply_to=c.message.message_id)
    await c.answer()


@router.callback_query(F.data.startswith("g:"))
async def open_game(c: CallbackQuery):
    key = c.data[2:]
    if key not in GAMES or not is_on(key):
        return await c.answer("🛠 Coming soon!", show_alert=True)
    ensure_user(c.from_user)
    await show(c, GAMES[key].build(c.from_user.id))


# custom bet (state handler: sabse last me, taaki commands pehle match ho)
@router.message(U.custom)
async def custom_bet_save(m: Message, state: FSMContext):
    txt = (m.text or "").strip()
    if txt.startswith("/"):
        return await m.answer("Send a number, or /cancel.")
    d = await state.get_data()
    game = d.get("game")
    v = parse_bet(txt, m.from_user.id)
    err = bet_error(v, game)
    if err:
        return await m.answer(err)
    await state.clear()
    set_pref(m.from_user.id, "bet", v)
    if game in GAMES:
        await edit(d["chat"], d["mid"], GAMES[game].build(m.from_user.id))
    await m.answer(f"✅ Bet set to {esc(fmt(v))}")
