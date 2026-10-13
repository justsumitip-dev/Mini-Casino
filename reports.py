"""Sab PDF reports (user ke liye, aur admin kisi bhi user ka nikal sakta hai).
Har function user row `u` leta hai aur PDF bytes lauta hai (blocking: asyncio.to_thread se chalao)."""
from database import db, get
from pdfgen import build, utc


def _cur():
    c = get("currency")
    return "Rs " if c == "₹" else c


def _m(x, signed=False):
    s = f"{_cur()}{abs(x):,.2f}"
    return ("-" if x < 0 else "+" if signed and x > 0 else "") + s


def _who(u):
    return f"{u['name'] or 'Player'} (@{u['username'] or '-'}) · ID {u['id']}"


def _limit():
    try:
        return int(float(get("pdf_max_rows")))
    except ValueError:
        return 2000


def _cap_note(total, shown):
    return f"Showing the latest {shown:,} of {total:,} records." if total > shown else ""


# ───────────── statement ─────────────
def statement_pdf(u):
    n = db("SELECT COUNT(*) n FROM txns WHERE uid=?", (u["id"],), "one")["n"]
    lim = _limit()
    rows = db("SELECT * FROM txns WHERE uid=? ORDER BY id DESC LIMIT ?", (u["id"], lim), "all")
    agg = db("SELECT COALESCE(SUM(CASE WHEN amount>0 THEN amount END),0) i, COALESCE(SUM(CASE WHEN amount<0 THEN -amount END),0) o "
             "FROM txns WHERE uid=?", (u["id"],), "one")
    data = [(f"TXN-{r['id']:08X}", r["kind"], r["note"] or "-", (_m(r["amount"], True), "good" if r["amount"] > 0 else "bad"),
             _m(r["balance"]), utc(r["ts"])) for r in rows]
    cols = [("TXN ID", 15, "l", False), ("Type", 15, "l", False), ("Note", 18, "l", False),
            ("Change", 13, "r", False), ("Balance", 13, "r", False), ("Time (UTC)", 14, "r", False)]
    return build(get("brand"), "Account Statement", _who(u),
                 [("Current balance", _m(u["balance"])), ("Entries", f"{n:,}"),
                  ("Total in", _m(agg["i"])), ("Total out", _m(agg["o"]))],
                 [("Real-wallet movements (newest first)", cols, data)], _cap_note(n, len(rows)))


# ───────────── payments ─────────────
def payments_pdf(u):
    lim = _limit()
    out = []
    totals = {}
    for kind in ("deposit", "withdrawal"):
        rows = db("SELECT * FROM payments WHERE uid=? AND kind=? ORDER BY id DESC LIMIT ?", (u["id"], kind, lim), "all")
        totals[kind] = db("SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM payments WHERE uid=? AND kind=? "
                          "AND status IN ('Credited','Paid')", (u["id"], kind), "one")
        data = [(utc(r["ts"]), _m(r["amount"]), r["asset"] or "-",
                 (r["status"], "good" if r["status"] in ("Credited", "Paid") else "bad" if r["status"] == "Cancelled" else "muted"),
                 r["tx"] or "-") for r in rows]
        cols = [("Date (UTC)", 15, "l", False), ("Amount", 12, "r", False), ("Asset", 17, "l", False),
                ("Status", 11, "l", False), ("TX / Reference", 45, "l", True)]
        out.append(("Deposits" if kind == "deposit" else "Withdrawals", cols, data))
    d, w = totals["deposit"], totals["withdrawal"]
    return build(get("brand"), "Payment History", _who(u),
                 [("Total deposited", _m(d["s"])), ("Deposits", str(d["n"])),
                  ("Total withdrawn", _m(w["s"])), ("Withdrawals", str(w["n"]))], out)


