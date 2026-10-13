"""/start wala photo card (Pillow se banta hai).

Design badalna ho to sirf is file me THEMES / layout badlo.
Admin panel se: Settings -> Card design (theme, badge, footer, on/off).
Font: system ka DejaVu/Liberation/Arial auto milta hai. Apna font chahiye to
config.py me FONT_PATH aur FONT_BOLD_PATH daal do.
"""
import io
import os
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    import config as _cfg
except Exception:  # pragma: no cover
    _cfg = None

W, H, S = 1000, 600, 2  # logical size, supersampling

THEMES = {
    "teal":   {"bg1": (5, 16, 27),  "bg2": (8, 56, 66),  "accent": (34, 211, 190), "gold": (251, 191, 36)},
    "gold":   {"bg1": (18, 12, 5),  "bg2": (66, 42, 8),  "accent": (251, 191, 36), "gold": (253, 224, 71)},
    "purple": {"bg1": (13, 7, 30),  "bg2": (52, 18, 96), "accent": (168, 85, 247), "gold": (250, 204, 21)},
    "ruby":   {"bg1": (24, 5, 11),  "bg2": (84, 12, 30), "accent": (244, 63, 94),  "gold": (251, 191, 36)},
}
TIER_COL = {"Bronze": (214, 140, 70), "Silver": (203, 213, 225), "Gold": (251, 191, 36), "Platinum": (125, 211, 252)}
WHITE, MUTED, GREEN = (240, 248, 250), (150, 176, 186), (74, 222, 128)

_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/", "/usr/share/fonts/TTF/",
              "/usr/share/fonts/truetype/liberation/", "/usr/share/fonts/truetype/freefont/",
              "/system/fonts/", "C:/Windows/Fonts/", "/Library/Fonts/", "/usr/share/fonts/truetype/noto/"]
_REG = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf", "Roboto-Regular.ttf", "NotoSans-Regular.ttf"]
_BOLD = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf", "Roboto-Bold.ttf", "NotoSans-Bold.ttf"]
_font_cache, _path_cache = {}, {}


def _find(bold):
    k = "b" if bold else "r"
    if k in _path_cache:
        return _path_cache[k]
    custom = getattr(_cfg, "FONT_BOLD_PATH" if bold else "FONT_PATH", None)
    cands = [custom] if custom else []
    cands += [d + n for d in _FONT_DIRS for n in (_BOLD if bold else _REG)]
    _path_cache[k] = next((p for p in cands if p and os.path.exists(p)), None)
    return _path_cache[k]


def font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        p = _find(bold)
        try:
            _font_cache[key] = ImageFont.truetype(p, size * S) if p else ImageFont.load_default(size * S)
        except Exception:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# ───────────── helpers ─────────────
def _sx(v):
    return int(round(v * S))


def _box(b):
    return [_sx(v) for v in b]


def _w(f, text, sp=0):
    return f.getlength(text) / S + sp * max(len(text) - 1, 0)


def _fit(text, bold, size, max_w, min_size=14, sp=0):
    while size > min_size and _w(font(size, bold), text, sp) > max_w:
        size -= 2
    return font(size, bold), size


def _text(d, x, y, text, f, fill, anchor="la", sp=0):
    """sp = letter spacing (logical px)."""
    if not sp:
        d.text((_sx(x), _sx(y)), text, font=f, fill=fill, anchor=anchor)
        return
    total = _w(f, text, sp)
    if anchor[0] == "r":
        x -= total
    elif anchor[0] == "m":
        x -= total / 2
    for ch in text:
        d.text((_sx(x), _sx(y)), ch, font=f, fill=fill, anchor="l" + anchor[1])
        x += f.getlength(ch) / S + sp


def _clean(s, limit):
    s = "".join(ch for ch in (s or "") if ch.isprintable() and ord(ch) < 0x250).strip()
    return s[:limit]


def _gradient(c1, c2):
    g = Image.linear_gradient("L").resize((_sx(W), _sx(H)))
    return Image.composite(Image.new("RGB", g.size, c2), Image.new("RGB", g.size, c1), g)


