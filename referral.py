"""Refer & Earn. /refer (card) | /referpdf (PDF) | Claim button.
Kaise kamata hai referrer: referred player jitna bet lagata hai uska X% (ref_wager_pct) aur deposit ka Y% (ref_deposit_pct).
Claim karne par paisa balance me aata hai aur utna x (ref_claim_mult) wager karna padta hai (database.wager_left(uid)).
Sab kuch admin panel -> Referral System se control hota hai."""
import asyncio
import math
import time
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import qr
import refcard
import reports
import tg
from database import credit, db, ensure_user, fget, fmt, get
from ui import Btn, Screen, edit_card, esc, send_card, send_doc
from utils import cb_chat, deliver

router = Router(name="referral")


def link_for(uname, uid):
    return f"https://t.me/{uname}?start=r-{uid}"


def attach(uid, ref_id):
    """Naye user ko referrer se jodo (sirf pehli baar). -> True agar juda."""
    if get("ref_enabled") != "1" or ref_id == uid:
        return False
    r = db("SELECT ref_by FROM users WHERE id=?", (ref_id,), "one")
    if not r or r["ref_by"] == uid:
        return False
    cur = db("UPDATE users SET ref_by=?, ref_ts=? WHERE id=? AND ref_by IS NULL", (ref_id, int(time.time()), uid))
    return cur.rowcount == 1


