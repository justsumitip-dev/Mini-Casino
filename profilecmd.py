"""/profile  -> photo card (level, wager rank, stats) + 'Change Theme' button.

Theme user ke hisaab se save hota hai (prefs 'ptheme'). Card design: profilecard.py
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import profilecard as pc
import tg
from cardimg import _clean
from database import db, ensure_user, get, pref, set_pref
from ui import Btn, Screen, delete, edit_card, esc, kb_json, send, send_card

log = logging.getLogger(__name__)
router = Router(name="profile")


def theme_of(uid):
    t = pref(uid, "ptheme", pc.DEFAULT_THEME)
    return t if t in pc.THEMES else pc.DEFAULT_THEME


def main_buttons(back):
    rows = [[Btn("🎨 Change Theme", "pf:th", style="success")],
            [Btn("📒 Statement", "st:open", style="primary"), Btn("💳 Payments", "pay:open", style="primary")],
            [Btn("👥 Refer & Earn", "ref:open", style="success")]]
    if back:
        rows.append([Btn("⬅️ Back", "home", style="primary")])
    return rows


def picker_buttons(cur):
    ids = pc.theme_ids()
    rows = []
    for i in range(0, len(ids), 2):
        rows.append([Btn(("✅ " if t == cur else "") + pc.THEMES[t]["label"], f"pf:t:{t}",
                         style="success" if t == cur else "primary") for t in ids[i:i + 2]])
    rows.append([Btn("✔ Done", "pf:done", style="success")])
    return rows


def caption(u, tgu, theme):
    li = pc.level_info(u["wagered"])
    name = _clean(tgu.full_name, 24) or "Player"
    return Screen(rich=False, title=f"👤 <b>{esc(name)}</b> · {li['tier']} L{li['level']}",
                  body=[f"Theme: <b>{esc(pc.THEMES[theme]['label'])}</b>"])


async def make_png(u, tgu, theme):
    li = pc.level_info(u["wagered"])
    h = db("SELECT COUNT(*) n, COALESCE(SUM(payout>bet),0) w, COALESCE(SUM(payout),0) tw, COALESCE(SUM(bet),0) tb, "
           "COALESCE(MAX(payout-bet),0) bw FROM history WHERE uid=?", (u["id"],), "one")
    rank = None
    if u["wagered"] > 0:
        rank = db("SELECT COUNT(*)+1 c FROM users WHERE wagered>?", (u["wagered"],), "one")["c"]
    av = await tg.avatar(tgu.id) if get("card_avatar") == "1" else None
    p = dict(brand=get("brand"), name=_clean(tgu.full_name, 22) or _clean(tgu.first_name, 22) or "Player",
             username=_clean(tgu.username or "", 24), uid=u["id"], joined=u["joined"], cur=get("currency"),
             tier=li["tier"], level=li["level"], next_label=li["next_label"], progress=li["progress"],
             target=li["target"], wagered=u["wagered"], rank=f"#{rank}" if rank else "—",
             games=h["n"], winrate=(100.0 * h["w"] / h["n"]) if h["n"] else 0.0, biggest=max(h["bw"], 0),
             balance=u["balance"], total_won=h["tw"], net=h["tw"] - h["tb"])
    return await asyncio.to_thread(pc.render, p, theme, av)


async def send_profile(chat_id, tgu, reply_to=None, back=False):
    u, _ = ensure_user(tgu)
    th = theme_of(u["id"])
    png = await make_png(u, tgu, th)
    return await send_card(chat_id, png, Screen(rich=False, title=caption(u, tgu, th).title,
                                                body=caption(u, tgu, th).body, buttons=main_buttons(back)), reply_to)


async def _markup(c, buttons):
    try:
        await tg.call("editMessageReplyMarkup", chat_id=c.message.chat.id, message_id=c.message.message_id,
                      reply_markup=kb_json(buttons))
    except tg.ApiError as e:
        if "not modified" not in e.desc.lower():
            raise


@router.message(Command("profile"))
async def profile_cmd(m: Message):
    try:
        await send_profile(m.chat.id, m.from_user, reply_to=m.message_id, back=m.chat.type == "private")
    except Exception:
        log.exception("profile card failed -> text fallback")  # Pillow/font issue -> simple text
        u, _ = ensure_user(m.from_user)
        li = pc.level_info(u["wagered"])
        await send(m.chat.id, Screen(rich=False, title="👤 <b>Profile</b>", rows=[
            ("Level", f"{li['tier']} L{li['level']}"), ("Wagered", f"{get('currency')}{u['wagered']:,.2f}"),
            ("Balance", f"{get('currency')}{u['balance']:,.2f}")]), reply_to=m.message_id)


@router.callback_query(F.data == "profile")
async def profile_cb(c: CallbackQuery):
    await c.answer()
    await delete(c.message.chat.id, c.message.message_id)
    await send_profile(c.message.chat.id, c.from_user, back=True)


@router.callback_query(F.data == "pf:th")
async def theme_open(c: CallbackQuery):
    cur = theme_of(c.from_user.id)
    await _markup(c, picker_buttons(cur))
    await c.answer("Pick a theme 🎨")


@router.callback_query(F.data.startswith("pf:t:"))
async def theme_set(c: CallbackQuery):
    t = c.data[5:]
    if t not in pc.THEMES:
        return await c.answer()
    u, _ = ensure_user(c.from_user)
    if theme_of(u["id"]) == t:
        return await c.answer("Already selected")
    set_pref(u["id"], "ptheme", t)
    await c.answer("Applying…")
    png = await make_png(u, c.from_user, t)
    cap = caption(u, c.from_user, t)
    await edit_card(c.message.chat.id, c.message.message_id, png,
                    Screen(rich=False, title=cap.title, body=cap.body, buttons=picker_buttons(t)))


@router.callback_query(F.data == "pf:done")
async def theme_done(c: CallbackQuery):
    await _markup(c, main_buttons(c.message.chat.type == "private"))
    await c.answer("Theme saved ✅")
