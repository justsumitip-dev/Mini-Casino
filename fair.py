"""Provably fair (commit-reveal): game shuru hone par seed ka SHA-256 hash dikhta hai,
game khatam hone par seed reveal hota hai. Koi bhi verify kar sakta hai."""
import hashlib
import hmac
import secrets


def new_seed():
    return secrets.token_hex(32)


def seed_hash(seed):
    return hashlib.sha256(seed.encode()).hexdigest()


def _int(seed, uid, nonce, tag, n):
    d = hmac.new(seed.encode(), f"{uid}:{nonce}:{tag}".encode(), hashlib.sha256).hexdigest()
    return int(d[:13], 16) % n


def tower_bombs(seed, uid, nonce, cols, levels):
    """Har floor par 1 bomb ka column."""
    return [_int(seed, uid, nonce, f"tower:{L}", cols) for L in range(levels)]


def mines_positions(seed, uid, nonce, m, grid=25):
    pool = list(range(grid))
    for i in range(grid - 1, 0, -1):
        j = _int(seed, uid, nonce, f"mines:{i}", i + 1)
        pool[i], pool[j] = pool[j], pool[i]
    return pool[:m]