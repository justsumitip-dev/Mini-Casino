"""🎲 Dice Match — player aur bot Telegram ke asli 🎲 emoji se baari-baari fekte hain.

Flow:  /dice 5   ->  "Dice match started"  ->  Bot fekta hai  ->  "send 🎲 x2"  ->  player 2 dice bhejta hai
       ->  total compare  ->  jo pehle `first to N` rounds jeete wo winner.
Modes: Classic = bada total jeete | Crazy = chhota total jeete | tie = round dobara.
Fair kyun: dice Telegram ke server par random hote hain (bot badal nahi sakta); forwarded dice reject hote hain.

Is game me kuch badalna ho to sirf yahi file edit karo.
Admin panel -> Games -> Dice me: ON/OFF, naam, dice count, first-to, crazy mode, timeout, payout, min/max bet, edge.
"""
import asyncio
import json
import logging
import re
import secrets
import string
import time
from collections import defaultdict

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

import tg
from database import cap, db, debit, ensure_user, fget, finish, fmt, get, pref, sess_del, sess_get, sess_set, set_pref, balance
from ui import Btn, Screen, esc, send, show

from .common import (DISABLED, NOT_ENOUGH, alert, bet_error, bet_rows, busy_msg, edge_for, get_bet, is_on, parse_bet,
                     reply_err)
from .registry import Game, register

log = logging.getLogger("dice")
router = Router(name="dice")

ANIM = 3.6                      # Telegram dice animation ka time (sec)
LOCKS = defaultdict(asyncio.Lock)
N_RANGE, T_RANGE = (1, 3), (1, 5)


def P(*lines, buttons=None):
    """Plain (non-rich) message, screenshots jaisa look."""
    return Screen(rich=False, body=["\n".join(lines)], buttons=buttons or [])


# ═════════════════ SETTINGS ═════════════════
def _int(name, lo, hi, default):
    try:
        v = int(float(get(f"dice_{name}")))
    except (ValueError, TypeError):
        return default
    return min(max(v, lo), hi)


def admin_defaults():
    return (_int("count", *N_RANGE, 2), _int("target", *T_RANGE, 2), get("dice_crazy") == "1")


def opts_for(uid, tokens=()):
    """-> (n, target, crazy) | error text.  Order: command args > user prefs > admin defaults."""
    n, t, crazy = admin_defaults()
    if get("dice_player_opts") == "1":
        n = int(pref(uid, "dice_n", n)) if str(pref(uid, "dice_n", n)).isdigit() else n
        t = int(pref(uid, "dice_t", t)) if str(pref(uid, "dice_t", t)).isdigit() else t
        n, t = min(max(n, N_RANGE[0]), N_RANGE[1]), min(max(t, T_RANGE[0]), T_RANGE[1])
    if get("dice_allow_crazy") == "1":
        p = pref(uid, "dice_crazy", "")
        crazy = (p == "1") if p in ("0", "1") else crazy
    else:
        crazy = admin_defaults()[2]
    nums = []
    for tk in (x.lower() for x in tokens):
        if tk in ("crazy", "c") and get("dice_allow_crazy") == "1":
            crazy = True
        elif tk in ("normal", "classic", "n") and get("dice_allow_crazy") == "1":
            crazy = False
        elif tk.isdigit() and get("dice_player_opts") == "1":
            nums.append(int(tk))
    if nums:
        n = nums[0]
        t = nums[1] if len(nums) > 1 else t
        if not (N_RANGE[0] <= n <= N_RANGE[1]) or not (T_RANGE[0] <= t <= T_RANGE[1]):
            return f"❌ Dice must be {N_RANGE[0]}-{N_RANGE[1]} and first-to {T_RANGE[0]}-{T_RANGE[1]}. Example: <code>/dice 5 crazy 2 3</code>"
    return n, t, crazy


def win_mult():
    v = fget("dice_payout", 0.0)
    m = v if v >= 1 else 2 * (1 - edge_for("dice"))
    return round(min(m, cap()), 4)


def game_id():
    pre = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", get("brand")))[:2].upper() or "CS"
    al = string.ascii_uppercase + string.digits
    rnd = lambda k: "".join(secrets.choice(al) for _ in range(k))
    return f"{pre}-DI{rnd(3)}-{rnd(6)}"


def mode_line(crazy):
    return "Crazy — lowest total wins" if crazy else "Classic — highest total wins"


def roll_txt(vals):
    return f"<b>{sum(vals)}</b>" + (f" ({' + '.join(map(str, vals))})" if len(vals) > 1 else "")


