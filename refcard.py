"""/refer ka photo card (cream ya night theme). Design badalna ho to PAL / layout yahin badlo."""
import io

from PIL import Image, ImageDraw

import qr
from cardimg import S, _avatar, _box, _fit, _sx, _text, _w, font

W, H = 1000, 1360
PAL = {
    "cream": dict(bg1=(246, 236, 210), bg2=(238, 220, 183), panel=(253, 249, 238), border=(70, 178, 205), ink=(20, 36, 50),
                  muted=(112, 122, 128), accent=(15, 148, 160), claim=(14, 66, 84), claim_lab=(168, 210, 222),
                  claim_val=(255, 255, 255), good=(14, 135, 88), pill=(255, 255, 255), line=(226, 214, 186)),
    "night": dict(bg1=(8, 18, 25), bg2=(12, 40, 50), panel=(15, 33, 42), border=(34, 211, 190), ink=(236, 246, 249),
                  muted=(138, 165, 175), accent=(34, 211, 190), claim=(8, 98, 104), claim_lab=(176, 232, 228),
                  claim_val=(255, 255, 255), good=(74, 222, 128), pill=(34, 211, 190), line=(33, 62, 74)),
}


def _bg(c1, c2):
    g = Image.linear_gradient("L").resize((_sx(W), _sx(H)))
    return Image.composite(Image.new("RGB", g.size, c2), Image.new("RGB", g.size, c1), g).convert("RGBA")


