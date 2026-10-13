"""Tower game. Is game me kuch badalna ho to sirf yahi file edit karo.
Admin panel -> Games -> Tower se ON/OFF, rename, min/max bet, house edge control hota hai."""
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

router = Router(name="tower")

# ═════════════════ 🗼 TOWER ═════════════════
LEVELS = 9
DIFFS = {"easy": (4, "🟢 Easy"), "medium": (3, "🟡 Medium"), "hard": (2, "🔴 Hard")}


def tower_mult(n, k, e=None, cp=None):
    e = edge_for("tower") if e is None else e
    cp = cap() if cp is None else cp
    return min((1 - e) * (n / (n - 1)) ** k, cp)


def build_tower(uid):
    v = active_screen(uid)
    if v:
        return v
    bet = get_bet(uid, "tower")
    d = pref(uid, "tower_d", "easy")
    d = d if d in DIFFS else "easy"
    n = DIFFS[d][0]
    rows = bet_rows("tower", uid)
    rows.append([Btn(("✅ " if k == d else "") + label, f"tw:diff:{k}", style="success" if k == d else "primary")
                 for k, (_, label) in DIFFS.items()])
    rows.append([Btn("▶️ Start Game", "tw:go", style="success")])
    rows.append([Btn("⬅️ Games", "play", style="primary")])
    return Screen(title="🗼 <b>Tower</b>",
                  rows=[("Balance", fmt(balance(uid))), ("Bet", fmt(bet)),
                        ("Difficulty", f"{DIFFS[d][1]} ({n} tiles, 1 bomb)"),
                        ("Top prize", f"{tower_mult(n, LEVELS):,.2f}x")],
                  body=[f"Climb {LEVELS} floors. Pick a safe tile on each floor, cash out anytime!"],
                  buttons=rows)


def tower_start(uid, bet, d):
    """-> (Screen, None) ya (None, error_text)"""
    v = active_screen(uid)
    if v:
        return v, None
    b = busy_msg(uid)
    if b:
        return None, b
    if not is_on("tower"):
        return None, DISABLED
    err = bet_error(bet, "tower")
    if err:
        return None, err
    if not debit(uid, bet, "Tower"):
        return None, NOT_ENOUGH
    n = DIFFS[d][0]
    rid, seed, nonce = new_round(uid, "tower", bet)
    s = {"rid": rid, "bet": bet, "d": d, "n": n, "path": [], "e": edge_for("tower"), "cap": cap(),
         "bombs": fair.tower_bombs(seed, uid, nonce, n, LEVELS), "hash": fair.seed_hash(seed)}
    sess_set(uid, "tower", s)
    return tower_screen(uid, s), None


def tower_screen(uid, s, end=None, payout=0.0):
    n, bet, path, bombs, rid = s["n"], s["bet"], s["path"], s["bombs"], s["rid"]
    k, e, cp = len(path), s["e"], s["cap"]
    grid = []
    for L in range(LEVELS, 0, -1):
        i = L - 1
        row = []
        for col in range(n):
            if end:
                if col == bombs[i]:
                    row.append(Btn("💥" if (end == "lose" and i == k) else "💀", "noop", style="danger"))
                elif i < k and col == path[i]:
                    row.append(Btn("🌴", "noop", style="success"))
                else:
                    row.append(Btn("🏝", "noop"))
            elif i < k:
                hit = col == path[i]
                row.append(Btn("🌴" if hit else "🏝", "noop", style="success" if hit else None))
            elif i == k:
                row.append(Btn("❓", f"tw:p:{rid}:{col}", style="primary"))
            else:
                row.append(Btn("🏝", "noop"))
        grid.append(row)

    if end:
        reached = k + 1 if end == "lose" else k
        mark = "✅" if payout > bet else "❌"
        hi = limits("tower")[1]
        nb = min(round(bet * 2, 2), hi)
        again = [Btn("🔁 Play Again", f"tw:again:{bet:g}:{s['d']}", style="primary")]
        if nb > bet:
            again.append(Btn(f"✖️2 Double ({fmt(nb)})", f"tw:again:{nb:g}:{s['d']}", style="primary"))
        return Screen(title="🗼 <b>Tower</b> · Result",
                      rows=[("Reached", f"Floor {reached}"), ("Bet", f"{fmt(bet)} → {fmt(payout)} {mark}")],
                      buttons=grid + [again, [Btn("🔍 Verify Fairness", f"fair:{rid}")]])

    mult = tower_mult(n, k, e, cp) if k else 0
    rows = [("Bet", fmt(bet)), ("Floor", f"{k + 1}/{LEVELS}"),
            ("Now", f"{mult:.2f}x = {fmt(bet * mult)}" if k else "—"),
            ("Next", f"{tower_mult(n, k + 1, e, cp):.2f}x")]
    cash = Btn(f"💰 Cashout {fmt(bet * mult)}" if k else "💰 Cashout", f"tw:cash:{rid}", style="success")
    return Screen(title=f"🗼 <b>Tower</b> · {DIFFS[s['d']][1]}", rows=rows,
                  body=[f"🔐 Seed hash: <code>{s['hash'][:20]}…</code>"],
                  buttons=grid + [[cash]])


