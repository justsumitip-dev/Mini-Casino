"""Group control ka admin hissa: /allow, /disallow, bot add/remove detect, Admin panel -> Groups page."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

import grouplock
from config import ADMIN_IDS
from ui import Btn, Screen, esc, send, show

router = Router(name="group_admin")
adm = F.from_user.id.in_(set(ADMIN_IDS))


def P(title="", body=None, buttons=None):
    return Screen(title=title, body=body or [], buttons=buttons or [], rich=False)


# ───────────── group me commands (sirf admin) ─────────────
@router.message(Command("allow"), adm, F.chat.type.in_(grouplock.GROUP_TYPES))
async def allow_cmd(m: Message):
    grouplock.allow(m.chat.id, m.chat.title)
    await send(m.chat.id, P(body=["✅ <b>Bot enabled in this group.</b>\nSend /play to start."]), reply_to=m.message_id)


@router.message(Command("disallow"), adm, F.chat.type.in_(grouplock.GROUP_TYPES))
async def disallow_cmd(m: Message):
    grouplock.disallow(m.chat.id)
    await send(m.chat.id, P(body=["🚫 <b>Bot disabled in this group.</b>\nAdmin can enable it again with /allow."]),
               reply_to=m.message_id)


@router.my_chat_member()
async def bot_status(ev: ChatMemberUpdated):
    """Admin bot ko group me add kare -> auto allow. Bot nikal diya jaye -> list se hata do."""
    if ev.chat.type not in grouplock.GROUP_TYPES:
        return
    st = ev.new_chat_member.status
    if st in ("left", "kicked"):
        grouplock.disallow(ev.chat.id)
    elif st in ("member", "administrator") and ev.from_user and ev.from_user.id in ADMIN_IDS:
        fresh = not grouplock.is_allowed(ev.chat.id)
        grouplock.allow(ev.chat.id, ev.chat.title)
        if fresh:
            try:
                await send(ev.chat.id, P(body=["✅ <b>Bot enabled in this group.</b>\nSend /play to start."]))
            except Exception:
                pass


@router.message(F.migrate_to_chat_id)
async def migrated(m: Message):
    """Group supergroup ban gaya -> naya chat id bhi allow."""
    if grouplock.is_allowed(m.chat.id):
        grouplock.allow(m.migrate_to_chat_id, m.chat.title)
        grouplock.disallow(m.chat.id)


# ───────────── Admin panel -> Groups ─────────────
def groups_screen():
    rows = grouplock.groups()
    body = [f"Bot works <b>only</b> in these groups (and in DM). Total: <b>{len(rows)}</b>"]
    if rows:
        body.append("\n".join(f"• {esc(r['title'] or 'Group')} <code>{r['chat_id']}</code>" for r in rows))
    else:
        body.append("No group is approved yet.")
    body.append("<b>How to add:</b> add the bot to a group yourself (it is approved automatically), "
                "or send /allow in the group. Send /disallow in a group to stop it.")
    btns = [[Btn(f"🗑 Remove · {(r['title'] or 'Group')[:24]}", f"gp:rm:{r['chat_id']}", style="danger")] for r in rows]
    btns.append([Btn("⬅️ Admin Menu", "a:home", style="primary")])
    return P("👥 <b>Allowed Groups</b>", body, btns)


@router.callback_query(F.data == "gp:home", adm)
async def gp_home(c: CallbackQuery):
    await show(c, groups_screen())


@router.callback_query(F.data.startswith("gp:rm:"), adm)
async def gp_rm(c: CallbackQuery):
    grouplock.disallow(int(c.data[6:]))
    await show(c, groups_screen(), "Removed")
