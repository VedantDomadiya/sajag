"""In-process rate limiting so the public API can't be used as a free proxy to a paid Gemini key.

Three layers per endpoint ("bucket"):
1. per client: a sliding window per IP (IPv6 grouped by /64);
2. fair share: once the shared soft budget is spent, only clients above their fair share are refused, so a few heavy
   clients can't lock out a normal live call;
3. hard ceiling: never exceeded, however many fresh IPs arrive. This is the cost cap.

Client entries live in an LRU (OrderedDict), so tracking, refreshing and evicting are all O(1). Eviction can forget a
quiet client, but never lifts the hard ceiling. Limits are per instance; put an edge limiter (Cloud Armor) in front
for real enforcement, and set a quota on the key.
"""

import ipaddress
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    per_client: int
    window_s: float
    fair_share: int
    soft_global: int
    hard_global: int


class RateLimited(Exception):
    """Raised when a request is over any of the limits."""


def _expire(q: deque[float], now: float, window: float) -> None:
    while q and now - q[0] > window:
        q.popleft()


class RateLimiter:
    def __init__(
        self, policies: dict[str, Policy], max_tracked: int = 10_000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.policies = policies
        self.max_tracked = max_tracked
        self.clock = clock
        self._clients: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._global: dict[str, deque[float]] = {bucket: deque() for bucket in policies}

    def check(self, bucket: str, client: str) -> None:
        """Record one request, or raise RateLimited without recording it."""
        p = self.policies[bucket]
        now = self.clock()
        key = (bucket, client)
        q = self._clients.get(key)
        if q is None:
            if len(self._clients) >= self.max_tracked:
                self._clients.popitem(last=False)  # least recently active client
            q = self._clients[key] = deque()
        else:
            self._clients.move_to_end(key)
        g = self._global[bucket]
        _expire(q, now, p.window_s)
        _expire(g, now, p.window_s)
        if len(q) >= p.per_client or len(g) >= p.hard_global or (len(g) >= p.soft_global and len(q) >= p.fair_share):
            raise RateLimited(bucket)
        q.append(now)
        g.append(now)

    def reset(self) -> None:
        self._clients.clear()
        for g in self._global.values():
            g.clear()

    @property
    def tracked(self) -> int:
        return len(self._clients)


def client_key(peer: str | None, forwarded_for: str, trusted_from_right: int) -> str:
    """Who to rate-limit. Behind a proxy, take the IP the *trusted* proxy appended to X-Forwarded-For, counting from
    the right (entries further left are client-supplied and spoofable). IPv6 clients are grouped by /64."""
    ip = peer or "unknown"
    if trusted_from_right > 0:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if len(parts) >= trusted_from_right:
            ip = parts[-trusted_from_right]
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return ip