def _die(d, x, y, size, val, body=(246, 248, 250), pip=(20, 30, 40), alpha=255):
    r = size * 0.22
    d.rounded_rectangle(_box((x, y, x + size, y + size)), radius=_sx(r), fill=body + (alpha,))
    pos = {1: [(.5, .5)], 2: [(.28, .28), (.72, .72)], 3: [(.28, .28), (.5, .5), (.72, .72)],
           4: [(.28, .28), (.72, .28), (.28, .72), (.72, .72)],
           5: [(.28, .28), (.72, .28), (.5, .5), (.28, .72), (.72, .72)],
           6: [(.3, .25), (.7, .25), (.3, .5), (.7, .5), (.3, .75), (.7, .75)]}[val]
    pr = size * 0.075
    for px, py in pos:
        cx, cy = x + size * px, y + size * py
        d.ellipse(_box((cx - pr, cy - pr, cx + pr, cy + pr)), fill=pip + (alpha,))


def _avatar(base, x, y, size, avatar_bytes, initial, accent):
    ring = Image.new("RGBA", base.size, (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse(_box((x - 5, y - 5, x + size + 5, y + size + 5)), outline=accent + (255,), width=_sx(3))
    base.alpha_composite(ring)
    px = None
    if avatar_bytes:
        try:
            im = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
            m = min(im.size)
            im = im.crop(((im.width - m) // 2, (im.height - m) // 2, (im.width + m) // 2, (im.height + m) // 2))
            px = im.resize((_sx(size), _sx(size)), Image.LANCZOS)
        except Exception:
            px = None
    if px is None:
        px = Image.new("RGB", (_sx(size), _sx(size)), accent)
        d = ImageDraw.Draw(px)
        f = font(int(size * 0.5), True)
        d.text((_sx(size) // 2, _sx(size) // 2), initial, font=f, fill=(6, 22, 30), anchor="mm")
    mask = Image.new("L", px.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px.size[0] - 1, px.size[1] - 1), fill=255)
    base.paste(px, (_sx(x), _sx(y)), mask)


# ───────────── main renderer ─────────────
def render(brand, name, username, uid, joined, balance, currency, tier, tier_prev, tier_next, next_name,
           wagered, last_win, badge, footer, live=True, theme="teal", avatar=None):
    th = THEMES.get(theme, THEMES["teal"])
    acc, gold = th["accent"], th["gold"]
    base = _gradient(th["bg1"], th["bg2"]).convert("RGBA")

    # soft glows
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(_box((620, -160, 1120, 300)), fill=acc + (70,))
    gd.ellipse(_box((-200, 330, 300, 760)), fill=gold + (45,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(_sx(70))))

    # faint dot grid
    dots = Image.new("RGBA", base.size, (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for gx in range(30, W, 28):
        for gy in range(30, H, 28):
            dd.ellipse(_box((gx, gy, gx + 2, gy + 2)), fill=(255, 255, 255, 14))
    base.alpha_composite(dots)

    # translucent panels (ek hi overlay)
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rounded_rectangle(_box((14, 14, W - 14, H - 14)), radius=_sx(34), outline=acc + (230,), width=_sx(3))
    od.rounded_rectangle(_box((22, 22, W - 22, H - 22)), radius=_sx(28), outline=gold + (90,), width=_sx(1))
    od.rounded_rectangle(_box((40, 112, 372, 366)), radius=_sx(22), fill=(255, 255, 255, 16), outline=(255, 255, 255, 40), width=_sx(1))
    od.rounded_rectangle(_box((392, 112, 960, 244)), radius=_sx(22), fill=(0, 0, 0, 90), outline=gold + (150,), width=_sx(2))
    cw = (568 - 28) / 3
    chips = [392 + i * (cw + 14) for i in range(3)]
    for cx in chips:
        od.rounded_rectangle(_box((cx, 260, cx + cw, 366)), radius=_sx(18), fill=(255, 255, 255, 16), outline=(255, 255, 255, 40), width=_sx(1))
    od.rounded_rectangle(_box((40, 470, 960, 566)), radius=_sx(24), fill=acc + (36,), outline=acc + (150,), width=_sx(2))
    od.rounded_rectangle(_box((40, 392, 960, 452)), radius=_sx(18), fill=(0, 0, 0, 70))
    base.alpha_composite(ov)

    d = ImageDraw.Draw(base)

    # header
    _die(d, 44, 40, 50, 6)
    f, _ = _fit(brand.upper(), True, 34, 540, 18, sp=2)
    _text(d, 108, 65, brand.upper(), f, WHITE, "lm", sp=2)
    bf = font(17, True)
    bw = _w(bf, badge.upper(), 2) + 40
    d.rounded_rectangle(_box((W - 44 - bw, 44, W - 44, 86)), radius=_sx(21), fill=gold + (255,))
    _text(d, W - 44 - bw / 2, 66, badge.upper(), bf, (30, 20, 0), "mm", sp=2)

    # player panel
    _avatar(base, 62, 134, 88, avatar, (name[:1] or username[:1] or "?").upper() or "?", acc)
    d = ImageDraw.Draw(base)
    nf, _ = _fit(name or "Player", True, 26, 200, 16)
    _text(d, 168, 156, name or "Player", nf, WHITE, "lm")
    uf, _ = _fit(f"@{username}" if username else "no username", False, 18, 200, 12)
    _text(d, 168, 190, f"@{username}" if username else "no username", uf, acc, "lm")
    _text(d, 62, 262, "PLAYER ID", font(13, True), MUTED, "lm", sp=2)
    _text(d, 62, 290, str(uid), font(28, True), WHITE, "lm")
    _text(d, 62, 328, "MEMBER SINCE", font(13, True), MUTED, "lm", sp=2)
    _text(d, 62, 352, datetime.fromtimestamp(joined).strftime("%d %b %Y") if joined else "-", font(22, True), WHITE, "lm")

    # balance
    _text(d, 418, 142, "AVAILABLE BALANCE", font(15, True), MUTED, "lm", sp=3)
    bal_txt = f"{currency}{balance:,.2f}"
    bf2, _ = _fit(bal_txt, True, 84, 516, 30)
    _text(d, 418, 196, bal_txt, bf2, gold, "lm")

    # chips
    tcol = TIER_COL.get(tier, WHITE)
    vals = [("PLAYER TIER", tier, tcol), ("LAST WIN", f"{currency}{last_win:,.2f}", GREEN if last_win > 0 else WHITE),
            ("WAGERED", f"{currency}{wagered:,.0f}", WHITE)]
    for cx, (lab, val, col) in zip(chips, vals):
        _text(d, cx + 18, 284, lab, font(13, True), MUTED, "lm", sp=2)
        vf, _ = _fit(val, True, 30, cw - 36, 14)
        _text(d, cx + 18, 330, val, vf, col, "lm")

    # tier progress
    if next_name:
        frac = min(max((wagered - tier_prev) / max(tier_next - tier_prev, 1), 0), 1)
        _text(d, 60, 413, f"NEXT TIER: {next_name.upper()}", font(14, True), MUTED, "lm", sp=2)
        _text(d, 940, 413, f"{currency}{wagered:,.0f} / {currency}{tier_next:,.0f}", font(14, True), WHITE, "rm")
    else:
        frac = 1
        _text(d, 60, 413, "MAX TIER REACHED", font(14, True), gold, "lm", sp=2)
    d.rounded_rectangle(_box((60, 429, 940, 440)), radius=_sx(6), fill=(40, 66, 76, 255))
    if frac > 0:
        d.rounded_rectangle(_box((60, 429, 60 + max(880 * frac, 12), 440)), radius=_sx(6), fill=acc + (255,))

    # footer
    dot = GREEN if live else (248, 113, 113)
    d.ellipse(_box((64, 505, 84, 525)), fill=dot + (255,))
    _text(d, 100, 504, "GAMES ARE LIVE" if live else "GAMES PAUSED", font(28, True), WHITE, "lm", sp=1)
    ff, _ = _fit(footer, False, 17, 620, 11)
    _text(d, 100, 540, footer, ff, MUTED, "lm")
    _die(d, 820, 484, 56, 3, alpha=235)
    _die(d, 888, 496, 44, 5, alpha=200)

    out = base.convert("RGB").resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def make_card(u, tgu, avatar, st):
    """u = users row, tgu = aiogram User, st = dict(brand, currency, tier..., badge, footer, theme, live)."""
    return render(
        brand=st["brand"], name=_clean(tgu.full_name, 22) or _clean(tgu.first_name, 22) or "Player",
        username=_clean(tgu.username or "", 24), uid=u["id"], joined=u["joined"], balance=u["balance"],
        currency=st["currency"], tier=st["tier"], tier_prev=st["tier_prev"], tier_next=st["tier_next"],
        next_name=st["next_name"], wagered=u["wagered"], last_win=u["last_win"], badge=st["badge"],
        footer=st["footer"], live=st["live"], theme=st["theme"], avatar=avatar)


if __name__ == "__main__":
    png = render("YOUR CASINO", "Cyber Amit", "cyber_amit", 8603893462, int(time.time()), 8.75, "$", "Bronze", 0, 100,
                 "Silver", 42, 0, "WELCOME PASS", "Tap Play Now to pick a game. Play responsibly.")
    open("card_preview.png", "wb").write(png)
    print("card_preview.png ban gaya")
