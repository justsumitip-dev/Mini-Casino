"""Admin panel -> 💎 Premium Emojis.

  • List se kisi bhi normal emoji ko chuno -> uski jagah premium emoji bhejo (ya numeric ID).
  • 📦 Import from pack: pack ka ek premium emoji bhejo, bot pack ke emoji khud match karke set kar deta hai.
  • ON/OFF switch, test message, reset.
Setup ke baad bot ke har message / button me normal emoji ki jagah premium emoji dikhta hai.
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import premium as pe
import tg
from config import ADMIN_IDS
from ui import Btn, Screen, esc, send, show

router = Router()
router.message.filter(F.from_user.id.in_(set(ADMIN_IDS)))
router.callback_query.filter(F.from_user.id.in_(set(ADMIN_IDS)))

PER = 15  # ek page par emoji (3 columns x 5 rows)


class E(StatesGroup):
    one = State()
    pack = State()


def P(title="", body=None, buttons=None):
    return Screen(title=title, body=body or [], buttons=buttons or [], rich=False)


def back_home():
    return [Btn("⬅️ Premium Emojis", "pe:home", style="primary")]


def home():
    total, n = len(pe.EMOJIS), len(pe.mapped())
    body = [f"Status: <b>{'ON 🟢' if pe.enabled() else 'OFF 🔴'}</b> · Set: <b>{n}/{total}</b>",
            "Jis emoji ka slot set hai, bot me wahan premium emoji dikhta hai. Khali slot par normal emoji hi rahega."]
    if pe.last_error():
        body.append("⚠️ Telegram ne premium emoji reject kiya, isliye normal emoji ke saath bheja gaya:\n"
                    f"<code>{esc(pe.last_error())}</code>")
    return P("💎 <b>Premium Emojis</b>", body, [
        [Btn("📋 Emoji list (set / change)", "pe:l:0", style="success")],
        [Btn("📦 Import from pack", "pe:imp", style="primary"), Btn("🧪 Test", "pe:test", style="primary")],
        [Btn("🟢 Turn OFF" if pe.enabled() else "🔴 Turn ON", "pe:tog", style="danger" if pe.enabled() else "success"),
         Btn("🗑 Reset all", "pe:rst", style="danger")],
        [Btn("⬅️ Admin Menu", "a:home", style="primary")],
    ])


def list_page(p):
    n = len(pe.EMOJIS)
    pages = (n + PER - 1) // PER
    p = max(0, min(p, pages - 1))
    rows, row = [], []
    for i in range(p * PER, min(n, (p + 1) * PER)):
        e = pe.EMOJIS[i][0]
        ok = pe.has(e)
        row.append(Btn(f"{e} ✔" if ok else f"{e} ·", f"pe:s:{i}", style="success" if ok else None))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if p > 0:
        nav.append(Btn("⬅️ Prev", f"pe:l:{p - 1}", style="primary"))
    nav.append(Btn(f"{p + 1}/{pages}", "noop"))
    if p < pages - 1:
        nav.append(Btn("Next ➡️", f"pe:l:{p + 1}", style="primary"))
    rows += [nav, back_home()]
    return P("📋 <b>Emoji list</b>", ["✔ = premium set · · = abhi normal. Emoji par tap karo."], rows), p


def slot_page(i):
    e, lab = pe.EMOJIS[i]
    cid = pe.cid_of(e)
    body = [f"Emoji: {e}\nUsed for: <b>{esc(lab)}</b>",
            f"Premium ID: <code>{cid}</code>" if cid else "Premium: <b>not set</b>"]
    rows = [[Btn("✏️ Set premium emoji", f"pe:set:{i}", style="success")]]
    if cid:
        rows.append([Btn("🗑 Remove (back to normal)", f"pe:d:{i}", style="danger")])
    rows.append([Btn("⬅️ List", f"pe:l:{i // PER}", style="primary")])
    return P("💎 <b>Premium emoji</b>", body, rows)


def ids_in(m: Message):
    ents = (m.entities or []) + (m.caption_entities or [])
    return [x.custom_emoji_id for x in ents if x.type == "custom_emoji" and x.custom_emoji_id]


# ───────────── pages ─────────────
@router.callback_query(F.data == "pe:home")
async def pe_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(c, home())


@router.callback_query(F.data == "pe:tog")
async def pe_tog(c: CallbackQuery):
    pe.set_enabled(not pe.enabled())
    pe.clear_error()
    await show(c, home())


@router.callback_query(F.data.startswith("pe:l:"))
async def pe_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    scr, _ = list_page(int(c.data[5:]))
    await show(c, scr)


@router.callback_query(F.data.startswith("pe:s:"))
async def pe_slot(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(c, slot_page(int(c.data[5:])))


@router.callback_query(F.data.startswith("pe:d:"))
async def pe_del(c: CallbackQuery):
    i = int(c.data[5:])
    pe.remove(pe.EMOJIS[i][0])
    await show(c, slot_page(i), "Removed")


# ───────────── set one ─────────────
@router.callback_query(F.data.startswith("pe:set:"))
async def pe_set(c: CallbackQuery, state: FSMContext):
    i = int(c.data[7:])
    await state.set_state(E.one)
    await state.update_data(i=i)
    await send(c.message.chat.id, P(body=[
        f"✏️ Send the <b>premium emoji</b> you want in place of {pe.EMOJIS[i][0]} "
        "(only the emoji, nothing else).\nYou can also send its numeric ID.\n/cancel to stop."]))
    await c.answer()


@router.message(E.one)
async def pe_set_save(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    if text.startswith("/"):
        return await m.answer("Send a premium emoji, or /cancel to stop.")
    ids = ids_in(m)
    cid = ids[0] if ids else (text if text.isdigit() and len(text) >= 10 else None)
    if not cid:
        return await m.answer("❌ That is not a premium emoji. Send one premium emoji (or its ID), or /cancel.")
    i = (await state.get_data())["i"]
    pe.set_many({pe.EMOJIS[i][0]: cid})
    await state.clear()
    await send(m.chat.id, slot_page(i))


# ───────────── import from pack ─────────────
@router.callback_query(F.data == "pe:imp")
async def pe_imp(c: CallbackQuery):
    await show(c, P("📦 <b>Import from pack</b>", [
        "Send one premium emoji from a pack. The bot reads the whole pack and matches each emoji "
        "with the same normal emoji automatically.\n\nWhat should it do with slots that are already set?"],
        [[Btn("Fill empty only", "pe:imp:0", style="success"), Btn("Overwrite all", "pe:imp:1", style="danger")],
         back_home()]))


@router.callback_query(F.data.startswith("pe:imp:"))
async def pe_imp_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(E.pack)
    await state.update_data(over=c.data.endswith("1"))
    await send(c.message.chat.id, P(body=["📦 Send <b>one premium emoji</b> from the pack you want to use. /cancel to stop."]))
    await c.answer()


async def import_pack(cid, overwrite):
    st = await tg.call("getCustomEmojiStickers", custom_emoji_ids=[cid])
    name = st[0].get("set_name") if st else None
    if not name:
        raise ValueError("pack not found")
    pack = await tg.call("getStickerSet", name=name)
    got = {}
    for s in pack.get("stickers", []):
        raw = pe.norm(s.get("emoji") or "")
        k = raw if raw in pe.KEYS else next((ch for ch in raw if ch in pe.KEYS), None)
        if k and s.get("custom_emoji_id") and k not in got and (overwrite or k not in pe.mapped()):
            got[k] = s["custom_emoji_id"]
    return pack.get("title") or name, len(pack.get("stickers", [])), pe.set_many(got)


@router.message(E.pack)
async def pe_pack_do(m: Message, state: FSMContext):
    if (m.text or "").startswith("/"):
        return await m.answer("Send a premium emoji, or /cancel to stop.")
    ids = ids_in(m)
    if not ids:
        return await m.answer("❌ Send one premium emoji from the pack (or /cancel).")
    over = (await state.get_data()).get("over", False)
    await state.clear()
    try:
        title, total, n = await import_pack(ids[0], over)
    except Exception as ex:
        return await send(m.chat.id, P("❌ <b>Import failed</b>", [esc(str(ex))], [back_home()]))
    left = len(pe.EMOJIS) - len(pe.mapped())
    await send(m.chat.id, P("✅ <b>Pack imported</b>", [
        f"Pack: <b>{esc(title)}</b> ({total} emojis)\nMatched &amp; set: <b>{n}</b>\nStill normal: <b>{left}</b> "
        "(set those one by one from the list)"], [[Btn("📋 Emoji list", "pe:l:0", style="success")], back_home()]))


# ───────────── test / reset ─────────────
@router.callback_query(F.data == "pe:test")
async def pe_test(c: CallbackQuery):
    m = pe.mapped()
    if not m:
        return await c.answer("Nothing is set yet.", show_alert=True)
    shown = [e for e, _ in pe.EMOJIS if pe.has(e)]
    row = [Btn(f"{e} Test", "noop", style="primary") for e in shown[:3]]
    await send(c.message.chat.id, P("🧪 <b>Premium emoji test</b>", [
        " ".join(shown), "Upar ke emoji aur neeche ke button icons premium dikhne chahiye."], [row, back_home()]))
    await c.answer()


@router.callback_query(F.data == "pe:rst")
async def pe_rst(c: CallbackQuery):
    await show(c, P("🗑 <b>Reset all?</b>", ["All premium emoji slots will be cleared and the bot goes back to normal emojis."],
                    [[Btn("Yes, reset all", "pe:rst2", style="danger"), Btn("Cancel", "pe:home", style="primary")]]))


@router.callback_query(F.data == "pe:rst2")
async def pe_rst2(c: CallbackQuery):
    pe.clear()
    pe.clear_error()
    await show(c, home(), "Reset")
