"""Admin panel (/admin). Sirf config.py ke ADMIN_IDS ko chalta hai.

Menu: Stats | Users | Casino Name | Branding | Start Card | Bets | Games | Payments | Community | Terms |
      Recent Games | UI mode | Broadcast.
Games page me har game (games/ folder se auto) ke liye ON/OFF, rename aur uski apni settings milti hain,
isliye naya game jodne par yahan kuch nahi badalna.
"""
import asyncio
import math
import re
import time
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from database import DEFAULTS, GROUPS, SPEC, balance, db, fmt, get, links, put, reset, tx, validate
from games.registry import GAMES
import payments
import reports
import tg
from referral import claimable
from ui import Btn, Screen, delete, esc, get_mode, send, send_doc, set_mode, show
from utils import send_home

router = Router()
router.message.filter(F.from_user.id.in_(set(ADMIN_IDS)))
router.callback_query.filter(F.from_user.id.in_(set(ADMIN_IDS)))

MAX_LINKS = 6
UI_MODES = ["inline", "classic", "plain"]
COLS = ["primary", "success"]


class A(StatesGroup):
    setting = State()
    rename = State()
    find = State()
    amount = State()
    bcast = State()
    link = State()
    pay = State()


def P(title="", body=None, buttons=None):
    """Admin screens: hamesha plain HTML + colored buttons."""
    return Screen(title=title, body=body or [], buttons=buttons or [], rich=False)


def menu():
    return P("🛠 <b>Admin Panel</b>", [f"🏷 Casino: <b>{esc(get('brand'))}</b>"], buttons=[
        [Btn("📊 Stats", "a:stats", style="primary"), Btn("👥 Users & PDFs", "a:users", style="primary")],
        [Btn("🏷 Casino Name", "a:s:brand", style="success"), Btn(GROUPS["brand"], "a:g:brand", style="primary")],
        [Btn(GROUPS["card"], "a:g:card", style="success"), Btn(GROUPS["bets"], "a:g:bets", style="primary")],
        [Btn("🎮 Games", "a:games", style="success"), Btn(GROUPS["pay"], "a:g:pay", style="primary")],
        [Btn(GROUPS["ref"], "a:g:ref", style="success"), Btn(GROUPS["stmt"], "a:g:stmt", style="primary")],
        [Btn("🌐 Community Links", "a:com", style="primary"), Btn(GROUPS["terms"], "a:g:terms", style="success")],
        [Btn("🗒 Recent Games", "a:recent", style="primary"), Btn(f"🖥 UI mode: {get_mode()}", "a:ui", style="primary")],
        [Btn("💎 Premium Emojis", "pe:home", style="success"), Btn("👥 Allowed Groups", "gp:home", style="primary")],
        [Btn("📢 Broadcast", "a:bc", style="danger")],
    ])


def back():
    return [Btn("⬅️ Admin Menu", "a:home", style="primary")]


async def need_text(m: Message):
    """State me hain aur command bhej di -> value ki tarah save mat karo."""
    if (m.text or "").startswith("/"):
        await m.answer("Send the value, or /cancel to stop.")
        return True
    return False


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await send(m.chat.id, P("❌ Cancelled.", buttons=[[Btn("🛠 Admin Menu", "a:home", style="primary")]]))


@router.message(Command("admin"))
async def admin_cmd(m: Message, state: FSMContext):
    await state.clear()
    if m.chat.type == "private":
        return await send(m.chat.id, menu())
    # group me /admin: panel hamesha DM me khulta hai, group me nahi
    try:
        await send(m.from_user.id, menu())
    except tg.ApiError as e:
        d = e.desc.lower()
        if e.code == 403 or "chat not found" in d or "can't initiate" in d or "blocked" in d:
            uname = await tg.bot_username()
            return await send(m.chat.id, P(body=["⚠️ Open the bot in DM and press <b>Start</b>, then send /admin again."],
                                           buttons=[[Btn("🤖 Open bot", url=f"https://t.me/{uname}?start=admin", style="primary")]]),
                              reply_to=m.message_id)
        raise
    await delete(m.chat.id, m.message_id)  # group me command hata do (bot ke paas delete right ho to)


