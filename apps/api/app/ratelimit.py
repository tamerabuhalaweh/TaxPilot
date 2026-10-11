"""Failed-login rate limiting (Redis counters). Blocks brute force; failures fail closed.

Exceeded attempts return False (request must be rejected with 429); Redis errors
propagate so a down limiter cannot silently disable protection.
"""


class RedisRateLimiter:
    def __init__(self, client, max_attempts: int = 5, window_seconds: int = 900):  # type: ignore[no-untyped-def]
        self.client = client
        self.max_attempts = max_attempts
        self.window = window_seconds

    def _key(self, scope: str, identity: str) -> str:
        return f"tp:ratelimit:{scope}:{identity}"

    def hit(self, scope: str, identity: str) -> None:
        key = self._key(scope, identity)
        pipe = self.client.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, self.window)
        pipe.execute()

    def allowed(self, scope: str, identity: str) -> bool:
        count = self.client.get(self._key(scope, identity))
        return int(count or 0) < self.max_attempts

    def reset(self, scope: str, identity: str) -> None:
        self.client.delete(self._key(scope, identity))

    def retry_after(self, scope: str, identity: str) -> int:
        ttl = self.client.ttl(self._key(scope, identity))
        return max(int(ttl or 0), 0)
