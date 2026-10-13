"""Screen -> Telegram message. 3 mode, automatic fallback:
  inline  : sendRichMessage, buttons card ke andar (<tg-button>)
  classic : sendRichMessage + niche colored inline keyboard
  plain   : sendMessage (HTML) + colored inline keyboard
"""
import html as _html
import logging
from dataclasses import dataclass, field

import grouplock
import premium as pe
import tg
from config import RICH_MODE

log = logging.getLogger("ui")


def esc(x):
    return _html.escape(str(x), quote=True)


@dataclass
class Btn:
    text: str
    data: str = None
    url: str = None
    style: str = None  # primary (blue) | success (green) | danger (red) | None (gray)


@dataclass
class Screen:
    title: str = ""                              # HTML
    rows: list = field(default_factory=list)     # [(label, plain value)] -> table
    body: list = field(default_factory=list)     # HTML paragraphs
    buttons: list = field(default_factory=list)  # [[Btn, ...], ...]
    rich: bool = True                            # False = hamesha plain (admin panel)
    tables: list = field(default_factory=list)   # [(heading, [header...], [[cell...], ...])] -> rich table / plain <pre>


# ───────────── renderers ─────────────
def _btn_json(b):
    cid, rest = pe.lead(b.text)  # premium emoji: pehla emoji button ke icon me jaata hai
    d = {"text": rest}
    if cid:
        d["icon_custom_emoji_id"] = cid
    if b.url:
        d["url"] = b.url
    else:
        d["callback_data"] = b.data or "noop"
    if b.style:
        d["style"] = b.style
    return d


def kb_json(rows):
    return {"inline_keyboard": [[_btn_json(b) for b in row] for row in rows if row]}


def _tg_button(b):
    st = f' style="{b.style}"' if b.style else ""
    if b.url:
        return f'<tg-button type="url" url="{esc(b.url)}"{st}>{esc(b.text)}</tg-button>'
    return f'<tg-button type="callback_data" data="{esc(b.data or "noop")}"{st}>{esc(b.text)}</tg-button>'


def rich_html(s, inline):
    out = []
    if s.title:
        out.append(f"<h3>{s.title}</h3>")
    if s.rows:
        t = "".join(f"<tr><td>{esc(l)}</td><td><b>{esc(v)}</b></td></tr>" for l, v in s.rows)
        out.append(f"<table>{t}</table>")
    out += [f"<p>{p}</p>" for p in s.body]
    for head, cols, data in s.tables:
        out.append(f"<h3>{esc(head)}</h3>")
        if not data:
            out.append("<p>No records yet.</p>")
            continue
        t = "<tr>" + "".join(f"<td><b>{esc(c)}</b></td>" for c in cols) + "</tr>"
        t += "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in data)
        out.append(f"<table>{t}</table>")
    if inline:
        for row in s.buttons:
            if row:
                out.append("<tg-button-row>" + "".join(_tg_button(b) for b in row) + "</tg-button-row>")
    return pe.html("\n".join(out))


def _plain_raw(s):
    out = []
    if s.title:
        out.append(s.title if "<b>" in s.title else f"<b>{s.title}</b>")
        out.append("")
    out += [f"{esc(l)}: <b>{esc(v)}</b>" for l, v in s.rows]
    if s.rows:
        out.append("")
    out += s.body
    for head, cols, data in s.tables:
        out += ["", f"<b>{esc(head)}</b>"]
        if not data:
            out.append("No records yet.")
            continue
        w = [max(len(str(x)) for x in [c] + [r[i] for r in data]) for i, c in enumerate(cols)]
        line = lambda r: "  ".join(str(c).ljust(w[i]) for i, c in enumerate(r))
        out.append("<pre>" + esc("\n".join([line(cols)] + [line(r) for r in data])) + "</pre>")
    return "\n".join(out).strip()


def plain_html(s):
    return pe.html(_plain_raw(s))


async def _guard(fn):
    """Premium emoji ke saath bhejo; Telegram reject (400) kare to normal emoji ke saath ek baar aur try."""
    if not pe.on():
        return await fn()
    try:
        return await fn()
    except tg.ApiError as e:
        d = e.desc.lower()
        if e.code != 400 or "not modified" in d or "to edit not found" in d or "can't be edited" in d:
            raise
        tok = pe.suspend()
        try:
            r = await fn()
        finally:
            pe.resume(tok)
        pe.note_error(e.desc)  # retry chala = premium emoji ki wajah se fail hua tha (admin panel me dikhta hai)
        log.warning("premium emoji rejected -> sent with normal emoji: %s", e)
        return r


# ───────────── mode handling ─────────────
_ORDER = ["inline", "classic", "plain"]
_start = {"auto": "inline", "rich": "inline", "inline": "inline", "classic": "classic", "plain": "plain"}
_state = {"mode": _start.get(RICH_MODE, "inline"), "fails": 0}
_MARKERS = ("rich", "parse", "tg-", "unsupported", "not supported", "entities", "unknown",
            "tag", "html", "button", "block", "style", "table")
