# @cached can't set a per-key TTL — WRONG

**Claim (Oct 2, agent):** `@cached` only accepts a fixed `ttl` in seconds, so the
invoice cache, which needs a TTL that depends on the invoice's status, can't use it.

## Evidence the claim rested on

The agent read only the signature:

```python
# billing/cache/decorators.py
def cached(ttl: int = 300, key: Callable[..., str] | None = None, **opts):
```

It never opened `**opts`, which is where the problem is.

## Correction (Oct 18, teammate)

`**opts` is forwarded to `CacheBackend.set`, which accepts `ttl_fn`:

```python
# billing/cache/backend.py#L88-L96
def set(self, key, value, ttl=None, ttl_fn=None):
    if ttl_fn is not None:
        ttl = ttl_fn(value)
    ...
```

- Code: https://github.com/acme/billing-svc/blob/3f2a91c/billing/cache/backend.py#L88-L96
- Usage elsewhere: https://github.com/acme/billing-svc/blob/3f2a91c/billing/plans/views.py#L41

## What this affects

`@raw-redis` (PR #412) was chosen only because of this claim. `@fixture-leak` is
unaffected.
