"""RateLimiter and client_key, tested with a fake clock (no sleeping, no HTTP)."""

import pytest

from app.ratelimit import Policy, RateLimited, RateLimiter, client_key


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def limiter(clock, **kw):
    policy = Policy(**{"per_client": 3, "window_s": 60, "fair_share": 2, "soft_global": 5, "hard_global": 8, **kw})
    return RateLimiter({"b": policy}, max_tracked=kw.pop("max_tracked", 100), clock=clock)


def hit(rl, client):
    try:
        rl.check("b", client)
        return True
    except RateLimited:
        return False


def test_per_client_limit_and_window_expiry():
    clock = Clock()
    rl = limiter(clock)
    assert [hit(rl, "a") for _ in range(4)] == [True, True, True, False]
    clock.t += 61
    assert hit(rl, "a")


def test_refused_requests_are_not_counted():
    clock = Clock()
    rl = limiter(clock, per_client=1)
    assert hit(rl, "a") and not hit(rl, "a") and not hit(rl, "a")
    clock.t += 61
    assert hit(rl, "a")


def test_fair_share_protects_light_clients_once_soft_budget_is_spent():
    rl = limiter(Clock())
    for c in ("x", "y"):  # heavy clients spend the soft budget (5) between them
        for _ in range(3):
            hit(rl, c)
    assert not hit(rl, "x")  # heavy client is over its fair share
    assert hit(rl, "light")  # a newcomer still gets through


def test_hard_ceiling_holds_when_ips_rotate():
    rl = limiter(Clock())
    results = [hit(rl, f"10.0.0.{i}") for i in range(12)]
    assert results.count(True) == 8 and results[8:] == [False] * 4


def test_lru_eviction_is_bounded_and_keeps_active_clients():
    clock = Clock()
    rl = RateLimiter({"b": Policy(3, 60, 2, 1000, 1000)}, max_tracked=2, clock=clock)
    hit(rl, "old")
    hit(rl, "active")
    hit(rl, "old")  # "old" becomes most recent, "active" least
    hit(rl, "new")  # evicts "active"
    assert rl.tracked == 2
    assert [hit(rl, "old") for _ in range(2)] == [True, False]  # old's count survived eviction of another key


@pytest.mark.parametrize(
    "peer, xff, n, expected",
    [
        ("10.0.0.1", "6.6.6.6, 203.0.113.9", 1, "203.0.113.9"),  # spoofed left entry ignored
        ("10.0.0.1", "203.0.113.9, 198.51.100.7", 2, "203.0.113.9"),  # behind an extra load balancer
        ("10.0.0.1", "203.0.113.9", 0, "10.0.0.1"),  # no proxy trust: socket peer
        ("10.0.0.1", "", 1, "10.0.0.1"),  # header missing: fall back to peer
        ("10.0.0.1", "2001:db8::1", 1, "2001:db8::/64"),  # IPv6 grouped by /64
        (None, "", 0, "unknown"),
        ("10.0.0.1", "not-an-ip", 1, "not-an-ip"),
    ],
)
def test_client_key(peer, xff, n, expected):
    assert client_key(peer, xff, n) == expected
