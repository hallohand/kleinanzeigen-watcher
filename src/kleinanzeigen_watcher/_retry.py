from __future__ import annotations

import random


def exp_backoff(attempt: int, *, cap: float = 60.0) -> float:
    """Exponential backoff with jitter (full-jitter ±1s), capped at `cap` seconds."""
    return min(cap, 2.0 ** attempt + random.uniform(0, 1))
