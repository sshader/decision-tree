# Pickle serialization of large invoices dominates

**Claim:** On cache hits for GET /invoices, most of the time is spent in
`pickle.loads`, not in Redis round trips.

## How it was verified

`py-spy record` against staging with the 10MB invoice fixture, 200 requests:

| Frame | Share of samples |
|---|---|
| `pickle.loads` | 61% |
| `redis.Connection.read_response` | 9% |
| serializer / view code | 22% |

Flamegraph: https://github.com/acme/perf-scripts/blob/main/runs/2026-10-14-invoices.svg

## Minimal snippet

```python
# billing/invoices/cache.py#L30-L34
def get_invoice(invoice_id):
    raw = redis.get(f"invoice:{invoice_id}")
    if raw:
        return pickle.loads(raw)   # 61% of request time on large invoices
```

## Caveats

- Measured on staging only; prod invoices are on average 3x smaller.
- Doesn't establish that msgpack would be faster. See `@msgpack`.