def pname(s):
    return esc(s["name"])


def reply_to(mid):
    return {"message_id": mid, "allow_sending_without_reply": True} if mid else None


# ═════════════════ MENU (button UI) ═════════════════
def build_dice(uid):
    n, t, crazy = opts_for(uid)
    bet = get_bet(uid, "dice")
    rows = bet_rows("dice", uid)
    if get("dice_allow_crazy") == "1":
        rows.append([Btn(("✅ " if not crazy else "") + "Classic", "dc:mode:0", style="success" if not crazy else "primary"),
                     Btn(("✅ " if crazy else "") + "Crazy", "dc:mode:1", style="success" if crazy else "primary")])
    if get("dice_player_opts") == "1":
        rows.append([Btn(("✅ " if k == n else "") + f"{k} 🎲", f"dc:n:{k}", style="success" if k == n else "primary")
                     for k in range(N_RANGE[0], N_RANGE[1] + 1)])
        rows.append([Btn(("✅ " if k == t else "") + f"First to {k}", f"dc:t:{k}", style="success" if k == t else "primary")
                     for k in (1, 2, 3, 5)])
    rows.append([Btn("▶️ Start Match", "dc:go", style="success")])
    rows.append([Btn("⬅️ Games", "play", style="primary")])
    return Screen(title="🎲 <b>Dice Match</b>",
                  rows=[("Balance", fmt(balance(uid))), ("Bet", fmt(bet)), ("Mode", f"{n} dice, first to {t}"),
                        ("Rule", mode_line(crazy)), ("Win pays", f"{win_mult():.2f}x")],
                  body=["You and the bot roll real Telegram dice, turn by turn. "
                        "Preset: <code>/dice 5</code> or <code>/dice 5 crazy 2 3</code>, then press Start Match"],
                  buttons=rows)


# ═════════════════ MATCH ENGINE ═════════════════
async def _send(s, screen):
    r = await send(s["chat"], screen)
    return (r or {}).get("message_id", 0) if isinstance(r, dict) else 0


async def _save(uid, s):
    sess_set(uid, "dice", s)


def _refund(uid, gid):
    g, s = sess_get(uid)
    if g == "dice" and s.get("gid") == gid:
        sess_del(uid)
        finish(uid, "Dice", s["bet"], s["bet"], gid=gid)


async def bot_turn(uid, s):
    """Bot apne dice fekta hai, phir player ko bolta hai."""
    s["phase"], s["deadline"], s["buf"] = "bot", time.time() + 90, []
    await _save(uid, s)
    vals = []
    for _ in range(s["n"]):
        r = await tg.call("sendDice", chat_id=s["chat"], emoji="🎲", reply_parameters=reply_to(s["reply"]))
        vals.append(r["dice"]["value"])
    await asyncio.sleep(ANIM)
    s["bot"] = vals
    mid = await _send(s, P(f"🤖 Bot rolled {roll_txt(vals)}",
                           f"<blockquote>👤 <b>{pname(s)}</b> to roll — send 🎲 ×{s['n']}</blockquote>"))
    s["after"], s["phase"] = mid, "player"
    s["deadline"] = time.time() + _int("timeout", 20, 900, 120)
    await _save(uid, s)


async def start_match(user, chat_id, bet, n, t, crazy, reply):
    """-> None (shuru ho gaya) ya error text."""
    uid = user.id
    await settle_expired(uid)
    if not is_on("dice"):
        return DISABLED
    err = bet_error(bet, "dice")
    if err:
        return err
    b = busy_msg(uid)
    if b:
        return b
    if not debit(uid, bet, "Dice"):
        return NOT_ENOUGH
    s = {"gid": game_id(), "bet": bet, "n": n, "t": t, "crazy": crazy, "score": [0, 0], "round": 1,
         "phase": "bot", "chat": chat_id, "name": (user.first_name or "Player")[:16], "reply": reply, "after": 0,
         "bot": [], "buf": [], "mult": win_mult(), "deadline": time.time() + 90}
    sess_set(uid, "dice", s)
    async with LOCKS[uid]:
        try:
            await _send(s, P("🎲 <b>Dice match started</b>", "",
                             f"<blockquote>👤 <b>{pname(s)}</b> vs 🤖 <b>Bot</b>", "",
                             f"Amount: <b>{esc(fmt(bet))}</b>", f"Mode: <b>{n} dice, first to {t}</b>",
                             mode_line(crazy), f"Game: <code>{s['gid']}</code></blockquote>"))
            await bot_turn(uid, s)
        except Exception:
            log.exception("dice start failed -> refund")
            _refund(uid, s["gid"])
            raise
    return None


