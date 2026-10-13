"""/statement ka photo card (dark ledger). Rows: dict(kind, note, id, amount, balance, ts)."""
import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw

from cardimg import S, _box, _die, _fit, _sx, _text, _w, font

W = 900
GOOD, BAD, GOLD, ORANGE = (52, 224, 150), (255, 84, 98), (251, 191, 36), (251, 146, 60)
KIND_COL = {"Game Bet": BAD, "Game Win": GOOD, "Game Refund": GOLD, "Game Payout": GOOD, "Deposit": GOOD,
            "Withdrawal": ORANGE, "Referral Claim": GOLD, "Admin Credit": GOOD, "Admin Debit": BAD}


def _icon(d, kind, x, y, s):
    col = KIND_COL.get(kind, (140, 170, 180))
    if kind.startswith("Game"):
        _die(d, x, y, s, 5 if kind == "Game Bet" else 6, body=(255, 255, 255), pip=(190, 40, 60) if kind == "Game Bet" else (20, 120, 80))
        return
    cx, cy, r = x + s / 2, y + s / 2, s / 2
    d.ellipse(_box((x, y, x + s, y + s)), fill=col)
    k = s * .22
    if kind == "Deposit":
        d.polygon([(_sx(cx - k), _sx(cy - k * .3)), (_sx(cx + k), _sx(cy - k * .3)), (_sx(cx), _sx(cy + k))], fill=(8, 28, 24))
        d.rectangle(_box((cx - k * .3, cy - k, cx + k * .3, cy - k * .2)), fill=(8, 28, 24))
    elif kind == "Withdrawal":
        d.polygon([(_sx(cx - k), _sx(cy + k * .3)), (_sx(cx + k), _sx(cy + k * .3)), (_sx(cx), _sx(cy - k))], fill=(40, 20, 4))
        d.rectangle(_box((cx - k * .3, cy + k * .2, cx + k * .3, cy + k)), fill=(40, 20, 4))
    else:
        _text(d, cx, cy + 1, kind[0], font(int(s * .5), True), (20, 30, 30), "mm")


def _ts(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m %H:%M")


def render(brand, username, balance, cur, page, pages, total, rows):
    n = max(len(rows), 1)
    H = 196 + n * 82 + 62
    g = Image.linear_gradient("L").resize((_sx(W), _sx(H)))
    base = Image.composite(Image.new("RGB", g.size, (14, 36, 44)), Image.new("RGB", g.size, (8, 17, 22)), g).convert("RGBA")
    d = ImageDraw.Draw(base)
    money = lambda x: f"{cur}{abs(x):,.2f}"

    d.rectangle(_box((0, 0, W, 5)), fill=(34, 211, 190))
    d.rectangle(_box((0, H - 5, W, H)), fill=(34, 211, 190))
    # header
    d.rounded_rectangle(_box((30, 30, 70, 56)), radius=_sx(5), fill=(251, 191, 36))
    d.rectangle(_box((30, 38, 70, 44)), fill=(120, 80, 10))
    _text(d, 84, 44, "Account Statement", font(32, True), (240, 248, 250), "lm")
    _text(d, 32, 84, f"@{username} | Private account ledger" if username else "Private account ledger", font(16, True), (160, 205, 215), "lm")
    _text(d, 32, 116, f"Balance: {money(balance)}", font(19, True), GOOD, "lm")
    bf, _ = _fit(brand.upper(), True, 22, 330, 12, sp=1)
    _text(d, W - 32, 40, brand.upper(), bf, (34, 211, 190), "rm", sp=1)
    _text(d, W - 32, 100, f"Page {page}/{pages} · {total:,} entries", font(14, True), (170, 195, 204), "rm")
    # column heads
    hy = 152
    for x, t, a in ((40, "TYPE", "lm"), (470, "CHANGE", "lm"), (650, "BALANCE", "lm"), (W - 34, "TIME", "rm")):
        _text(d, x, hy, t, font(12, True), (130, 160, 170), a, sp=2)
    d.line([_sx(30), _sx(166), _sx(W - 30), _sx(166)], fill=(40, 70, 80), width=_sx(2))

    if not rows:
        _text(d, W / 2, 230, "No transactions yet", font(22, True), (150, 175, 185), "mm")
    y = 180
    for r in rows:
        col = KIND_COL.get(r["kind"], (140, 170, 180))
        d.rounded_rectangle(_box((30, y, W - 30, y + 72)), radius=_sx(10), fill=(18, 36, 44), outline=(30, 56, 66), width=_sx(1))
        d.rounded_rectangle(_box((30, y + 6, 36, y + 66)), radius=_sx(3), fill=col)
        _icon(d, r["kind"], 50, y + 20, 32)
        _text(d, 98, y + 24, r["kind"], font(21, True), (240, 248, 250), "lm")
        nf, _ = _fit(f"TXN-{r['id']:08X} | {r['note'] or 'Balance movement'}", False, 13, 340, 9)
        _text(d, 98, y + 50, f"TXN-{r['id']:08X} | {r['note'] or 'Balance movement'}", nf, (140, 168, 178), "lm")
        amt = f"{'+' if r['amount'] > 0 else '-'}{money(r['amount'])}"
        _text(d, 470, y + 36, amt, font(20, True), GOOD if r["amount"] > 0 else BAD, "lm")
        _text(d, 650, y + 36, money(r["balance"]), font(20, True), (240, 248, 250), "lm")
        _text(d, W - 46, y + 36, _ts(r["ts"]), font(16), (170, 195, 204), "rm")
        y += 82
    _text(d, W / 2, H - 30, "Private account statement · Timezone: UTC", font(13, True), (150, 175, 185), "mm")
    out = base.convert("RGB").resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()