# ───────────── games ─────────────
def games_pdf(u):
    n = db("SELECT COUNT(*) n FROM history WHERE uid=?", (u["id"],), "one")["n"]
    agg = db("SELECT COALESCE(SUM(bet),0) b, COALESCE(SUM(payout),0) p, "
             "COALESCE(SUM(CASE WHEN payout>bet THEN 1 END),0) w FROM history WHERE uid=?", (u["id"],), "one")
    rows = db("SELECT * FROM history WHERE uid=? ORDER BY ts DESC LIMIT ?", (u["id"], _limit()), "all")
    data = []
    for r in rows:
        net = round(r["payout"] - r["bet"], 2)
        data.append((utc(r["ts"]), r["game"], _m(r["bet"]), _m(r["payout"]),
                     (_m(net, True), "good" if net > 0 else "bad" if net < 0 else "muted"), r["gid"] or "-"))
    cols = [("Date (UTC)", 14, "l", False), ("Game", 10, "l", False), ("Bet", 11, "r", False),
            ("Payout", 11, "r", False), ("Net", 11, "r", False), ("Game ID", 22, "l", True)]
    by = db("SELECT game, COUNT(*) n, SUM(bet) b, SUM(payout) p FROM history WHERE uid=? GROUP BY game", (u["id"],), "all")
    sumrows = [(r["game"], str(r["n"]), _m(r["b"]), _m(r["p"]),
                (_m(r["p"] - r["b"], True), "good" if r["p"] > r["b"] else "bad" if r["p"] < r["b"] else "muted"))
               for r in by]
    scols = [("Game", 20, "l", False), ("Played", 10, "r", False), ("Total bet", 16, "r", False),
             ("Total payout", 16, "r", False), ("Net", 16, "r", False)]
    return build(get("brand"), "Game History", _who(u),
                 [("Games played", f"{n:,}"), ("Wins", str(agg["w"])), ("Total bet", _m(agg["b"])),
                  ("Net result", _m(agg["p"] - agg["b"], True))],
                 [("By game", scols, sumrows), ("All games (newest first)", cols, data)], _cap_note(n, len(rows)))


# ───────────── referral ─────────────
def referral_rows(uid):
    """Referred players: (user row, wagered since join, deposited since join, earned for referrer)."""
    out = []
    for r in db("SELECT * FROM users WHERE ref_by=? ORDER BY ref_ts DESC, joined DESC", (uid,), "all"):
        since = r["ref_ts"] or r["joined"] or 0
        w = db("SELECT COALESCE(SUM(bet),0) s FROM history WHERE uid=? AND ts>=?", (r["id"], since), "one")["s"]
        d = db("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE uid=? AND kind='deposit' AND status='Credited' AND ts>=?",
               (r["id"], since), "one")["s"]
        e = db("SELECT COALESCE(SUM(amount),0) s FROM ref_earn WHERE referrer=? AND referred=?", (uid, r["id"]), "one")["s"]
        out.append((r, w, d, e))
    return out


def referral_pdf(u):
    ref = referral_rows(u["id"])
    ew = db("SELECT COALESCE(SUM(amount),0) s FROM ref_earn WHERE referrer=? AND kind='wager'", (u["id"],), "one")["s"]
    ed = db("SELECT COALESCE(SUM(amount),0) s FROM ref_earn WHERE referrer=? AND kind='deposit'", (u["id"],), "one")["s"]
    data = [((r["name"] or "Player")[:28], "@" + (r["username"] or "-"), utc(r["ref_ts"] or r["joined"], "%d/%m/%y"),
             _m(w), _m(d), (_m(e), "good" if e > 0 else "muted")) for r, w, d, e in ref]
    cols = [("Player", 20, "l", False), ("Username", 16, "l", False), ("Joined", 11, "l", False),
            ("Wagered", 13, "r", False), ("Deposited", 13, "r", False), ("You earned", 13, "r", False)]
    log = db("SELECT e.*, u.name FROM ref_earn e LEFT JOIN users u ON u.id=e.referred WHERE e.referrer=? "
             "ORDER BY e.id DESC LIMIT ?", (u["id"], _limit()), "all")
    ldata = [(utc(r["ts"]), (r["name"] or str(r["referred"]))[:26], r["kind"].title(), _m(r["base"]),
              (_m(r["amount"], True), "good")) for r in log]
    lcols = [("Date (UTC)", 16, "l", False), ("Player", 24, "l", False), ("Type", 12, "l", False),
             ("Their amount", 16, "r", False), ("Your share", 16, "r", False)]
    return build(get("brand"), "Referral Portfolio", _who(u),
                 [("Referred players", str(len(ref))), ("Lifetime earned", _m(ew + ed)),
                  ("Wager earned", _m(ew)), ("Deposit earned", _m(ed)),
                  ("Ready to claim", _m(u["ref_pending"] or 0)), ("Claimed", _m(u["ref_claimed"] or 0))],
                 [("Referred players (deposit and wager counted from each join date)", cols, data),
                  ("Earnings log (newest first)", lcols, ldata)])