def stats(uid):
    u = db("SELECT * FROM users WHERE id=?", (uid,), "one")
    n = db("SELECT COUNT(*) n FROM users WHERE ref_by=?", (uid,), "one")["n"]
    sums = {r["kind"]: r["s"] for r in db("SELECT kind, SUM(amount) s FROM ref_earn WHERE referrer=? GROUP BY kind", (uid,), "all")}
    top = []
    for r in db("SELECT referred, SUM(amount) e FROM ref_earn WHERE referrer=? GROUP BY referred ORDER BY e DESC LIMIT 3", (uid,), "all"):
        p = db("SELECT name, joined, ref_ts FROM users WHERE id=?", (r["referred"],), "one")
        since = (p["ref_ts"] or p["joined"] or 0) if p else 0
        w = db("SELECT COALESCE(SUM(bet),0) s FROM history WHERE uid=? AND ts>=?", (r["referred"], since), "one")["s"]
        d = db("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE uid=? AND kind='deposit' AND status='Credited' AND ts>=?",
               (r["referred"], since), "one")["s"]
        top.append(((p["name"] if p else str(r["referred"]))[:14], r["e"], w, d))
    today = int(time.time() // 86400)
    per_day = {r["d"]: r["s"] for r in db("SELECT ts/86400 d, SUM(amount) s FROM ref_earn WHERE referrer=? AND ts>=? GROUP BY d",
                                          (uid, (today - 6) * 86400), "all")}
    days = [(datetime.fromtimestamp((today - 6 + i) * 86400, timezone.utc).strftime("%d %b"), per_day.get(today - 6 + i, 0.0))
            for i in range(7)]
    return dict(u=u, n=n, ew=sums.get("wager", 0.0), ed=sums.get("deposit", 0.0), top=top, days=days)


def claimable(u):
    return math.floor((u["ref_pending"] or 0) * 100) / 100


def claim(uid):
    """-> (ok, message)"""
    u = db("SELECT * FROM users WHERE id=?", (uid,), "one")
    amt = claimable(u)
    need = max(fget("ref_min_claim", 0.01), 0.01)
    if amt < need:
        return False, f"Minimum claim is {fmt(need)}. Ready: {fmt(amt)}."
    mult = fget("ref_claim_mult", 2.0)
    cur = db("UPDATE users SET ref_pending=ref_pending-?, ref_claimed=ROUND(ref_claimed+?,2), wager_req=ROUND(wager_req+?,2) "
             "WHERE id=? AND ref_pending>=?", (amt, amt, amt * mult, uid, amt))
    if cur.rowcount != 1:
        return False, "Nothing to claim."
    credit(uid, amt, kind="Referral Claim", note="Referral earnings")
    return True, f"✅ Claimed {fmt(amt)}" + (f" — wager {fmt(amt * mult)} ({mult:g}x) to unlock withdrawal." if mult > 0 else "")


async def build(tgu):
    """-> (png, Screen) referral card."""
    ensure_user(tgu)
    st = stats(tgu.id)
    u = st["u"]
    uname = await tg.bot_username()
    link = link_for(uname, tgu.id)
    av = await tg.avatar(tgu.id) if get("card_avatar") == "1" else None
    png = await asyncio.to_thread(
        refcard.render, get("brand"), get("ref_title"), (tgu.full_name or tgu.first_name or "Player")[:22], tgu.username or "",
        av, st["n"], claimable(u), fget("ref_claim_mult", 2.0), tgu.id, link, get("currency"), get("ref_theme"),
        st["ew"], st["ed"], u["ref_claimed"] or 0, fget("ref_wager_pct", 0), fget("ref_deposit_pct", 0), st["top"], st["days"])
    body = [f"<b>Referral link:</b> {esc(link)}"]
    if get("ref_group_link"):
        body.append(f"<b>Group invite:</b> {esc(get('ref_group_link'))}")
    body.append("<b>Report:</b> /referpdf")
    ready = claimable(u)
    can = ready >= max(fget("ref_min_claim", 0.01), 0.01)
    share = f"https://t.me/share/url?url={link}&text=Join%20me%20and%20play!"
    scr = Screen(body=["\n".join(body)], buttons=[
        [Btn(f"💰 Claim {fmt(ready)}", "ref:claim", style="success" if can else "primary")],
        [Btn("📄 Report PDF", "ref:pdf", style="primary"), Btn("📤 Share link", url=share, style="primary")]])
    return png, scr


async def _send_card(chat, tgu, reply=None):
    png, scr = await build(tgu)
    await send_card(chat, png, scr, reply)


async def send_pdf(chat, u, reply=None):
    data = await asyncio.to_thread(reports.referral_pdf, u)
    await send_doc(chat, data, f"referrals_{u['id']}.pdf", "👥 <b>Your Private Referral Portfolio</b>", reply)


async def _disabled(m):
    from ui import send
    await send(m.chat.id, Screen(rich=False, body=["🛠 The referral program is currently off."]), reply_to=m.message_id)


@router.message(Command("refer"))
async def cmd_refer(m: Message):
    ensure_user(m.from_user)
    if get("ref_enabled") != "1":
        return await _disabled(m)
    await deliver(m, lambda chat, reply: _send_card(chat, m.from_user, reply))


@router.message(Command("referpdf"))
async def cmd_referpdf(m: Message):
    u, _ = ensure_user(m.from_user)
    if get("ref_enabled") != "1":
        return await _disabled(m)
    await deliver(m, lambda chat, reply: send_pdf(chat, u, reply))


@router.callback_query(F.data == "ref:open")
async def open_refer(c: CallbackQuery):
    if get("ref_enabled") != "1":
        return await c.answer("🛠 Referral program is off.", show_alert=True)
    await _send_card(cb_chat(c), c.from_user)
    await c.answer("Sent" if cb_chat(c) != c.message.chat.id else None)


@router.callback_query(F.data == "ref:pdf")
async def cb_pdf(c: CallbackQuery):
    u, _ = ensure_user(c.from_user)
    await c.answer("Preparing PDF...")
    await send_pdf(cb_chat(c), u)


@router.callback_query(F.data == "ref:claim")
async def cb_claim(c: CallbackQuery):
    ensure_user(c.from_user)
    ok, msg = claim(c.from_user.id)
    await c.answer(msg.replace("<b>", "").replace("</b>", ""), show_alert=True)
    if ok:  # card refresh
        png, scr = await build(c.from_user)
        await edit_card(c.message.chat.id, c.message.message_id, png, scr)
