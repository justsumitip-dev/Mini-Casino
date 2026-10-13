"""/profile ka photo card (Pillow). Naya theme jodna ho to THEMES me ek entry daalo, bas.

Fonts / helpers cardimg.py se aate hain (DejaVu/Liberation auto, ya config.py me FONT_PATH).
"""
import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter

from cardimg import S, _avatar, _box, _clean, _fit, _sx, _text, font

W, H = 900, 1180

# ───────────── levels (15) ─────────────
# (tier, lifetime wager jahan se level shuru). 5 tier x 3 level.
LEVELS = [("Bronze", 0), ("Bronze", 100), ("Bronze", 300),
          ("Silver", 750), ("Silver", 1500), ("Silver", 3000),
          ("Gold", 6000), ("Gold", 10000), ("Gold", 15000),
          ("Platinum", 25000), ("Platinum", 40000), ("Platinum", 60000),
          ("Diamond", 100000), ("Diamond", 150000), ("Diamond", 250000)]
TIER_COL = {"Bronze": (205, 127, 50), "Silver": (190, 200, 214), "Gold": (240, 185, 30),
            "Platinum": (110, 200, 235), "Diamond": (140, 150, 255)}


def level_info(wagered):
    """-> dict(level, tier, next_label, progress 0..1, target (agle level ki limit) | None)."""
    idx = 0
    for i, (_, thr) in enumerate(LEVELS):
        if wagered >= thr:
            idx = i
    tier, cur = LEVELS[idx]
    if idx + 1 >= len(LEVELS):
        return {"level": idx + 1, "tier": tier, "next_label": "MAX LEVEL", "progress": 1.0, "target": None}
    ntier, nthr = LEVELS[idx + 1]
    label = f"NEXT · {ntier.upper()}" if ntier != tier else f"NEXT · LEVEL {idx + 2}"
    return {"level": idx + 1, "tier": tier, "next_label": label,
            "progress": max(0.0, min(1.0, (wagered - cur) / (nthr - cur))), "target": nthr}


# ───────────── themes ─────────────
# bg1/bg2 gradient, panel = player box, ink = main text, sub = chhota text, accent = bar/headings,
# track = progress bar ka khali hissa, box/box_ink = neeche ka box, pos/neg = profit colours, dark = glow ON
THEMES = {
    "lavender": dict(label="💜 Lavender", dark=False, bg1=(205, 178, 196), bg2=(178, 184, 214), panel=(172, 152, 200),
                     ink=(70, 38, 112), sub=(112, 90, 146), accent=(104, 66, 166), track=(160, 152, 180),
                     box=(204, 186, 156), box_ink=(80, 56, 30), line=(140, 118, 160), pos=(30, 140, 80), neg=(190, 50, 60)),
    "midnight": dict(label="🌙 Midnight", dark=True, bg1=(8, 12, 30), bg2=(22, 34, 78), panel=(30, 44, 96),
                     ink=(236, 242, 255), sub=(140, 158, 205), accent=(96, 165, 250), track=(40, 54, 100),
                     box=(20, 30, 66), box_ink=(220, 232, 255), line=(70, 90, 150), pos=(74, 222, 128), neg=(248, 113, 113)),
    "emerald": dict(label="💚 Emerald", dark=True, bg1=(4, 22, 18), bg2=(8, 66, 54), panel=(12, 84, 66),
                    ink=(232, 255, 246), sub=(134, 196, 174), accent=(52, 211, 153), track=(16, 60, 50),
                    box=(8, 48, 40), box_ink=(220, 252, 238), line=(40, 120, 98), pos=(110, 231, 160), neg=(252, 129, 129)),
    "gold": dict(label="👑 Royal Gold", dark=True, bg1=(14, 10, 4), bg2=(58, 40, 8), panel=(70, 50, 12),
                 ink=(255, 244, 214), sub=(204, 176, 112), accent=(251, 191, 36), track=(52, 38, 10),
                 box=(40, 28, 6), box_ink=(255, 236, 190), line=(120, 90, 30), pos=(134, 239, 172), neg=(252, 129, 129)),
    "crimson": dict(label="❤️ Crimson", dark=True, bg1=(22, 4, 10), bg2=(88, 12, 34), panel=(110, 20, 46),
                    ink=(255, 238, 242), sub=(222, 150, 170), accent=(251, 113, 133), track=(64, 12, 28),
                    box=(50, 8, 20), box_ink=(255, 226, 232), line=(150, 50, 80), pos=(134, 239, 172), neg=(254, 202, 202)),
    "ocean": dict(label="🌊 Ocean", dark=True, bg1=(4, 20, 34), bg2=(8, 78, 104), panel=(10, 96, 124),
                  ink=(232, 250, 255), sub=(136, 200, 220), accent=(34, 211, 238), track=(10, 58, 80),
                  box=(6, 52, 72), box_ink=(220, 248, 255), line=(40, 130, 160), pos=(110, 231, 183), neg=(252, 165, 165)),
    "sunset": dict(label="🌅 Sunset", dark=False, bg1=(255, 205, 170), bg2=(244, 160, 190), panel=(250, 150, 120),
                   ink=(96, 28, 40), sub=(150, 70, 80), accent=(200, 50, 80), track=(238, 180, 170),
                   box=(255, 226, 190), box_ink=(110, 50, 30), line=(214, 120, 120), pos=(20, 130, 70), neg=(180, 30, 50)),
    "mint": dict(label="🍃 Mint", dark=False, bg1=(200, 240, 224), bg2=(176, 222, 236), panel=(120, 206, 176),
                 ink=(16, 70, 56), sub=(60, 120, 104), accent=(16, 150, 110), track=(168, 210, 200),
                 box=(224, 240, 200), box_ink=(40, 80, 40), line=(110, 170, 150), pos=(10, 120, 60), neg=(190, 50, 60)),
}
DEFAULT_THEME = "lavender"


