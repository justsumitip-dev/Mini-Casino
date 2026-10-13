import asyncio
import logging

import cardimg
import tg
from database import db, ensure_user, fmt, get, links, tier, tier_info
from ui import Btn, Screen, delete, esc, send, send_card

log = logging.getLogger("utils")
STYLES = ["success", "primary", "danger"]


# ───────────── buttons ─────────────
def money_row(both_green=False):
    """Deposit / Withdraw: admin ne link daala hai to URL button, warna maintenance popup."""
    dep, wd = get("deposit_url"), get("withdraw_url")
    st = "success" if both_green else None
    return [Btn("📥 Deposit", url=dep, style="success") if dep else Btn("📥 Deposit", "dep", style="success"),
            Btn("📤 Withdraw", url=wd, style=st) if wd else Btn("📤 Withdraw", "wd", style=st)]


def main_buttons():
    tu = get("terms_url")
    row3 = [Btn("👤 Profile", "profile", style="primary"), Btn("⚙️ Preferences", "prefs")]
    row4 = []
    if links():
        row4.append(Btn("🌐 Community", "community", style="success"))
    row4.append(Btn("📜 Fair Play & Terms", url=tu, style="primary") if tu else Btn("📜 Fair Play & Terms", "terms", style="primary"))
    return [
        [Btn("🎮 " + get("play_btn"), "play", style="success")],
        money_row(),
        row3,
        row4,
    ]


async def deliver(m, fn):
    """Private commands (/refer, /statement, /transactions...). DM me seedha chalta hai;
    group me ho (aur admin ne dm_only ON rakha ho) to result user ke DM me jaata hai aur group me 'check DM' aata hai.
    fn(chat_id, reply_to) = async function jo result bhejta hai."""
    if m.chat.type == "private" or get("dm_only") != "1":
        return await fn(m.chat.id, m.message_id)
    uname = await tg.bot_username()
    try:
        await fn(m.from_user.id, None)
    except tg.ApiError as e:
        d = e.desc.lower()
        if e.code == 403 or "chat not found" in d or "can't initiate" in d or "blocked" in d:
            return await send(m.chat.id, Screen(rich=False, body=["⚠️ I can't message you in DM yet. Open the bot, press <b>Start</b>, then send the command again."],
                                                buttons=[[Btn("🤖 Open bot", url=f"https://t.me/{uname}?start=hi", style="primary")]]),
                              reply_to=m.message_id)
        raise
    await send(m.chat.id, Screen(rich=False, body=["📩 Sent to your DM — please check."],
                                 buttons=[[Btn("📩 Open DM", url=f"https://t.me/{uname}", style="success")]]),
               reply_to=m.message_id)


def cb_chat(c):
    """Button dabaya gaya: private data hamesha user ke DM me."""
    if c.message.chat.type != "private" and get("dm_only") == "1":
        return c.from_user.id
    return c.message.chat.id


def back_row(data="home", text="⬅️ Back"):
    return [Btn(text, data, style="primary")]


# ───────────── screens ─────────────
def home_screen(u):
    """Text version (card OFF hone par / fallback)."""
    return Screen(
        title=f"🎲 <b>{esc(get('brand'))}</b>",
        rows=[("Balance", fmt(u["balance"])), ("Tier", tier(u["wagered"]))],
        body=[f"<b>{esc(get('welcome_title'))}</b>", f"<i>{esc(get('welcome_text'))}</i>"],
        buttons=main_buttons())


def home_caption(u):
    """Photo card ke neeche ka text + colored buttons."""
    return Screen(title=f"🎲 <b>{esc(get('welcome_title'))}</b>",
                  body=[f"<i>{esc(get('welcome_text'))}</i>"], buttons=main_buttons())


def games_screen():
    rows = []
    helps = []
    for g in db("SELECT * FROM games ORDER BY sort", fetch="all"):
        if g["enabled"]:
            rows.append([Btn(f"🟢 {g['title']}", f"g:{g['key']}", style="success")])
        else:
            rows.append([Btn(f"🔒 {g['title']} • Soon", f"g:{g['key']}", style="danger")])
    try:
        from games.registry import GAMES
        helps = [f"<code>{esc(x.usage)}</code>" for x in sorted(GAMES.values(), key=lambda x: x.order) if x.usage]
    except Exception:
        pass
    rows.append(back_row())
    return Screen(title="🎮 <b>Games</b>",
                  body=["Choose a game" + (", or use " + ", ".join(helps) if helps else "")],
                  buttons=rows)


def community_screen():
    rows = [[Btn(r["label"], url=r["url"], style=STYLES[i % 3])] for i, r in enumerate(links())]
    rows.append(back_row())
    return Screen(title="🌐 <b>Community</b>", body=["Join us 👇"], buttons=rows)


# ───────────── start card ─────────────
def games_live():
    return bool(db("SELECT 1 FROM games WHERE enabled=1", fetch="one"))


async def card_png(u, tgu):
    name, prev, nxt, nxt_name = tier_info(u["wagered"])
    badge = get("card_badge") if u["wagered"] <= 0 else f"{name} Member"
    st = {"brand": get("brand"), "currency": get("currency"), "tier": name, "tier_prev": prev,
          "tier_next": nxt or 0, "next_name": nxt_name, "badge": badge, "footer": get("card_footer"),
          "theme": get("card_theme"), "live": games_live()}
    av = await tg.avatar(tgu.id) if get("card_avatar") == "1" else None
    return await asyncio.to_thread(cardimg.make_card, u, tgu, av, st)


async def send_home(chat_id, tgu, reply_to=None):
    """/start: photo card + caption + colored buttons. Card fail ho to text UI."""
    u, _ = ensure_user(tgu)
    if get("card_enabled") == "1":
        try:
            return await send_card(chat_id, await card_png(u, tgu), home_caption(u), reply_to)
        except Exception as e:
            log.warning("card failed (%s) -> text UI", e)
    return await send(chat_id, home_screen(u), reply_to)


async def go_home(c):
    """'Back' / home button: purana message hata ke fresh card bhejo."""
    ensure_user(c.from_user)
    if get("card_enabled") == "1":
        await delete(c.message.chat.id, c.message.message_id)
        await send_home(c.message.chat.id, c.from_user)
        try:
            await c.answer()
        except Exception:
            pass
        return True
    return False
