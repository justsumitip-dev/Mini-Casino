"""Mines game. Is game me kuch badalna ho to sirf yahi file edit karo.
Admin panel -> Games -> Mines se ON/OFF, rename, min/max bet, house edge control hota hai."""
import math

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

import fair
from database import balance, cap, debit, ensure_user, finish, fmt, new_round, pref, sess_del, sess_get, sess_set, set_pref
from ui import Btn, Screen, esc, send, show

from .common import (DISABLED, NO_GAME, NOT_ENOUGH, active_screen, alert, bet_error, bet_rows, busy_msg, edge_for,
                     get_bet, is_on, limits, own_session, parse_bet, reply_err)
from .registry import Game, register

router = Router(name="mines")

# ═════════════════ 💣 MINES ═════════════════
GRID = 25
MINE_OPTS = [1, 3, 5, 10]


def mines_mult(m, k, e=None, cp=None):
    e = edge_for("mines") if e is None else e
    cp = cap() if cp is None else cp
    if k > GRID - m:
        return cp
    return min((1 - e) * math.comb(GRID, k) / math.comb(GRID - m, k), cp)


def build_mines(uid):
    v = active_screen(uid)
    if v:
        return v
    m = int(pref(uid, "mines_n", "3"))
    m = m if 1 <= m <= 24 else 3
    rows = bet_rows("mines", uid)
    rows.append([Btn(("✅ " if n == m else "") + f"{n} 💣", f"mn:cnt:{n}", style="success" if n == m else "primary")
                 for n in MINE_OPTS])
    rows.append([Btn("▶️ Start Game", "mn:go", style="success")])
    rows.append([Btn("⬅️ Games", "play", style="primary")])
    return Screen(title="💣 <b>Mines</b>",
                  rows=[("Balance", fmt(balance(uid))), ("Bet", fmt(get_bet(uid, "mines"))), ("Mines", str(m)),
                        ("Top prize", f"{mines_mult(m, GRID - m):,.2f}x")],
                  body=["Open safe tiles 💎 to raise the multiplier. Cash out before you hit a mine!"],
                  buttons=rows)


def mines_start(uid, bet, m):
    v = active_screen(uid)
    if v:
        return v, None
    b = busy_msg(uid)
    if b:
        return None, b
    if not is_on("mines"):
        return None, DISABLED
    err = bet_error(bet, "mines")
    if err:
        return None, err
    if not debit(uid, bet, "Mines"):
        return None, NOT_ENOUGH
    rid, seed, nonce = new_round(uid, "mines", bet)
    s = {"rid": rid, "bet": bet, "m": m, "open": [], "e": edge_for("mines"), "cap": cap(),
         "mines": fair.mines_positions(seed, uid, nonce, m, GRID), "hash": fair.seed_hash(seed)}
    sess_set(uid, "mines", s)
    return mines_screen(uid, s), None


def mines_screen(uid, s, end=None, hit=None, payout=0.0):
    m, bet, opened, rid = s["m"], s["bet"], s["open"], s["rid"]
    k, e, cp = len(opened), s["e"], s["cap"]
    grid = []
    for r in range(5):
        row = []
        for cc in range(5):
            i = r * 5 + cc
            if end:
                if i == hit:
                    row.append(Btn("💥", "noop", style="danger"))
                elif i in s["mines"]:
                    row.append(Btn("💣", "noop", style="danger"))
                elif i in opened:
                    row.append(Btn("💎", "noop", style="success"))
                else:
                    row.append(Btn("▫️", "noop"))
            elif i in opened:
                row.append(Btn("💎", "noop", style="success"))
            else:
                row.append(Btn("⬜", f"mn:t:{rid}:{i}", style="primary"))
        grid.append(row)
    if end:
        mark = "✅" if payout > bet else "❌"
        hi = limits("mines")[1]
        nb = min(round(bet * 2, 2), hi)
        again = [Btn("🔁 Play Again", f"mn:again:{bet:g}:{m}", style="primary")]
        if nb > bet:
            again.append(Btn(f"✖️2 Double ({fmt(nb)})", f"mn:again:{nb:g}:{m}", style="primary"))
        return Screen(title="💣 <b>Mines</b> · Result",
                      rows=[("Mines", str(m)), ("Safe found", f"{k}/{GRID - m}"),
                            ("Bet", f"{fmt(bet)} → {fmt(payout)} {mark}")],
                      buttons=grid + [again, [Btn("🔍 Verify Fairness", f"fair:{rid}")]])
    mult = mines_mult(m, k, e, cp) if k else 0
    rows = [("Bet", fmt(bet)), ("Safe found", f"{k}/{GRID - m}"),
            ("Now", f"{mult:.2f}x = {fmt(bet * mult)}" if k else "—"),
            ("Next", f"{mines_mult(m, k + 1, e, cp):.2f}x")]
    cash = Btn(f"💰 Cashout {fmt(bet * mult)}" if k else "💰 Cashout", f"mn:cash:{rid}", style="success")
    return Screen(title=f"💣 <b>Mines</b> · {m} mines", rows=rows,
                  body=[f"🔐 Seed hash: <code>{s['hash'][:20]}…</code>"], buttons=grid + [[cash]])


