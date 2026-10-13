"""Har game apni file me ek `Game(...)` banata hai aur `register()` karta hai.
Naya game jodna: games/ me nayi file banao (tower.py ko copy karke), bas. Baaki sab auto hai:
games menu, /command, admin ON/OFF, rename aur game ki apni settings.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from aiogram import Router

from database import db, register as reg_setting


@dataclass
class Game:
    key: str                       # 'dice' (callback + command + DB key)
    title: str                     # 'Dice' (admin panel se rename ho sakta hai)
    build: Callable                # build(uid) -> Screen  (game ka menu)
    router: Router                 # is game ke handlers
    order: int = 99                # games menu me position
    usage: str = ""                # '/dice <bet>' (games menu me dikhta hai)
    cmd_desc: str = ""             # Telegram command menu ka text
    settings: list = field(default_factory=list)   # [(name, default, label, kind)] -> admin panel me
    resume: Optional[Callable] = None              # resume(uid, session) -> Screen | None
    background: Optional[Callable] = None          # async background(bot) (timeout sweeper etc.)


GAMES: dict = {}


def register(g: Game):
    GAMES[g.key] = g
    db("INSERT OR IGNORE INTO games VALUES(?,?,1,?)", (g.key, g.title, g.order))
    grp = f"game:{g.key}"
    for name, default, label, kind in g.settings:
        reg_setting(f"{g.key}_{name}", default, f"{g.title}: {label}", kind, grp)
    # har game ke liye common overrides (blank = global setting use hoti hai)
    reg_setting(f"{g.key}_min", "", f"{g.title}: Min bet (blank = global)", "num", grp)
    reg_setting(f"{g.key}_max", "", f"{g.title}: Max bet (blank = global)", "num", grp)
    reg_setting(f"{g.key}_edge", "", f"{g.title}: House edge % (blank = global)", "edge", grp)
    return g
