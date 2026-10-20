# Example decision tree (fabricated, for exercising the viewer)

- goal fresh-invoices: Invoices page p99 < 300ms; totals never > 1 min stale {repo:acme/billing-svc} {at:2026-10-02 09:30}
  > From the #billing thread, Oct 2. Today p99 is 1.4s.
  > next: decide between @cached + ttl_fn and keeping #412, now that @no-ttl is wrong
  - q cache-patterns: How does billing-svc cache today? {session:4f1c2a9e-0b7d-4c1e-9a55-1d2e3f4a5b6c ~/src/billing-svc} {at:2026-10-02 10:05}
    - finding two-patterns: Two patterns exist: @cached decorator and raw RedisClient {at:2026-10-02 10:40}
    - finding no-ttl: @cached can't set a per-key TTL #wrong {at:2026-10-02 10:52}
      > Teammate (Oct 18): `ttl_fn=` exists. Agent inferred this from the signature, never read the source.
      - decision raw-redis: Use raw RedisClient for the invoice cache {pr:412} {branch:sarah/invoice-cache} {at:2026-10-02 11:30}
        - q pool-exhausted: Tests fail with "connection pool exhausted" #done {at:2026-10-06 14:10}
          - finding fixture-leak: Test fixture never closes Redis clients #kept {pr:415 merged} {at:2026-10-06 15:20}
        - q slow-p99: Why is GET /invoices still 800ms p99? {session:9a8b7c6d-1111-2222-3333-444455556666 ~/src/billing-svc} {session:codex:0199a1b2-c3d4 ~/src/perf-scripts} {at:2026-10-14 13:00}
          - finding pickle-slow: Pickle serialization of large invoices dominates {at:2026-10-14 16:45}
            > Verified with py-spy flamegraph.
          - decision msgpack: Switch cache serialization to msgpack #parked {at:2026-10-15 10:00}
            > next: benchmark msgpack vs pickle on the 10MB invoice fixture
  - q invalidation: Does the write path need explicit cache invalidation? {at:2026-10-19 11:00}
    - ? finding webhook-writes: Payment webhooks write invoices without going through InvoiceService {at:2026-10-19 11:40}
      > unverified: inferred from grepping for `Invoice.save`
      > ? suggest: this may matter for @raw-redis too

- goal release-unblocked: Nightly release isn't blocked by flaky CI {repo:acme/scheduler} {at:2026-09-22 09:00}
  - q rollover-flake: Why does test_rollover fail ~5% of CI runs? #done {session:7e7e1d2c-aaaa-bbbb-cccc-ddddeeeeffff ~/src/scheduler} {at:2026-09-22 09:15}
    - finding not-a-race: Not a worker race; fails with workers=1 #done {at:2026-09-22 10:30}
    - finding not-ordering: Not test-order dependent; fails alone with --count=200 #done {at:2026-09-22 11:10}
    - finding dst-boundary: Fails only when CI runs 23:00-00:00 UTC #done {at:2026-09-23 09:40}
      - decision freeze-clock: Freeze the clock in the test {pr:88 merged} {at:2026-09-23 11:00}
    - q prod-rollover: Does prod have the same midnight bug? #parked {at:2026-09-23 11:30}
      > next: check prod logs around 00:00 UTC for rollover errors

- goal big-exports: Users can export 1M-row reports without the tab crashing {repo:acme/web} {at:2026-10-08 10:00}
  - finding browser-only: Export must run in the browser, no server #wrong {at:2026-10-08 10:00}
    > PM (Oct 15): server-side generation is fine now.
    - decision web-workers: Stream CSV from Web Workers {at:2026-10-08 15:00}
      - finding worker-plumbing: Worker message plumbing works {pr:201 merged} {at:2026-10-10 12:00}
      - finding chunked-writer: Chunked writer keeps memory flat {pr:205} {at:2026-10-13 17:20}
  - ? q server-export: Can the existing report job generate CSVs server-side? {at:2026-10-16 09:10}
