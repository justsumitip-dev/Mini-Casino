import asyncio
import json
import logging
from datetime import datetime
from html import escape as esc

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message

import admin
import admin_emoji
import group_admin
import grouplock
import games
import payments
import profilecmd
import referral
import statement
import tg
from config import ADMIN_IDS, BOT_TOKEN, LOG_CHANNEL
from database import db, ensure_user, fmt, get, set_pref, tier
from games.common import get_bet, limits, presets
from ui import Btn, Screen, send, show
from utils import back_row, community_screen, games_screen, go_home, home_screen, money_row, send_home

logging.basicConfig(level=logging.INFO)
user = Router()


# ───────────── aiogram ko naye 'rich_message' field se bachao ─────────────
# Naye Bot API ke rich message blocks (jaise buttons) kuch aiogram versions validate nahi kar paate
# aur getUpdates loop atak jaata hai. Humein incoming rich_message chahiye hi nahi -> hata do.
def _strip(o):
    if isinstance(o, dict):
        o.pop("rich_message", None)
        for v in o.values():
            _strip(v)
    elif isinstance(o, list):
        for v in o:
            _strip(v)


class SafeSession(AiohttpSession):
    def check_response(self, bot, method, status_code, content):
        try:
            data = json.loads(content)
            _strip(data)
            content = json.dumps(data)
        except Exception:
            pass
        return super().check_response(bot, method, status_code, content)


# ───────────── LOBBY ─────────────
@user.message(CommandStart())
async def start(m: Message, bot: Bot, command: CommandObject):
    u, new = ensure_user(m.from_user)
    arg = (command.args or "").strip()
    if new and arg.startswith("r-") and arg[2:].isdigit():  # referral link: t.me/Bot?start=r-<id>
        ref_id = int(arg[2:])
        if referral.attach(m.from_user.id, ref_id):
            try:
                await bot.send_message(ref_id, f"🎉 <b>{esc(m.from_user.full_name)}</b> joined with your referral link!")
            except Exception:
                pass
    await send_home(m.chat.id, m.from_user, reply_to=m.message_id)  # photo card + colored buttons
    if new and LOG_CHANNEL:
        try:
            await bot.send_message(LOG_CHANNEL, f"🆕 New user: {esc(m.from_user.full_name)} (<code>{m.from_user.id}</code>)")
        except Exception:
            pass


@user.message(Command("play"))
async def play_cmd(m: Message):
    ensure_user(m.from_user)
    await send(m.chat.id, games_screen(), reply_to=m.message_id)


def balance_screen(u):
    return Screen(rich=False, body=[f"<blockquote>💰 Balance: <b>{esc(fmt(u['balance']))}</b></blockquote>"],
                  buttons=[money_row(both_green=True)])


@user.message(Command("bal", "balance"))
async def balance_cmd(m: Message):
    u, _ = ensure_user(m.from_user)
    await send(m.chat.id, balance_screen(u), reply_to=m.message_id)


@user.callback_query(F.data == "home")
async def home(c: CallbackQuery):
    if not await go_home(c):  # card OFF -> text UI
        u, _ = ensure_user(c.from_user)
        await show(c, home_screen(u))


@user.callback_query(F.data == "play")
async def play(c: CallbackQuery):
    await show(c, games_screen())


@user.callback_query(F.data.in_({"dep", "wd"}))
async def maintenance(c: CallbackQuery):
    await c.answer(get("maint_msg"), show_alert=True)


@user.callback_query(F.data == "community")
async def community(c: CallbackQuery):
    await show(c, community_screen())


@user.callback_query(F.data == "terms")
async def terms(c: CallbackQuery):
    await show(c, Screen(title="📜 <b>Fair Play & Terms</b>", body=[esc(get("terms_text"))], buttons=[back_row()]))


# ───────────── PREFERENCES ─────────────
def prefs_screen(uid):
    bet = get_bet(uid)
    row = [Btn(("✅ " if abs(p - bet) < 1e-9 else "") + f"{p:g}", f"pf:bet:{p:g}",
               style="success" if abs(p - bet) < 1e-9 else "primary") for p in presets()]
    return Screen(title="⚙️ <b>Preferences</b>", rows=[("Default bet", fmt(bet))],
                  body=["Pick your default bet. Game-specific options (like Dice mode) are inside each game."],
                  buttons=[row, back_row()])


@user.callback_query(F.data == "prefs")
async def prefs(c: CallbackQuery):
    ensure_user(c.from_user)
    await show(c, prefs_screen(c.from_user.id))


@user.callback_query(F.data.startswith("pf:bet:"))
async def pf_bet(c: CallbackQuery):
    try:
        v = float(c.data[7:])
    except ValueError:
        return await c.answer()
    lo, hi = limits()
    set_pref(c.from_user.id, "bet", round(min(max(v, lo), hi), 2))
    await show(c, prefs_screen(c.from_user.id))


# ───────────── BAN CHECK ─────────────
class BanMW(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = event.from_user
        if u and u.id not in ADMIN_IDS:
            r = db("SELECT banned FROM users WHERE id=?", (u.id,), "one")
            if r and r["banned"]:
                if isinstance(event, CallbackQuery):
                    await event.answer("🚫 You are banned.", show_alert=True)
                return
        return await handler(event, data)


# ───────────── RUN ─────────────
async def main():
    if not BOT_TOKEN or BOT_TOKEN.startswith("PASTE"):
        raise SystemExit("config.py me naya BOT_TOKEN daalo (@BotFather -> /revoke)!")
    bot = Bot(BOT_TOKEN, session=SafeSession(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(grouplock.GroupMW())        # approved groups + owner lock
    dp.callback_query.outer_middleware(grouplock.GroupMW())
    dp.message.middleware(BanMW())
    dp.callback_query.middleware(BanMW())
    dp.include_router(admin.router)
    dp.include_router(admin_emoji.router)
    dp.include_router(group_admin.router)
    dp.include_router(payments.router)
    dp.include_router(referral.router)
    dp.include_router(statement.router)
    dp.include_router(profilecmd.router)
    dp.include_router(games.router)
    dp.include_router(user)
    await bot.set_my_commands([
        BotCommand(command="start", description="Main menu"),
        BotCommand(command="play", description="Games"),
        *[BotCommand(command=k, description=d[:250]) for k, d in games.commands()],
        BotCommand(command="profile", description="Your profile card"),
        BotCommand(command="bal", description="Your balance"),
        BotCommand(command="statement", description="Account statement"),
        BotCommand(command="transactions", description="Payment history"),
        BotCommand(command="refer", description="Refer & earn"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    tasks = [asyncio.create_task(g.background(bot)) for g in games.GAMES.values() if g.background]  # timeouts etc.
    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()
        await tg.close()


if __name__ == "__main__":
    asyncio.run(main())