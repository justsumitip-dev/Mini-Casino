"""Chhota raw Bot API client (aiohttp). Rich Messages + colored buttons + photo card ke liye,
kyunki ye naye fields aiogram ke har version me nahi hote."""
import asyncio
import json
import logging
import time

import aiohttp

from config import BOT_TOKEN

log = logging.getLogger("tg")
_session = None
_avatars = {}  # uid -> (time, bytes|None)


class ApiError(Exception):
    def __init__(self, code, desc):
        super().__init__(f"{code}: {desc}")
        self.code, self.desc = code, desc or ""


def _sess():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40))
    return _session


async def _post(method, make_kwargs):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for attempt in range(3):
        async with _sess().post(url, **make_kwargs()) as r:
            data = await r.json(content_type=None)
        if data.get("ok"):
            return data["result"]
        if data.get("error_code") == 429 and attempt < 2:
            await asyncio.sleep(data.get("parameters", {}).get("retry_after", 1) + 0.3)
            continue
        raise ApiError(data.get("error_code"), data.get("description"))


async def call(method, **params):
    return await _post(method, lambda: {"json": params})


async def call_file(method, field, data, filename="card.png", content_type="image/png", **params):
    """Multipart upload (sendPhoto etc). params me dict/list ho to JSON ban jaata hai."""
    def make():
        form = aiohttp.FormData()
        for k, v in params.items():
            if v is None:
                continue
            form.add_field(k, v if isinstance(v, str) else json.dumps(v))
        form.add_field(field, data, filename=filename, content_type=content_type)
        return {"data": form}
    return await _post(method, make)


async def avatar(uid, ttl=3600):
    """User ki profile photo (bytes) ya None. 1 ghante cache."""
    hit = _avatars.get(uid)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = None
    try:
        r = await call("getUserProfilePhotos", user_id=uid, limit=1)
        if r.get("total_count"):
            sizes = r["photos"][0]
            pick = next((p for p in sizes if p["width"] >= 200), sizes[-1])
            f = await call("getFile", file_id=pick["file_id"])
            async with _sess().get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f['file_path']}") as resp:
                if resp.status == 200:
                    data = await resp.read()
    except Exception as e:
        log.info("avatar fetch failed: %s", e)
    _avatars[uid] = (time.time(), data)
    return data


_me = {}


async def bot_username():
    if "u" not in _me:
        _me["u"] = (await call("getMe"))["username"]
    return _me["u"]


async def close():
    if _session and not _session.closed:
        await _session.close()
