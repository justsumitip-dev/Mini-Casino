"""/statement: poora account statement (photo card, pages, Export PDF).
Har balance movement `txns` table me jaata hai (bet, win, refund, deposit, withdrawal, referral claim, admin credit/debit)."""
import asyncio
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import reports
import stmtcard
from database import db, ensure_user, get
from ui import Btn, Screen, edit_card, send_card, send_doc
from utils import cb_chat, deliver

router = Router(name="statement")


def _page(uid, page):
    per = int(get("stmt_rows"))
    total = db("SELECT COUNT(*) n FROM txns WHERE uid=?", (uid,), "one")["n"]
    pages = max(1, math.ceil(total / per))
    page = min(max(page, 0), pages - 1)
    rows = db("SELECT * FROM txns WHERE uid=? ORDER BY id DESC LIMIT ? OFFSET ?", (uid, per, page * per), "all")
    return page, pages, total, rows


async def build(u, tgu, page=0):
    """-> (png, Screen)"""
    page, pages, total, rows = _page(u["id"], page)
    u = db("SELECT * FROM users WHERE id=?", (u["id"],), "one")
    png = await asyncio.to_thread(stmtcard.render, get("brand"), tgu.username or "", u["balance"], get("currency"),
                                  page + 1, pages, total, rows)
    nav = []
    if page > 0:
        nav.append(Btn("< Prev", f"st:{page - 1}", style="primary"))
    if page < pages - 1:
        nav.append(Btn("Next >", f"st:{page + 1}", style="primary"))
    scr = Screen(title="Account Statement", body=[f"Real-wallet movements · Page {page + 1}/{pages}"],
                 buttons=[nav, [Btn("Export PDF", "st:pdf", style="success")]])
    return png, scr


async def send_pdf(chat, u, reply=None):
    data = await asyncio.to_thread(reports.statement_pdf, u)
    await send_doc(chat, data, f"statement_{u['id']}.pdf", "📒 <b>Account Statement</b>", reply)


async def _send_statement(chat, u, tgu, reply=None, page=0):
    png, scr = await build(u, tgu, page)
    await send_card(chat, png, scr, reply)


@router.message(Command("statement"))
async def cmd_statement(m: Message):
    u, _ = ensure_user(m.from_user)
    await deliver(m, lambda chat, reply: _send_statement(chat, u, m.from_user, reply))


@router.callback_query(F.data == "st:open")
async def open_statement(c: CallbackQuery):
    u, _ = ensure_user(c.from_user)
    await _send_statement(cb_chat(c), u, c.from_user)
    await c.answer("Sent" if cb_chat(c) != c.message.chat.id else None)


@router.callback_query(F.data == "st:pdf")
async def cb_pdf(c: CallbackQuery):
    u, _ = ensure_user(c.from_user)
    await c.answer("Preparing PDF...")
    await send_pdf(cb_chat(c), u)


@router.callback_query(F.data.regexp(r"^st:\d+$"))
async def cb_page(c: CallbackQuery):
    u, _ = ensure_user(c.from_user)
    png, scr = await build(u, c.from_user, int(c.data[3:]))
    await edit_card(c.message.chat.id, c.message.message_id, png, scr)
    await c.answer()