def render(brand, title, name, username, avatar, n_ref, ready, mult, code, link, cur, theme, ew, ed, claimed,
           wager_pct, dep_pct, top, days):
    p = PAL.get(theme, PAL["cream"])
    base = _bg(p["bg1"], p["bg2"])
    d = ImageDraw.Draw(base)
    rr = lambda b, r, fill=None, out=None, w=1: d.rounded_rectangle(_box(b), radius=_sx(r), fill=fill, outline=out, width=_sx(w))
    money = lambda x: f"{cur}{x:,.2f}"

    rr((16, 16, W - 16, H - 16), 34, None, p["border"], 4)
    # header
    _text(d, 48, 52, brand.upper(), font(15, True), p["muted"], "lm", sp=3)
    tf, _ = _fit(title.upper(), True, 58, 640, 30)
    _text(d, 46, 106, title.upper(), tf, p["ink"], "lm")
    _text(d, 48, 152, "YOUR AFFILIATE ACCOUNT", font(16, True), p["muted"], "lm", sp=2)
    pf = font(15, True)
    pw = _w(pf, "REFERRAL", 2) + 44
    rr((W - 48 - pw, 70, W - 48, 112), 21, p["pill"], p["ink"], 2)
    _text(d, W - 48 - pw / 2, 91, "REFERRAL", pf, (20, 36, 50) if theme == "cream" else (6, 30, 36), "mm", sp=2)
    d.rectangle(_box((48, 178, W - 48, 181)), fill=p["border"])

    # profile + claim
    rr((46, 204, W - 46, 372), 24, p["panel"], p["line"], 2)
    _avatar(base, 76, 232, 112, avatar, (name[:1] or "?").upper(), p["accent"])
    d = ImageDraw.Draw(base)
    nf, _ = _fit(name or "Player", True, 36, 380, 18)
    _text(d, 214, 262, name or "Player", nf, p["ink"], "lm")
    _text(d, 214, 304, f"@{username}" if username else "no username", font(20), p["muted"], "lm")
    _text(d, 214, 342, f"{n_ref} REFERRED PLAYER{'S' if n_ref != 1 else ''}", font(16, True), p["accent"], "lm", sp=1)
    rr((618, 226, W - 68, 350), 18, p["claim"])
    _text(d, 642, 254, "READY TO CLAIM", font(15, True), p["claim_lab"], "lm", sp=2)
    rf, _ = _fit(money(ready), True, 50, 270, 24)
    _text(d, 642, 298, money(ready), rf, p["claim_val"], "lm")
    _text(d, 642, 336, f"{mult:g}x WAGER ON CLAIM", font(14, True), p["claim_lab"], "lm", sp=1)

    # invite
    rr((46, 396, W - 46, 612), 24, p["panel"], p["border"], 3)
    _text(d, 78, 428, "YOUR INVITE CODE", font(15, True), p["muted"], "lm", sp=3)
    _text(d, 78, 490, str(code), font(64, True), p["ink"], "lm")
    lf, _ = _fit(link.replace("https://", ""), False, 19, 600, 11)
    _text(d, 78, 544, link.replace("https://", ""), lf, p["muted"], "lm")
    _text(d, 78, 586, "SHARE THE LINK. FRIENDS PLAY. YOU EARN.", font(16, True), p["accent"], "lm", sp=1)
    rr((762, 418, 934, 590), 16, (255, 255, 255), p["ink"], 2)
    q = qr.png(link, box=8, border=1).resize((_sx(148), _sx(148)), Image.NEAREST)
    base.paste(q, (_sx(774), _sx(430)))
    d = ImageDraw.Draw(base)

    # stats
    def cells(y0, y1, items):
        rr((46, y0, W - 46, y1), 22, p["panel"], p["line"], 2)
        cw = (W - 92) / len(items)
        for i, (lab, val, sub, col) in enumerate(items):
            x = 46 + i * cw
            if i:
                d.line([_sx(x), _sx(y0 + 18), _sx(x), _sx(y1 - 18)], fill=p["line"], width=_sx(2))
            _text(d, x + 26, y0 + 28, lab, font(13, True), p["muted"], "lm", sp=2)
            vf, _ = _fit(val, True, 38, cw - 44, 16)
            _text(d, x + 26, y0 + 68, val, vf, col, "lm")
            if sub:
                _text(d, x + 26, y0 + 98, sub, font(13), p["muted"], "lm")
    cells(636, 752, [("REFERRALS", str(n_ref), "", p["ink"]), ("WAGER EARNED", money(ew), "", p["good"]),
                     ("DEPOSIT EARNED", money(ed), "", p["good"]), ("CLAIMED", money(claimed), "", p["ink"])])
    dep_txt = f"{dep_pct:g}%" if dep_pct > 0 else "NONE"
    cells(772, 888, [("WAGER SHARE", f"{wager_pct:g}%", "of referred play", p["ink"]),
                     ("DEPOSIT REWARD", dep_txt, "of deposits" if dep_pct > 0 else "not active", p["ink"]),
                     ("LIFETIME EARNED", money(ew + ed), "wager + deposit", p["good"])])

    # top referrals
    rr((46, 908, W - 46, 1086), 22, p["panel"], p["line"], 2)
    _text(d, 74, 940, "TOP REFERRALS", font(18, True), p["ink"], "lm", sp=2)
    cw = (W - 92) / 3
    for i in range(3):
        x = 46 + i * cw + 28
        if i:
            d.line([_sx(46 + i * cw), _sx(962), _sx(46 + i * cw), _sx(1064)], fill=p["line"], width=_sx(2))
        if i < len(top):
            nm, e, w_, dp = top[i]
            f_, _ = _fit(f"#{i + 1} {nm}", True, 21, cw - 56, 12)
            _text(d, x, 988, f"#{i + 1} {nm}", f_, p["ink"], "lm")
            _text(d, x, 1028, money(e), font(30, True), p["good"], "lm")
            _text(d, x, 1058, f"W {money(w_)}  D {money(dp)}", font(13), p["muted"], "lm")
        else:
            _text(d, x, 988, f"#{i + 1}", font(21, True), p["muted"], "lm")
            _text(d, x, 1028, "—", font(30, True), p["muted"], "lm")

    # last 7 days
    rr((46, 1106, W - 46, 1296), 22, p["panel"], p["line"], 2)
    _text(d, 74, 1138, "LAST 7 DAYS EARNINGS", font(18, True), p["ink"], "lm", sp=2)
    x0, x1, yt, yb = 110, W - 110, 1176, 1250
    vals = [v for _, v in days]
    top_v = max(vals) if max(vals) > 0 else 1
    pts = [(x0 + i * (x1 - x0) / 6, yb - (v / top_v) * (yb - yt)) for i, v in enumerate(vals)]
    d.line([_sx(x0 - 20), _sx(yb + 12), _sx(x1 + 20), _sx(yb + 12)], fill=p["line"], width=_sx(2))
    d.line([(_sx(x), _sx(y)) for x, y in pts], fill=p["accent"], width=_sx(4), joint="curve")
    for (x, y), (lab, v) in zip(pts, days):
        d.ellipse(_box((x - 7, y - 7, x + 7, y + 7)), fill=p["panel"], outline=p["accent"], width=_sx(4))
        if v > 0:
            _text(d, x, y - 20, money(v), font(13, True), p["good"], "mm")
    _text(d, x0, 1274, days[0][0], font(13), p["muted"], "mm")
    _text(d, x1, 1274, days[-1][0], font(13), p["muted"], "mm")
    _text(d, W / 2, 1324, f"STANDARD REFERRAL CLAIM: {mult:g}x WAGER", font(15, True), p["muted"], "mm", sp=2)

    out = base.convert("RGB").resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()