async def finish_match(uid, s, last_p, last_b):
    sess_del(uid)
    won = s["score"][0] > s["score"][1]
    payout = round(s["bet"] * s["mult"], 2) if won else 0
    finish(uid, "Dice", s["bet"], payout, gid=s["gid"])
    net = round(payout - s["bet"], 2)
    head = (f"🏆 <b>{pname(s)}</b> won <b>{esc(fmt(net))}</b>" if won
            else f"🚩 <b>{pname(s)}</b> lost <b>{esc(fmt(s['bet']))}</b>")
    nb = round(s["bet"] * 2, 2)
    again = f"{s['bet']:g}:{s['n']}:{s['t']}:{int(s['crazy'])}"
    btns = [[Btn("🔁 Play Again", f"dc:again:{again}", style="primary")]]
    if nb <= 1e9:
        btns[0].append(Btn(f"✖️2 Double ({fmt(nb)})", f"dc:again:{nb:g}:{s['n']}:{s['t']}:{int(s['crazy'])}", style="primary"))
    btns.append([Btn("🔍 Verify Fairness", "dc:fair")])
    await _send(s, P(head,
                     f"<blockquote>👤 {pname(s)} - {s['score'][0]}", f"🤖 Bot - {s['score'][1]}", "",
                     f"Final roll: {sum(last_p)} vs {sum(last_b)}", f"Game <code>{s['gid']}</code></blockquote>",
                     buttons=btns))


async def resolve_round(uid, s):
    pv, bv = s["buf"], s["bot"]
    pt, bt = sum(pv), sum(bv)
    if pt == bt:
        line = "🤝 <b>Tie</b> — this round is replayed"
    else:
        player_wins = (pt < bt) if s["crazy"] else (pt > bt)
        s["score"][0 if player_wins else 1] += 1
        s["round"] += 1
        line = "✅ <b>You win this round!</b>" if player_wins else "❌ <b>Bot wins this round</b>"
    if max(s["score"]) >= s["t"]:
        return await finish_match(uid, s, pv, bv)
    await _send(s, P(f"👤 {pname(s)} rolled {roll_txt(pv)}", f"🤖 Bot rolled {roll_txt(bv)}", line,
                     f"<blockquote>Score: {pname(s)} {s['score'][0]} – {s['score'][1]} Bot  ·  first to {s['t']}</blockquote>"))
    await bot_turn(uid, s)


@router.message(F.dice)
async def on_dice(m: Message):
    d = m.dice
    if d.emoji != "🎲" or not m.from_user:
        return
    if getattr(m, "forward_origin", None) or getattr(m, "forward_date", None) or getattr(m, "via_bot", None):
        return  # forwarded / fake dice allowed nahi
    uid = m.from_user.id
    g, s = sess_get(uid)
    if g != "dice" or s["chat"] != m.chat.id:
        return
    async with LOCKS[uid]:
        g, s = sess_get(uid)
        if g != "dice" or s["phase"] != "player" or m.message_id <= s["after"] or time.time() > s["deadline"]:
            return
        s["buf"].append(d.value)
        if len(s["buf"]) < s["n"]:
            return await _save(uid, s)
        s["phase"], s["deadline"] = "resolve", time.time() + 90
        await _save(uid, s)
        try:
            await asyncio.sleep(ANIM)
            await resolve_round(uid, s)
        except Exception:
            log.exception("dice round failed -> refund")
            _refund(uid, s["gid"])
            raise


# ═════════════════ TIMEOUT ═════════════════
async def settle_expired(uid):
    async with LOCKS[uid]:
        g, s = sess_get(uid)
        if g != "dice" or s.get("deadline", 0) >= time.time():
            return False
        sess_del(uid)
        forfeit = s["phase"] == "player"
        finish(uid, "Dice", s["bet"], 0 if forfeit else s["bet"], gid=s["gid"])
    try:
        await _send(s, P("⌛ <b>Match timed out</b>",
                         f"<blockquote>{pname(s)} didn't roll in time — "
                         + (f"bet {esc(fmt(s['bet']))} forfeited." if forfeit else f"bet {esc(fmt(s['bet']))} refunded.")
                         + f"\nGame <code>{s['gid']}</code></blockquote>"))
    except Exception:
        pass
    return True