def theme_ids():
    return list(THEMES)


# ───────────── drawing helpers ─────────────
def _canvas(th):
    g = Image.linear_gradient("L").resize((_sx(W), _sx(H)))
    base = Image.composite(Image.new("RGB", g.size, th["bg2"]), Image.new("RGB", g.size, th["bg1"]), g).convert("RGBA")
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    a = 90 if th["dark"] else 70
    gd.ellipse(_box((520, -220, 1060, 260)), fill=th["accent"] + (a,))
    gd.ellipse(_box((-260, 760, 340, 1300)), fill=th["accent"] + (a - 30,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(_sx(90))))
    return base


def _rr(base, box, r, fill, shadow=True):
    """Rounded box (soft shadow ke saath) base par."""
    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
        x0, y0, x1, y1 = box
        ImageDraw.Draw(sh).rounded_rectangle(_box((x0, y0 + 10, x1, y1 + 10)), radius=_sx(r), fill=(0, 0, 0, 70))
        base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(_sx(16))))
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle(_box(box), radius=_sx(r), fill=fill)
    base.alpha_composite(lay)


def _emblem(d, x, y, w, h, fill):
    """Chhota 'A' (peak) logo."""
    pts = [(x, y + h), (x + w / 2, y), (x + w, y + h), (x + w * .72, y + h), (x + w / 2, y + h * .42), (x + w * .28, y + h)]
    d.polygon([(_sx(px), _sx(py)) for px, py in pts], fill=fill)


def _shield(d, cx, cy, size, col, ink):
    w, h = size * 0.86, size
    x, y = cx - w / 2, cy - h / 2
    outer = [(0.0, 0.04), (1.0, 0.04), (1.0, 0.56), (0.5, 1.0), (0.0, 0.56)]
    inner = [(0.09, 0.12), (0.91, 0.12), (0.91, 0.54), (0.5, 0.9), (0.09, 0.54)]
    dark = tuple(int(c * 0.45) for c in col)
    d.polygon([(_sx(x + w * px), _sx(y + h * py)) for px, py in outer], fill=dark)
    d.polygon([(_sx(x + w * px), _sx(y + h * py)) for px, py in inner], fill=col)
    _emblem(d, cx - w * .24, cy - h * .22, w * .48, h * .42, ink)


def _money(cur, v):
    return f"{cur}{v:,.2f}"