async def end_mines(c, uid, s, hit=None):
    sess_del(uid)
    if hit is None:
        payout = round(s["bet"] * mines_mult(s["m"], len(s["open"]), s["e"], s["cap"]), 2)
        finish(uid, "Mines", s["bet"], payout, s["rid"])
        scr = mines_screen(uid, s, "win", payout=payout)
    else:
        finish(uid, "Mines", s["bet"], 0, s["rid"])
        scr = mines_screen(uid, s, "lose", hit=hit)
    await show(c, scr)


@router.message(Command("mines"))
async def mines_cmd(m: Message, command: CommandObject):
    """/mines  ya  /mines <bet> [mines]  -> game seedha start nahi hota, setup screen khulti hai
    (bet / mines pehle se chuni hui). Player 'Start Game' dabaye tab game shuru hota hai."""
    u, _ = ensure_user(m.from_user)
    uid = u["id"]
    args = (command.args or "").split()
    if args:
        bet = parse_bet(args[0], uid)
        err = bet_error(bet, "mines")
        if err:
            return await reply_err(m, err)
        set_pref(uid, "bet", bet)
        if len(args) > 1 and args[1].isdigit() and 1 <= int(args[1]) <= 24:
            set_pref(uid, "mines_n", int(args[1]))
    await send(m.chat.id, build_mines(uid), reply_to=m.message_id)


@router.callback_query(F.data.startswith("mn:cnt:"))
async def mines_cnt(c: CallbackQuery):
    n = int(c.data.split(":")[2])
    if n in MINE_OPTS:
        set_pref(c.from_user.id, "mines_n", n)
    await show(c, build_mines(c.from_user.id))


@router.callback_query(F.data == "mn:menu")
async def mines_menu(c: CallbackQuery):
    await show(c, build_mines(c.from_user.id))


@router.callback_query(F.data == "mn:go")
async def mines_go(c: CallbackQuery):
    uid = c.from_user.id
    m = int(pref(uid, "mines_n", "3"))
    scr, err = mines_start(uid, get_bet(uid, "mines"), m if 1 <= m <= 24 else 3)
    if err:
        return await alert(c, err)
    await show(c, scr)


@router.callback_query(F.data.startswith("mn:again:"))
async def mines_again(c: CallbackQuery):
    _, _, bet, m = c.data.split(":")
    ensure_user(c.from_user)
    m = int(m)
    scr, err = mines_start(c.from_user.id, round(float(bet), 2), m if 1 <= m <= 24 else 3)
    if err:
        return await alert(c, err)
    await show(c, scr)


@router.callback_query(F.data.startswith("mn:t:"))
async def mines_tile(c: CallbackQuery):
    _, _, rid, i = c.data.split(":")
    uid = c.from_user.id
    s = own_session(c, "mines", int(rid))
    if not s:
        return await c.answer(NO_GAME, show_alert=True)
    i = int(i)
    if i in s["open"] or not 0 <= i < GRID:
        return await c.answer()
    if i in s["mines"]:
        return await end_mines(c, uid, s, hit=i)
    s["open"].append(i)
    k = len(s["open"])
    if k == GRID - s["m"] or mines_mult(s["m"], k, s["e"], s["cap"]) >= s["cap"]:
        return await end_mines(c, uid, s)
    sess_set(uid, "mines", s)
    await show(c, mines_screen(uid, s))


@router.callback_query(F.data.startswith("mn:cash:"))
async def mines_cash(c: CallbackQuery):
    s = own_session(c, "mines", int(c.data.split(":")[2]))
    if not s:
        return await c.answer(NO_GAME, show_alert=True)
    if not s["open"]:
        return await c.answer("Open at least 1 tile first.", show_alert=True)
    await end_mines(c, c.from_user.id, s)


# ═════════════════ REGISTER ═════════════════
def resume(uid, s):
    return mines_screen(uid, s)


register(Game(key="mines", title="Mines", build=build_mines, router=router, order=0,
              usage="/mines <bet> [mines]", cmd_desc="/mines <bet> [mines] - Mines", resume=resume))