async def background(bot=None):
    while True:
        await asyncio.sleep(15)
        try:
            for r in db("SELECT uid, data FROM sessions WHERE game='dice'", fetch="all"):
                if json.loads(r["data"]).get("deadline", 0) < time.time():
                    await settle_expired(r["uid"])
        except Exception:
            log.exception("dice sweeper")


# ═════════════════ HANDLERS ═════════════════
@router.message(Command("dice"))
async def dice_cmd(m: Message, command: CommandObject):
    """/dice  ya  /dice <bet> [crazy] [dice] [first-to]  -> setup screen (match 'Start Match' dabane par shuru)."""
    u, _ = ensure_user(m.from_user)
    uid = u["id"]
    args = (command.args or "").split()
    if args:
        bet = parse_bet(args[0], uid)
        err = bet_error(bet, "dice")
        o = opts_for(uid, args[1:]) if not err else None
        if err or isinstance(o, str):
            return await reply_err(m, err or o)
        set_pref(uid, "bet", bet)
        n, t, crazy = o
        if get("dice_player_opts") == "1":
            set_pref(uid, "dice_n", n)
            set_pref(uid, "dice_t", t)
        if get("dice_allow_crazy") == "1":
            set_pref(uid, "dice_crazy", "1" if crazy else "0")
    await send(m.chat.id, build_dice(uid), reply_to=m.message_id)


@router.callback_query(F.data == "dc:go")
async def go(c: CallbackQuery):
    ensure_user(c.from_user)
    uid = c.from_user.id
    o = opts_for(uid)
    await c.answer("🎲 Starting...")
    err = await start_match(c.from_user, c.message.chat.id, get_bet(uid, "dice"), *o, reply=c.message.message_id)
    if err:
        await send(c.message.chat.id, Screen(rich=False, body=[err]), reply_to=c.message.message_id)


@router.callback_query(F.data.startswith("dc:again:"))
async def again(c: CallbackQuery):
    try:
        _, _, bet, n, t, cr = c.data.split(":")
        bet, n, t, cr = round(float(bet), 2), int(n), int(t), cr == "1"
    except ValueError:
        return await c.answer()
    ensure_user(c.from_user)
    if not (N_RANGE[0] <= n <= N_RANGE[1] and T_RANGE[0] <= t <= T_RANGE[1]):
        return await c.answer()
    await c.answer("🎲 Starting...")
    err = await start_match(c.from_user, c.message.chat.id, bet, n, t, cr, reply=c.message.message_id)
    if err:
        await send(c.message.chat.id, Screen(rich=False, body=[err]), reply_to=c.message.message_id)


@router.callback_query(F.data == "dc:fair")
async def fair(c: CallbackQuery):
    await alert(c, "🔍 Dice are Telegram's native 🎲 — values are generated by Telegram's servers, "
                   "so neither the bot nor the admin can change them. Forwarded dice are rejected.")


@router.callback_query(F.data.startswith("dc:mode:"))
async def set_mode(c: CallbackQuery):
    if c.data[8:] in ("0", "1"):
        set_pref(c.from_user.id, "dice_crazy", c.data[8:])
    await show(c, build_dice(c.from_user.id))


@router.callback_query(F.data.startswith("dc:n:"))
async def set_n(c: CallbackQuery):
    if c.data[5:].isdigit() and N_RANGE[0] <= int(c.data[5:]) <= N_RANGE[1]:
        set_pref(c.from_user.id, "dice_n", c.data[5:])
    await show(c, build_dice(c.from_user.id))


@router.callback_query(F.data.startswith("dc:t:"))
async def set_t(c: CallbackQuery):
    if c.data[5:].isdigit() and T_RANGE[0] <= int(c.data[5:]) <= T_RANGE[1]:
        set_pref(c.from_user.id, "dice_t", c.data[5:])
    await show(c, build_dice(c.from_user.id))


# ═════════════════ REGISTER ═════════════════
register(Game(
    key="dice", title="Dice", build=build_dice, router=router, order=1,
    usage="/dice <bet> [crazy] [dice] [first-to]", cmd_desc="/dice <bet> - Dice match vs bot",
    background=background,
    settings=[
        ("count", "2", "Dice per roll (1-3)", "int:1:3"),
        ("target", "2", "First to N rounds (1-5)", "int:1:5"),
        ("crazy", "1", "Crazy mode by default", "bool"),
        ("allow_crazy", "1", "Players pick Classic/Crazy", "bool"),
        ("player_opts", "1", "Players change dice/first-to", "bool"),
        ("timeout", "120", "Roll timeout (seconds)", "int:20:900"),
        ("payout", "", "Win multiplier (blank=auto)", "mult"),
    ]))
