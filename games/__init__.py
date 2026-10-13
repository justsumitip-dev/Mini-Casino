"""Games package. Is folder me jo bhi file `register(Game(...))` karti hai wo apne aap load ho jaati hai.

  games/tower.py   Tower
  games/mines.py   Mines
  games/dice.py    Dice match vs bot
  games/common.py  shared bet system (kisi game me nahi, bas helpers)

Naya game: tower.py ko copy karo, naam badlo, logic likho. main.py ya admin.py me kuch nahi badalna.
"""
import importlib
import pkgutil

from aiogram import Router

from .registry import GAMES, Game, register  # noqa: F401
from . import common

for _m in pkgutil.iter_modules(__path__):
    if _m.name not in ("common", "registry"):
        importlib.import_module(f"{__name__}.{_m.name}")

router = Router(name="games")
for _g in sorted(GAMES.values(), key=lambda g: g.order):
    router.include_router(_g.router)
router.include_router(common.router)  # sabse last (custom-bet state handler)


def commands():
    """Telegram command menu ke liye [(command, description)]."""
    return [(g.key, g.cmd_desc or g.title) for g in sorted(GAMES.values(), key=lambda g: g.order)]