_NOT_UI = ("chat not found", "blocked", "kicked", "deactivated", "forbidden")


def get_mode():
    return _state["mode"]


def set_mode(m):
    if m in _ORDER:
        _state["mode"], _state["fails"] = m, 0


async def _once(m, kind, chat_id, mid, s, reply_to):
    if m == "plain":
        params = {"text": plain_html(s) or "·", "parse_mode": "HTML",
                  "link_preview_options": {"is_disabled": True}}
        use_kb = True
    else:
        params = {"rich_message": {"html": rich_html(s, m == "inline")}}
        use_kb = m == "classic"
    if use_kb and s.buttons:
        params["reply_markup"] = kb_json(s.buttons)
    if kind == "send":
        params["chat_id"] = chat_id
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        method = "sendMessage" if m == "plain" else "sendRichMessage"
    else:
        params.update(chat_id=chat_id, message_id=mid)
        method = "editMessageText"
    return await tg.call(method, **params)


async def _deliver(kind, chat_id, mid, s, reply_to=None):
    m = "plain" if not s.rich else _state["mode"]
    while True:
        try:
            r = await _guard(lambda: _once(m, kind, chat_id, mid, s, reply_to))
            if m == _state["mode"]:
                _state["fails"] = 0
            if kind == "send":
                grouplock.note(chat_id, r)  # group me naye message ka owner = command bhejne wala
            return r
        except tg.ApiError as e:
            d = e.desc.lower()
            if "not modified" in d:
                return None
            if kind == "edit" and ("to edit not found" in d or "can't be edited" in d):
                return None
            fallbackable = (e.code == 404 or any(x in d for x in _MARKERS)) and not any(x in d for x in _NOT_UI)
            if not fallbackable or m == "plain":
                raise
            log.warning("UI mode %s failed (%s) -> falling back", m, e)
            if m == _state["mode"]:
                _state["fails"] += 1
                if _state["fails"] >= 3:
                    _state["mode"], _state["fails"] = _ORDER[_ORDER.index(m) + 1], 0
                    log.warning("UI mode permanently -> %s", _state["mode"])
            m = _ORDER[_ORDER.index(m) + 1]


async def send(chat_id, s, reply_to=None):
    return await _deliver("send", chat_id, None, s, reply_to)


async def edit(chat_id, mid, s):
    return await _deliver("edit", chat_id, mid, s)


async def send_card(chat_id, png, s, reply_to=None):
    """Photo card + caption + colored buttons (/start). Screen ka title/rows/body caption banta hai."""
    async def go():
        params = {"chat_id": chat_id, "caption": pe.html(_plain_raw(s)[:1024]), "parse_mode": "HTML"}
        if s.buttons:
            params["reply_markup"] = kb_json(s.buttons)
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return await tg.call_file("sendPhoto", "photo", png, **params)
    r = await _guard(go)
    grouplock.note(chat_id, r)
    return r


async def edit_card(chat_id, mid, png, s):
    """Photo message ki photo + caption + buttons badlo (statement pages)."""
    async def go():
        params = {"chat_id": chat_id, "message_id": mid,
                  "media": {"type": "photo", "media": "attach://photo", "caption": pe.html(_plain_raw(s)[:1024]),
                            "parse_mode": "HTML"}}
        if s.buttons:
            params["reply_markup"] = kb_json(s.buttons)
        return await tg.call_file("editMessageMedia", "photo", png, **params)
    try:
        return await _guard(go)
    except tg.ApiError as e:
        if "not modified" not in e.desc.lower():
            raise


async def send_doc(chat_id, data, filename, caption="", reply_to=None, buttons=None):
    async def go():
        params = {"chat_id": chat_id, "caption": pe.html(caption[:1024]), "parse_mode": "HTML"}
        if buttons:
            params["reply_markup"] = kb_json(buttons)
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return await tg.call_file("sendDocument", "document", data, filename=filename,
                                  content_type="application/pdf", **params)
    r = await _guard(go)
    grouplock.note(chat_id, r)
    return r


async def delete(chat_id, mid):
    try:
        await tg.call("deleteMessage", chat_id=chat_id, message_id=mid)
    except tg.ApiError:
        pass


async def show(c, s, alert=None, alert_box=False):
    """Callback ke message ko edit karo + callback answer.
    Agar message photo card hai (edit nahi ho sakta) -> delete karke naya bhejo."""
    try:
        if getattr(c.message, "photo", None):
            await delete(c.message.chat.id, c.message.message_id)
            await send(c.message.chat.id, s)
        else:
            await edit(c.message.chat.id, c.message.message_id, s)
    except tg.ApiError as e:
        log.error("edit failed: %s", e)
    try:
        await c.answer(alert, show_alert=alert_box) if alert else await c.answer()
    except Exception:
        pass