@router.message(Command("uimode"))
async def uimode(m: Message, command: CommandObject):
    a = (command.args or "").strip().lower()
    if a in UI_MODES:
        set_mode(a)
    await m.answer(f"UI mode: <b>{get_mode()}</b>\n"
                   "<code>/uimode inline</code> - Rich Message + buttons inside card\n"
                   "<code>/uimode classic</code> - Rich Message + colored buttons below\n"
                   "<code>/uimode plain</code> - normal message + colored buttons\n"
                   "(restart par config.py wala RICH_MODE wapas aa jaata hai)")


@router.callback_query(F.data == "a:home")
async def a_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(c, menu())


@router.callback_query(F.data == "a:ui")
async def a_ui(c: CallbackQuery):
    set_mode(UI_MODES[(UI_MODES.index(get_mode()) + 1) % len(UI_MODES)])
    await show(c, menu(), f"UI mode: {get_mode()}")


# ───────────── STATS ─────────────
def extra_stats():
    r = db("SELECT COALESCE(SUM(ref_pending),0) p, COALESCE(SUM(ref_claimed),0) c FROM users", fetch="one")
    n = db("SELECT COUNT(*) n FROM users WHERE ref_by IS NOT NULL", fetch="one")["n"]
    pay = {x["kind"]: x for x in db("SELECT kind, COUNT(*) n, SUM(amount) s FROM payments "
                                    "WHERE status IN ('Credited','Paid') GROUP BY kind", fetch="all")}
    d, w = pay.get("deposit"), pay.get("withdrawal")
    return (f"💳 Deposits: {d['n'] if d else 0} ({esc(fmt(d['s'] if d else 0))}) · Withdrawals: {w['n'] if w else 0} "
            f"({esc(fmt(w['s'] if w else 0))})\n👥 Referred players: {n} · Unclaimed: {esc(fmt(r['p']))} · Claimed: {esc(fmt(r['c']))}")



@router.callback_query(F.data == "a:stats")
async def a_stats(c: CallbackQuery):
    now = int(time.time())
    t = db("SELECT COUNT(*) n, COALESCE(SUM(balance),0) b, COALESCE(SUM(banned),0) x FROM users", fetch="one")
    today = db("SELECT COUNT(*) n FROM users WHERE joined>?", (now - 86400,), "one")["n"]
    h = db("SELECT COUNT(*) n, COALESCE(SUM(bet),0) b, COALESCE(SUM(payout),0) p FROM history", fetch="one")
    h24 = db("SELECT COALESCE(SUM(bet),0) b, COALESCE(SUM(payout),0) p FROM history WHERE ts>?", (now - 86400,), "one")
    per = db("SELECT game, COUNT(*) n, SUM(bet)-SUM(payout) pr FROM history GROUP BY game", fetch="all")
    games = "\n".join(f"  • {esc(r['game'])}: {r['n']} plays, profit {esc(fmt(r['pr']))}" for r in per) or "  (no games yet)"
    await show(c, P("📊 <b>Stats</b>", [
        f"👥 Users: <b>{t['n']}</b> (🆕 24h: {today}, 🚫 banned: {t['x']})\n"
        f"💰 Total user balance: <b>{esc(fmt(t['b']))}</b>",
        f"🎮 Games played: <b>{h['n']}</b>\n🎯 Total bets: {esc(fmt(h['b']))}\n💸 Total payouts: {esc(fmt(h['p']))}\n"
        f"🏦 House profit: <b>{esc(fmt(h['b'] - h['p']))}</b> (24h: {esc(fmt(h24['b'] - h24['p']))})",
        f"By game:\n{games}", extra_stats()], [back()]))


# ───────────── RECENT GAMES ─────────────
@router.callback_query(F.data == "a:recent")
async def a_recent(c: CallbackQuery):
    rows = db("SELECT h.ts, h.uid, h.game, h.bet, h.payout, h.gid, u.name FROM history h "
              "LEFT JOIN users u ON u.id=h.uid ORDER BY h.ts DESC LIMIT 15", fetch="all")
    lines = []
    for r in rows:
        mark = "✅" if r["payout"] > r["bet"] else "➖" if r["payout"] == r["bet"] else "❌"
        lines.append(f"{mark} {datetime.fromtimestamp(r['ts']).strftime('%d/%m %H:%M')} · {esc((r['name'] or str(r['uid']))[:14])}"
                     f" · {esc(r['game'])} · {esc(fmt(r['bet']))} → {esc(fmt(r['payout']))}"
                     + (f"\n     <code>{esc(r['gid'])}</code>" if r["gid"] else ""))
    await show(c, P("🗒 <b>Recent Games</b>", ["\n".join(lines) or "No games yet."], [back()]))


