"""Payment history: deposits + withdrawals.
/transactions (ya /payhistory)  -> rich message tables      /transactionspdf (ya /paypdf) -> PDF

Data kahan se aata hai: `add_payment()` se. Admin panel (user page -> Record Deposit / Record Withdrawal) isse use karta hai.
Aapka koi payment gateway/webhook ho to deposit confirm hone par bas ye call karo:
    payments.add_payment(user_id, "deposit", 25.0, asset="USDT_POLYGON", tx="0xabc...")
"""
import asyncio
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import reports
from database import credit, db, ensure_user, get, ref_accrue, spend
from pdfgen import utc
from ui import Btn, Screen, send, send_doc
from utils import cb_chat, deliver

router = Router(name="payments")


def add_payment(uid, kind, amount, asset="USDT", status=None, tx="", note=""):
    """kind: 'deposit' | 'withdrawal'. -> (True, id) ya (False, error text).
    deposit    : balance badhta hai + referral deposit-reward lagta hai.
    withdrawal : balance ghatta hai (status 'Cancelled' ho to balance nahi chhua jaata)."""
    amount = round(float(amount), 2)
    if amount <= 0:
        return False, "Amount must be above 0."
    if kind == "deposit":
        status = status or "Credited"
        if status == "Credited":
            credit(uid, amount, kind="Deposit", note=asset)
            ref_accrue(uid, "deposit", amount)
    else:
        status = status or "Paid"
        if status != "Cancelled" and not spend(uid, amount, "Withdrawal", asset):
            return False, "Insufficient balance."
    cur = db("INSERT INTO payments(ts,uid,kind,amount,asset,status,tx,note) VALUES(?,?,?,?,?,?,?,?)",
             (int(time.time()), uid, kind, amount, asset, status, tx, note))
    return True, cur.lastrowid


def _short(tx):
    tx = tx or "-"
    return tx if len(tx) <= 14 else tx[:6] + "…" + tx[-4:]


def history_screen(uid):
    n = int(get("pay_rows"))
    cur = get("currency")
    tables = []
    for kind, head in (("deposit", "Deposits"), ("withdrawal", "Withdrawals")):
        rows = db("SELECT * FROM payments WHERE uid=? AND kind=? ORDER BY id DESC LIMIT ?", (uid, kind, n), "all")
        tables.append((head, ["Date", "Amount", "Asset", "Status", "TX"],
                       [[utc(r["ts"]), f"{cur}{r['amount']:,.2f}", r["asset"] or "-", r["status"], _short(r["tx"])] for r in rows]))
    return Screen(title="Payment History", body=[f"Latest {n} each · {get('pay_unit')} · UTC"], tables=tables,
                  buttons=[[Btn("📄 Export PDF", "pay:pdf", style="success")]])


async def send_pdf(chat, u, reply=None):
    data = await asyncio.to_thread(reports.payments_pdf, u)
    await send_doc(chat, data, f"payments_{u['id']}.pdf", "💳 <b>Payment History</b>", reply)


@router.message(Command("transactions", "payhistory"))
async def cmd_history(m: Message):
    u, _ = ensure_user(m.from_user)
    await deliver(m, lambda chat, reply: send(chat, history_screen(u["id"]), reply_to=reply))


@router.message(Command("transactionspdf", "payhistorypdf", "paypdf"))
async def cmd_pdf(m: Message):
    u, _ = ensure_user(m.from_user)
    await deliver(m, lambda chat, reply: send_pdf(chat, u, reply))


@router.callback_query(F.data == "pay:open")
async def open_history(c: CallbackQuery):
    ensure_user(c.from_user)
    await send(cb_chat(c), history_screen(c.from_user.id))
    await c.answer("Sent" if cb_chat(c) != c.message.chat.id else None)


@router.callback_query(F.data == "pay:pdf")
async def cb_pdf(c: CallbackQuery):
    u, _ = ensure_user(c.from_user)
    await c.answer("Preparing PDF...")
    await send_pdf(cb_chat(c), u)
