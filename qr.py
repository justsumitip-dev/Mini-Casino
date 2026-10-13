"""Chhota QR code generator (koi extra package nahi chahiye).
Byte mode, error correction M, version 1-10 (~210 bytes tak). make(text) -> list[list[bool]] (True = dark)."""

# version: (EC codewords per block, [(blocks, data codewords per block), ...])  — level M
_EC = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
       6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
       10: (26, [(4, 43), (1, 44)])}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}

_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i], _LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs(data, n):
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            nxt[j] ^= c
            nxt[j + 1] ^= _mul(c, _EXP[i])
        gen = nxt
    rem = [0] * n
    for b in data:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n):
            rem[i] ^= _mul(gen[i + 1], f)
    return rem


def _codewords(data, ver):
    ec, groups = _EC[ver]
    blocks, pos = [], 0
    for cnt, dcw in groups:
        for _ in range(cnt):
            blocks.append(data[pos:pos + dcw])
            pos += dcw
    eccs = [_rs(b, ec) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec):
        out += [e[i] for e in eccs]
    return out


def _bit(v, i):
    return (v >> i) & 1


def _penalty(m):
    n = len(m)
    p = 0
    for grid in (m, [list(r) for r in zip(*m)]):
        for row in grid:
            run, prev = 1, row[0]
            for c in row[1:]:
                if c == prev:
                    run += 1
                else:
                    p += 3 + run - 5 if run >= 5 else 0
                    run, prev = 1, c
            p += 3 + run - 5 if run >= 5 else 0
            s = "".join("1" if c else "0" for c in row)
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                p += 3
    dark = sum(sum(r) for r in m)
    k = abs(dark * 20 - n * n * 10) // (n * n)
    return p + k * 10


_MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
          lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
          lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
          lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]


def make(text):
    raw = text.encode("utf-8")
    ver = next((v for v in range(1, 11)
                if 4 + (8 if v < 10 else 16) + 8 * len(raw) <= 8 * sum(c * d for c, d in _EC[v][1])), None)
    if ver is None:
        raise ValueError("QR text too long")
    cap = sum(c * d for c, d in _EC[ver][1])
    bits = "0100" + format(len(raw), "08b" if ver < 10 else "016b") + "".join(format(b, "08b") for b in raw)
    bits += "0" * min(4, cap * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    data = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(data) < cap:
        data.append(pad[(len(data) - len(bits) // 8) % 2])
    cw = _codewords(data, ver)

    size = 17 + 4 * ver
    mod = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def setf(x, y, dark):
        if 0 <= x < size and 0 <= y < size:
            mod[y][x], fn[y][x] = dark, True

    for i in range(size):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                setf(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    pos = _ALIGN[ver]
    for i, ax in enumerate(pos):
        for j, ay in enumerate(pos):
            if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def fmt_bits(mask):
        data5 = (0 << 3) | mask  # EC level M = 0b00
        rem = data5
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits_ = (data5 << 10 | rem) ^ 0x5412
        for i in range(6):
            setf(8, i, bool(_bit(bits_, i)))
        setf(8, 7, bool(_bit(bits_, 6)))
        setf(8, 8, bool(_bit(bits_, 7)))
        setf(7, 8, bool(_bit(bits_, 8)))
        for i in range(9, 15):
            setf(14 - i, 8, bool(_bit(bits_, i)))
        for i in range(8):
            setf(size - 1 - i, 8, bool(_bit(bits_, i)))
        for i in range(8, 15):
            setf(8, size - 15 + i, bool(_bit(bits_, i)))
        setf(8, size - 8, True)

    fmt_bits(0)  # area reserve
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vb = ver << 12 | rem
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            setf(a, b, bool(_bit(vb, i)))
            setf(b, a, bool(_bit(vb, i)))

    i = 0
    for right in range(size - 1, 0, -2):
        if right <= 6:
            right -= 1
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if (right + 1) & 2 == 0 else vert
                if not fn[y][x] and i < len(cw) * 8:
                    mod[y][x] = bool(_bit(cw[i >> 3], 7 - (i & 7)))
                    i += 1

    best = None
    for k, f in enumerate(_MASKS):
        m = [[mod[y][x] ^ ((not fn[y][x]) and f(x, y)) for x in range(size)] for y in range(size)]
        saved = [r[:] for r in mod]
        for y in range(size):
            mod[y] = m[y]
        fmt_bits(k)
        pen = _penalty(mod)
        if best is None or pen < best[0]:
            best = (pen, [r[:] for r in mod])
        for y in range(size):
            mod[y] = saved[y]
    return best[1]


def png(text, box=8, border=4):
    """PIL Image (RGB) wala QR."""
    from PIL import Image
    m = make(text)
    n = len(m) + border * 2
    im = Image.new("RGB", (n, n), "white")
    px = im.load()
    for y, row in enumerate(m):
        for x, d in enumerate(row):
            if d:
                px[x + border, y + border] = (0, 0, 0)
    return im.resize((n * box, n * box), Image.NEAREST)
