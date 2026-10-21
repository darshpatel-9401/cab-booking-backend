import pytest
from fastapi import HTTPException

import ratelimit
from ratelimit import rate_limit

USER = {"id": "u1", "email": "a@example.com"}


class FakePipeline:
    def __init__(self, fake):
        self.fake = fake
        self.ops = []

    def incr(self, key):
        self.ops.append(("incr", key))

    def ttl(self, key):
        self.ops.append(("ttl", key))

    def execute(self):
        results = []
        for op, key in self.ops:
            if op == "incr":
                self.fake.counts[key] = self.fake.counts.get(key, 0) + 1
                results.append(self.fake.counts[key])
            else:
                results.append(self.fake.ttls.get(key, -1))
        return results


class FakeRedis:
    def __init__(self):
        self.counts = {}
        self.ttls = {}
        self.expired = []

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        self.expired.append((key, seconds))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    redis = FakeRedis()
    monkeypatch.setattr(ratelimit, "redis_sync", redis)
    return redis


def test_calls_under_the_limit_pass(fake):
    check = rate_limit("t", 3, 60)
    for _ in range(3):
        assert check(USER) == USER


def test_the_call_over_the_limit_gets_429_with_retry_after(fake):
    check = rate_limit("t", 2, 60)
    check(USER)
    check(USER)

    with pytest.raises(HTTPException) as error:
        check(USER)

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "60"


def test_the_window_expiry_is_set_on_the_first_call(fake):
    rate_limit("t", 3, 60)(USER)
    assert fake.expired == [("rl:t:u1", 60)]


def test_a_counter_that_lost_its_expiry_is_healed(fake):
    fake.counts["rl:t:u1"] = 5
    fake.ttls["rl:t:u1"] = -1
    rate_limit("t", 100, 60)(USER)
    assert ("rl:t:u1", 60) in fake.expired


def test_users_have_separate_counters(fake):
    check = rate_limit("t", 1, 60)
    check({"id": "u1", "email": "a@example.com"})
    assert check({"id": "u2", "email": "b@example.com"})["id"] == "u2"


def test_it_lets_requests_through_when_redis_fails(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    class BrokenRedis:
        def pipeline(self, transaction=True):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(ratelimit, "redis_sync", BrokenRedis())
    assert rate_limit("t", 1, 60)(USER) == USER


def test_it_does_nothing_when_switched_off(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")

    class MustNotBeUsed:
        def pipeline(self, transaction=True):
            raise AssertionError("redis must not be used")

    monkeypatch.setattr(ratelimit, "redis_sync", MustNotBeUsed())
    assert rate_limit("t", 1, 60)(USER) == USER