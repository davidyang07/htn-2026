import hashlib
import random


def rng(seed: int, tick: int, agent_id: str, purpose: str) -> random.Random:
    """Deterministic generator for one (tick, agent, purpose) draw site.

    The key fully determines the stream, so results never depend on the order
    in which draws happen. Never cache or reuse the returned object.
    """
    key = f"{seed}|{tick}|{agent_id}|{purpose}"
    digest = hashlib.blake2b(key.encode()).digest()
    return random.Random(digest)