# ───────────── SETTINGS (group pages + game pages) ─────────────
def short(key):
    kind = SPEC[key][0]
    v = get(key)
    if kind == "bool":
        return "ON" if v == "1" else "OFF"
    if v == "":
        return "default"
    return v if len(v) <= 16 else v[:15] + "…"


def btn_text(key):
    label = DEFAULTS[key][1]
    label = label if len(label) <= 34 else label[:33] + "…"
    return f"{label} · {short(key)}"


def keys_of(group):
    return [k for k, (_, g) in SPEC.items() if g == group]


def group_page(group):
    rows = [[Btn(btn_text(k), f"a:s:{k}", style=COLS[i % 2])] for i, k in enumerate(keys_of(group))]
    if group == "card":
        rows.append([Btn("👁 Preview my card", "a:cardprev", style="success")])
    rows.append(back())
    return P(GROUPS.get(group, "⚙️ Settings"), ["Tap what you want to change:"], rows)


def game_page(key):
    g = db("SELECT * FROM games WHERE key=?", (key,), "one")
    title = g["title"] if g else key
    rows = [[Btn(f"{'🟢 ON' if g and g['enabled'] else '🔴 OFF'} · tap to switch", f"a:gt:{key}:p",
                 style="success" if g and g["enabled"] else "danger"),
             Btn("✏️ Rename", f"a:gr:{key}", style="primary")]]
    rows += [[Btn(btn_text(k), f"a:s:{k}", style=COLS[i % 2])]
             for i, k in enumerate(keys_of(f"game:{key}"))]
    rows.append([Btn("⬅️ Games", "a:games", style="primary")])
    return P(f"🎮 <b>{esc(title)}</b> settings", ["Empty/default min, max & edge = global Bets & Payout settings."], rows)


def page_for(key):
    grp = SPEC[key][1]
    return game_page(grp[5:]) if grp.startswith("game:") else group_page(grp)


@router.callback_query(F.data.startswith("a:g:"))
async def a_group(c: CallbackQuery, state: FSMContext):
    await state.clear()
    grp = c.data[4:]
    if grp in GROUPS:
        await show(c, group_page(grp))
    else:
        await c.answer()


@router.callback_query(F.data == "a:cardprev")
async def a_cardprev(c: CallbackQuery):
    await c.answer("Generating preview...")
    await send_home(c.message.chat.id, c.from_user)


@router.callback_query(F.data.startswith("a:s:"))
async def a_set_pick(c: CallbackQuery, state: FSMContext):
    key = c.data[4:]
    if key not in DEFAULTS:
        return await c.answer()
    kind = SPEC[key][0]
    if kind == "bool":  # tap = switch
        put(key, "0" if get(key) == "1" else "1")
        return await show(c, page_for(key), f"{short(key)}")
    if kind.startswith("choice:"):  # tap = next option
        opts = kind[7:].split(",")
        put(key, opts[(opts.index(get(key)) + 1) % len(opts)] if get(key) in opts else opts[0])
        return await show(c, page_for(key), f"{short(key)}")
    await state.set_state(A.setting)
    await state.update_data(key=key)
    hint = {"num": "number (0 or more)", "edge": "number 0-50", "mult": "number 1 or more", "url": "link starting with https://",
            "presets": "numbers like 1,5,10,50,100"}.get(kind.split(":")[0], "")
    await send(c.message.chat.id, P(f"✏️ <b>{esc(DEFAULTS[key][1])}</b>", [
        f"Current:\n<code>{esc(get(key)) or '(empty)'}</code>",
        "Send the new value" + (f" ({hint})" if hint else "") + ". Send <code>-</code> to reset to default. /cancel to stop."]))
    await c.answer()


@router.message(A.setting)
async def a_set_save(m: Message, state: FSMContext):
    if await need_text(m):
        return
    key = (await state.get_data())["key"]
    val = (m.text or "").strip()
    if val == "-":
        reset(key)
    elif not val or not validate(key, val):
        return await m.answer("❌ Invalid value for this setting. Try again or /cancel.")
    else:
        put(key, val)
    await state.clear()
    scr = page_for(key)
    scr.title = f"✅ Updated · {scr.title}"
    await send(m.chat.id, scr)


