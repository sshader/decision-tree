# test_rollover fails only when CI runs 23:00–00:00 UTC

**Claim:** The flake isn't random. `test_rollover` fails when "now" and
"now + 1h" fall on different UTC dates.

## Evidence

All 14 failures in the last 30 days of CI started between 23:02 and 23:58 UTC;
0 of 270 runs outside that window failed.
Query: https://ci.acme.dev/insights?test=test_rollover&range=30d

Reproduced locally:

```bash
faketime '2026-09-22 23:30:00' pytest tests/test_rollover.py -k rollover   # fails
faketime '2026-09-22 12:00:00' pytest tests/test_rollover.py -k rollover   # passes
```

## Root cause

```python
# scheduler/rollover.py#L52
next_day = date.today() + timedelta(days=1)   # local date, compared against UTC timestamps
```

https://github.com/acme/scheduler/blob/a81c0de/scheduler/rollover.py#L52