def render(p, theme=DEFAULT_THEME, avatar=None):
    """p = dict(brand, name, username, uid, joined, cur, tier, level, next_label, progress, target, wagered,
    rank, games, winrate, biggest, balance, total_won, net)"""
    th = THEMES.get(theme, THEMES[DEFAULT_THEME])
    base = _canvas(th)
    ink, sub, acc = th["ink"], th["sub"], th["accent"]
    tcol = TIER_COL.get(p["tier"], (200, 200, 200))
    cur = p["cur"]

    _rr(base, (40, 104, 860, 494), 38, th["panel"] + (235 if not th["dark"] else 245,))
    _rr(base, (40, 1000, 860, 1120), 30, th["box"] + (235,), shadow=False)
    d = ImageDraw.Draw(base)

    # header
    _emblem(d, 40, 38, 34, 28, acc)
    brand = _clean((p["brand"] or "CASINO").upper(), 26) or "CASINO"
    f, _ = _fit(brand, True, 24, 480, 14, 2)
    _text(d, 86, 54, brand, f, ink, "lm", sp=2)
    _text(d, 860, 54, "PRIVATE ACCOUNT", font(17, True), sub, "rm", sp=1.5)

    # player panel
    _avatar(base, 80, 140, 150, avatar, (p["name"] or "P")[:1].upper(), acc)
    d = ImageDraw.Draw(base)
    f, _ = _fit(p["name"], True, 56, 560, 28)
    _text(d, 268, 168, p["name"], f, ink, "lm")
    if p["username"]:
        _text(d, 268, 224, "@" + p["username"], font(28), sub, "lm")
    _text(d, 80, 338, "PLAYER LEVEL", font(17, True), sub, "lm", sp=1.5)
    f, _ = _fit(p["tier"].upper(), True, 70, 360, 36)
    _text(d, 80, 392, p["tier"].upper(), f, ink, "lm")
    _text(d, 80, 446, f"LEVEL {p['level']} OF {len(LEVELS)}", font(23), sub, "lm", sp=1)
    _shield(d, 772, 196, 116, tcol, th["panel"])
    _text(d, 822, 338, "MEMBER SINCE", font(17, True), sub, "rm", sp=1.5)
    since = datetime.fromtimestamp(p["joined"] or 0).strftime("%d %b %Y").upper()
    _text(d, 822, 384, since, font(36, True), ink, "rm")
    _text(d, 822, 458, f"ID / {p['uid']}", font(18), sub, "rm", sp=1)

    # wager + rank
    _text(d, 40, 540, "LIFETIME WAGERED", font(17, True), sub, "lm", sp=1.5)
    f, _ = _fit(_money(cur, p["wagered"]), True, 66, 470, 30)
    _text(d, 40, 598, _money(cur, p["wagered"]), f, ink, "lm")
    _text(d, 40, 650, "QUALIFYING PLAY", font(15, True), sub, "lm", sp=1.2)
    _text(d, 860, 540, "WAGER RANK", font(17, True), sub, "rm", sp=1.5)
    _text(d, 860, 598, p["rank"], font(66, True), ink, "rm")
    _text(d, 860, 650, "BY LIFETIME PLAY", font(15, True), sub, "rm", sp=1.2)
    d.line([_sx(40), _sx(690), _sx(860), _sx(690)], fill=th["line"] + (150,), width=_sx(2))

    # progress
    _text(d, 40, 730, p["next_label"], font(30, True), acc, "lm", sp=1)
    _text(d, 860, 730, f"{int(round(p['progress'] * 100))}%", font(30, True), acc, "rm")
    d.rounded_rectangle(_box((40, 764, 860, 788)), radius=_sx(12), fill=th["track"] + (255,))
    fw = max(24, int(820 * p["progress"])) if p["progress"] > 0 else 0
    if fw:
        d.rounded_rectangle(_box((40, 764, 40 + fw, 788)), radius=_sx(12), fill=acc + (255,))
    if p["target"]:
        _text(d, 40, 826, f"{_money(cur, p['wagered'])} of {_money(cur, p['target'])}", font(23, True), ink, "lm")
        _text(d, 860, 826, f"{_money(cur, max(p['target'] - p['wagered'], 0))} to go", font(23, True), ink, "rm")
    else:
        _text(d, 40, 826, "Top level reached", font(23, True), ink, "lm")
    d.line([_sx(40), _sx(872), _sx(860), _sx(872)], fill=th["line"] + (150,), width=_sx(2))

    # 3 stats
    for x, lab, val in ((40, "GAMES PLAYED", f"{p['games']:,}"), (330, "WIN RATE", f"{p['winrate']:.1f}%"),
                        (590, "BIGGEST WIN", _money(cur, p["biggest"]))):
        _text(d, x, 908, lab, font(16, True), sub, "lm", sp=1.5)
        f, _ = _fit(val, True, 46, 270, 24)
        _text(d, x, 958, val, f, ink, "lm")

    # account box
    bi = th["box_ink"]
    _text(d, 72, 1028, "YOUR ACCOUNT", font(21, True), bi, "lm", sp=1.5)
    net_col = th["pos"] if p["net"] >= 0 else th["neg"]
    net_txt = ("+" if p["net"] > 0 else "") + _money(cur, p["net"]) if p["net"] >= 0 else "-" + _money(cur, -p["net"])
    for x, lab, val, col in ((72, "BALANCE", _money(cur, p["balance"]), bi),
                            (352, "TOTAL WON", _money(cur, p["total_won"]), bi),
                            (622, "NET PROFIT", net_txt, net_col)):
        _text(d, x, 1066, lab, font(14, True), bi, "lm", sp=1.2)
        f, _ = _fit(val, True, 30, 240, 18)
        _text(d, x, 1098, val, f, col, "lm")

    _text(d, 450, 1152, "LEVEL PROGRESS · PLAY RESPONSIBLY", font(15, True), sub, "mm", sp=1.5)

    out = base.convert("RGB").resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()