# ───────────── GAMES ─────────────
def games_panel():
    rows = []
    for g in db("SELECT * FROM games ORDER BY sort", fetch="all"):
        rows.append([Btn(f"{'🟢 ON' if g['enabled'] else '🔴 OFF'} • {g['title']}", f"a:gt:{g['key']}",
                         style="success" if g["enabled"] else "danger"),
                     Btn("⚙️ Settings", f"a:gs:{g['key']}", style="primary")])
    rows.append(back())
    return P("🎮 <b>Games</b>", ["Switch ON/OFF, or open ⚙️ Settings for a game (rename, bets, dice rules...)."], rows)


@router.callback_query(F.data == "a:games")
async def a_games(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(c, games_panel())


@router.callback_query(F.data.startswith("a:gs:"))
async def a_game_settings(c: CallbackQuery):
    await show(c, game_page(c.data[5:]))


@router.callback_query(F.data.startswith("a:gt:"))
async def a_game_toggle(c: CallbackQuery):
    parts = c.data.split(":")
    db("UPDATE games SET enabled=1-enabled WHERE key=?", (parts[2],))
    await show(c, game_page(parts[2]) if len(parts) > 3 else games_panel())


@router.callback_query(F.data.startswith("a:gr:"))
async def a_game_rename(c: CallbackQuery, state: FSMContext):
    await state.set_state(A.rename)
    await state.update_data(key=c.data[5:])
    await send(c.message.chat.id, P(body=["✏️ Send the new game name (/cancel to stop):"]))
    await c.answer()


@router.message(A.rename)
async def a_game_rename_save(m: Message, state: FSMContext):
    if await need_text(m):
        return
    key = (await state.get_data())["key"]
    name = (m.text or "").strip()[:20]
    if not name:
        return await m.answer("❌ Name can't be empty.")
    db("UPDATE games SET title=? WHERE key=?", (name, key))
    await state.clear()
    await send(m.chat.id, game_page(key))


# ───────────── COMMUNITY LINKS (add / remove) ─────────────
def community_panel():
    ls = links()
    lines = [f"{i}. <b>{esc(r['label'])}</b>\n<code>{esc(r['url'])}</code>" for i, r in enumerate(ls, 1)]
    rows = []
    if len(ls) < MAX_LINKS:
        rows.append([Btn("➕ Add Link", "a:la", style="success")])
    for r in ls:
        rows.append([Btn(f"🗑 Remove: {r['label'][:22]}", f"a:lr:{r['id']}", style="danger")])
    rows.append(back())
    body = ["\n\n".join(lines) if lines else "No links yet. Community button will stay hidden until you add one.",
            f"Max {MAX_LINKS} links. They show as colored buttons under 🌐 Community."]
    return P("🌐 <b>Community Links</b>", body, rows)


def parse_link(text):
    label, _, url = text.rpartition("|")
    url, label = url.strip(), label.strip() or "🌐 Community"
    if url.startswith("@"):
        url = "https://t.me/" + url[1:]
    elif url.lower().startswith("t.me/"):
        url = "https://" + url
    if not re.match(r"^https?://\S+$", url):
        return None
    return label[:30], url


@router.callback_query(F.data == "a:com")
async def a_com(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(c, community_panel())


@router.callback_query(F.data == "a:la")
async def a_link_add(c: CallbackQuery, state: FSMContext):
    if len(links()) >= MAX_LINKS:
        return await c.answer(f"Max {MAX_LINKS} links. Remove one first.", show_alert=True)
    await state.set_state(A.link)
    await send(c.message.chat.id, P("➕ <b>Add community link</b>", [
        "Send the link:\n<code>https://t.me/yourgroup</code>\n\n"
        "Or with a button name:\n<code>Join Channel | https://t.me/yourchannel</code>\n\n/cancel to stop."]))
    await c.answer()


@router.message(A.link)
async def a_link_save(m: Message, state: FSMContext):
    if await need_text(m):
        return
    p = parse_link((m.text or "").strip())
    if not p:
        return await m.answer("❌ Send a valid link starting with https:// (or @username). Try again or /cancel.")
    if len(links()) >= MAX_LINKS:
        await state.clear()
        return await m.answer(f"Max {MAX_LINKS} links reached.")
    db("INSERT INTO links(label,url) VALUES(?,?)", p)
    await state.clear()
    await send(m.chat.id, community_panel())


@router.callback_query(F.data.startswith("a:lr:"))
async def a_link_remove(c: CallbackQuery):
    db("DELETE FROM links WHERE id=?", (int(c.data[5:]),))
    await show(c, community_panel(), "🗑 Removed")


# ───────────── USERS ─────────────
def user_panel(u):
    from database import wager_left
    nref = db("SELECT COUNT(*) n FROM users WHERE ref_by=?", (u["id"],), "one")["n"]
    body = [f"👤 <b>{esc(u['name'])}</b> @{esc(u['username'] or '-')}\n🆔 <code>{u['id']}</code>",
            f"💰 Balance: <b>{esc(fmt(u['balance']))}</b>\n🎯 Wagered: {esc(fmt(u['wagered']))}\n"
            f"🔒 Wager left to unlock: {esc(fmt(wager_left(u['id'])))}\n🚫 Banned: {'Yes' if u['banned'] else 'No'}",
            f"👥 Referrals: {nref} · Referred by: <code>{u['ref_by'] or '-'}</code>\n"
            f"🎁 Ready to claim: {esc(fmt(claimable(u)))} · Claimed: {esc(fmt(u['ref_claimed'] or 0))}"]
    i = u["id"]
    return P("", body, [
        [Btn("➕ Add Balance", f"a:bal:{i}:add", style="success"), Btn("➖ Deduct", f"a:bal:{i}:sub", style="danger")],
        [Btn("📥 Record Deposit", f"a:rec:{i}:deposit", style="success"), Btn("📤 Record Withdrawal", f"a:rec:{i}:withdrawal", style="primary")],
        [Btn("🎮 Games PDF", f"a:pdf:g:{i}", style="primary"), Btn("👥 Refer PDF", f"a:pdf:r:{i}", style="primary")],
        [Btn("💳 Payments PDF", f"a:pdf:p:{i}", style="primary"), Btn("📒 Statement PDF", f"a:pdf:s:{i}", style="primary")],
        [Btn("✅ Unban" if u["banned"] else "🚫 Ban", f"a:ban:{i}", style="primary" if u["banned"] else "danger")],
        back()])


@router.callback_query(F.data == "a:users")
async def a_users(c: CallbackQuery, state: FSMContext):
    await state.set_state(A.find)
    await send(c.message.chat.id, P(body=["🔎 Send user ID or @username (/cancel to stop):"]))
    await c.answer()


@router.message(A.find)
async def a_find(m: Message, state: FSMContext):
    if await need_text(m):
        return
    s = (m.text or "").strip().lstrip("@")
    u = db("SELECT * FROM users WHERE id=?", (int(s),), "one") if s.isdigit() else \
        db("SELECT * FROM users WHERE LOWER(username)=?", (s.lower(),), "one")
    if not u:
        return await m.answer("❌ User not found. Try again or /cancel.")
    await state.clear()
    await send(m.chat.id, user_panel(u))


@router.callback_query(F.data.startswith("a:ban:"))
async def a_ban(c: CallbackQuery):
    uid = int(c.data[6:])
    db("UPDATE users SET banned=1-banned WHERE id=?", (uid,))
    await show(c, user_panel(db("SELECT * FROM users WHERE id=?", (uid,), "one")))


@router.callback_query(F.data.startswith("a:bal:"))
async def a_bal(c: CallbackQuery, state: FSMContext):
    _, _, uid, mode = c.data.split(":")
    await state.set_state(A.amount)
    await state.update_data(uid=int(uid), mode=mode)
    await send(c.message.chat.id, P(body=[f"💰 Send amount to {'add' if mode == 'add' else 'deduct'} (/cancel to stop):"]))
    await c.answer()


@router.message(A.amount)
async def a_amount(m: Message, state: FSMContext, bot: Bot):
    if await need_text(m):
        return
    try:
        amt = round(float((m.text or "").strip()), 2)
    except ValueError:
        return await m.answer("❌ Send a number.")
    if not math.isfinite(amt) or amt <= 0 or amt > 1_000_000_000:
        return await m.answer("❌ Amount must be a positive number (max 1,000,000,000).")
    d = await state.get_data()
    old = balance(d["uid"])
    new = max(0.0, round(old + (amt if d["mode"] == "add" else -amt), 2))
    delta = round(new - old, 2)
    db("UPDATE users SET balance=? WHERE id=?", (new, d["uid"]))
    db("INSERT INTO ledger VALUES(?,?,?,?,?)", (int(time.time()), d["uid"], delta, "admin " + d["mode"], m.from_user.id))
    tx(d["uid"], "Admin Credit" if delta >= 0 else "Admin Debit", delta, "Admin adjustment")
    await state.clear()
    scr = user_panel(db("SELECT * FROM users WHERE id=?", (d["uid"],), "one"))
    scr.title = "✅ <b>Done</b>"
    await send(m.chat.id, scr)
    try:
        await bot.send_message(d["uid"], f"💰 Your balance was updated: {'+' if delta >= 0 else '-'}{esc(fmt(abs(delta)))}")
    except Exception:
        pass


PDFS = {"g": ("games_pdf", "games", "Game History"), "r": ("referral_pdf", "referrals", "Referral Portfolio"),
        "p": ("payments_pdf", "payments", "Payment History"), "s": ("statement_pdf", "statement", "Account Statement")}


@router.callback_query(F.data.startswith("a:pdf:"))
async def a_pdf(c: CallbackQuery):
    _, _, k, uid = c.data.split(":")
    u = db("SELECT * FROM users WHERE id=?", (int(uid),), "one")
    if k not in PDFS or not u:
        return await c.answer("User not found", show_alert=True)
    await c.answer("Preparing PDF...")
    fn, name, label = PDFS[k]
    data = await asyncio.to_thread(getattr(reports, fn), u)
    await send_doc(c.message.chat.id, data, f"{name}_{uid}.pdf", f"📄 <b>{label}</b> · <code>{uid}</code> · {esc(u['name'] or '')}")


@router.callback_query(F.data.startswith("a:rec:"))
async def a_rec(c: CallbackQuery, state: FSMContext):
    _, _, uid, kind = c.data.split(":")
    await state.set_state(A.pay)
    await state.update_data(uid=int(uid), kind=kind)
    ex = "25 USDT_POLYGON 0x70aa...f3" if kind == "deposit" else "20 USDT_POLYGON 0xabc...  (end me status: paid / pending / cancelled)"
    await send(c.message.chat.id, P(body=[f"{'📥 Deposit' if kind == 'deposit' else '📤 Withdrawal'} record.\n"
                                         f"Send: <code>amount asset [tx hash] [status]</code>\nExample: <code>{ex}</code>\n"
                                         f"Deposit balance badhata hai, withdrawal balance ghatata hai (cancelled = no change). /cancel to stop."]))
    await c.answer()


@router.message(A.pay)
async def a_rec_save(m: Message, state: FSMContext, bot: Bot):
    if await need_text(m):
        return
    parts = (m.text or "").split()
    if len(parts) < 2:
        return await m.answer("❌ Format: amount asset [tx hash] [status]")
    try:
        amt = float(parts[0])
    except ValueError:
        return await m.answer("❌ Amount must be a number.")
    d = await state.get_data()
    status = None
    if parts[-1].lower() in ("paid", "pending", "cancelled", "credited") and len(parts) > 2:
        status = parts.pop().title()
    ok, res = payments.add_payment(d["uid"], d["kind"], amt, parts[1][:24].upper(), status, " ".join(parts[2:])[:120])
    if not ok:
        return await m.answer(f"❌ {res}")
    await state.clear()
    scr = user_panel(db("SELECT * FROM users WHERE id=?", (d["uid"],), "one"))
    scr.title = f"✅ <b>{'Deposit' if d['kind'] == 'deposit' else 'Withdrawal'} recorded</b>"
    await send(m.chat.id, scr)
    try:
        await bot.send_message(d["uid"], (f"✅ Deposit credited: <b>{esc(fmt(amt))}</b> ({esc(parts[1].upper())})" if d["kind"] == "deposit"
                                           else f"📤 Withdrawal {esc((status or 'Paid').lower())}: <b>{esc(fmt(amt))}</b> ({esc(parts[1].upper())})"))
    except Exception:
        pass


# ───────────── BROADCAST ─────────────
@router.callback_query(F.data == "a:bc")
async def a_bc(c: CallbackQuery, state: FSMContext):
    await state.set_state(A.bcast)
    await send(c.message.chat.id, P(body=["📢 Send the message to broadcast (text / photo / anything). /cancel to stop."]))
    await c.answer()


@router.message(A.bcast)
async def a_bc_send(m: Message, state: FSMContext):
    if await need_text(m):
        return
    await state.clear()
    ids = [r["id"] for r in db("SELECT id FROM users WHERE banned=0", fetch="all")]
    ok = 0
    status = await m.answer(f"📤 Sending to {len(ids)} users...")
    for uid in ids:
        try:
            await m.copy_to(uid)
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                await m.copy_to(uid)
                ok += 1
            except Exception:
                pass
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Broadcast done. Delivered: {ok}/{len(ids)}")