async def end_tower(c, uid, s, lose=False):
    sess_del(uid)
    if lose:
        finish(uid, "Tower", s["bet"], 0, s["rid"])
        scr = tower_screen(uid, s, "lose")
    else:
        payout = round(s["bet"] * tower_mult(s["n"], len(s["path"]), s["e"], s["cap"]), 2)
        finish(uid, "Tower", s["bet"], payout, s["rid"])
        scr = tower_screen(uid, s, "win", payout)
    await show(c, scr)


@router.message(Command("tower"))
async def tower_cmd(m: Message, command: CommandObject):
    """/tower  ya  /tower <bet> [easy|medium|hard]  -> setup screen (game 'Start Game' dabane par shuru)."""
    u, _ = ensure_user(m.from_user)
    uid = u["id"]
    args = (command.args or "").split()
    if args:
        bet = parse_bet(args[0], uid)
        err = bet_error(bet, "tower")
        if err:
            return await reply_err(m, err)
        set_pref(uid, "bet", bet)
        if len(args) > 1 and args[1].lower() in DIFFS:
            set_pref(uid, "tower_d", args[1].lower())
    await send(m.chat.id, build_tower(uid), reply_to=m.message_id)


@router.callback_query(F.data.startswith("tw:diff:"))
async def tower_diff(c: CallbackQuery):
    d = c.data.split(":")[2]
    if d in DIFFS:
        set_pref(c.from_user.id, "tower_d", d)
    await show(c, build_tower(c.from_user.id))


@router.callback_query(F.data == "tw:menu")
async def tower_menu(c: CallbackQuery):
    await show(c, build_tower(c.from_user.id))


@router.callback_query(F.data == "tw:go")
async def tower_go(c: CallbackQuery):
    uid = c.from_user.id
    d = pref(uid, "tower_d", "easy")
    scr, err = tower_start(uid, get_bet(uid, "tower"), d if d in DIFFS else "easy")
    if err:
        return await alert(c, err)
    await show(c, scr)


@router.callback_query(F.data.startswith("tw:again:"))
async def tower_again(c: CallbackQuery):
    _, _, bet, d = c.data.split(":")
    ensure_user(c.from_user)
    scr, err = tower_start(c.from_user.id, round(float(bet), 2), d if d in DIFFS else "easy")
    if err:
        return await alert(c, err)
    await show(c, scr)


@router.callback_query(F.data.startswith("tw:p:"))
async def tower_pick(c: CallbackQuery):
    _, _, rid, col = c.data.split(":")
    uid = c.from_user.id
    s = own_session(c, "tower", int(rid))
    if not s:
        return await c.answer(NO_GAME, show_alert=True)
    col = int(col)
    if col < 0 or col >= s["n"]:
        return await c.answer()
    if col == s["bombs"][len(s["path"])]:
        return await end_tower(c, uid, s, lose=True)
    s["path"].append(col)
    k = len(s["path"])
    if k == LEVELS or tower_mult(s["n"], k, s["e"], s["cap"]) >= s["cap"]:
        return await end_tower(c, uid, s)
    sess_set(uid, "tower", s)
    await show(c, tower_screen(uid, s))


@router.callback_query(F.data.startswith("tw:cash:"))
async def tower_cash(c: CallbackQuery):
    s = own_session(c, "tower", int(c.data.split(":")[2]))
    if not s:
        return await c.answer(NO_GAME, show_alert=True)
    if not s["path"]:
        return await c.answer("Climb at least 1 floor first.", show_alert=True)
    await end_tower(c, c.from_user.id, s)


# ═════════════════ REGISTER ═════════════════
def resume(uid, s):
    return tower_screen(uid, s)


register(Game(key="tower", title="Tower", build=build_tower, router=router, order=2,
              usage="/tower <bet>", cmd_desc="/tower <bet> - Tower", resume=resume))
