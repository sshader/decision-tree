# Rules for proposing decision-tree updates

The tree is the human's map of *why* they are doing each piece of work. They
edit it heavily by hand. Your job is to propose a few high-value additions, not
to log the session. When in doubt, leave it out.

## Format

One line per node, indented two spaces per level under the node that caused it:

```
- [?] <kind> <name>: <title> [#status] [{key:value} ...]
  > optional one-line note
```

- kinds: `goal`, `q` (question), `finding`, `decision`
- status: `#open` (default, omit it), `#done`, `#parked`, `#wrong`, `#kept`
  (`#kept` = re-checked after something above it went wrong, still valid)
- attachments: `{pr:412}`, `{pr:org/repo#412 merged}`, `{session:<id> <dir>}`
  (Codex: `{session:codex:<id> <dir>}`; a node can have several sessions),
  `{branch:<name>}`, `{repo:org/repo}` (inherited by children), `{link:<url>}`
- time: `{at:2026-10-18 14:02}` on every node you add, from when it happened
- refer to another node with `@name`
- a note starting `next:` is a "where was I" reminder: `> next: benchmark msgpack on the 10MB fixture`

## What deserves a node

Only add a node if it passes one of these tests:
"If this turned out to be wrong, would some of the human's work need redoing?"
"Would they mention it at standup?"

- **goal**: only when the human states a new outcome. Phrase it as the
  user-facing requirement ("Invoice totals are never more than a minute
  stale"), not the work ("add caching"). Never invent goals. A goal also
  carries the context someone needs to pick it up cold, as notes in the
  human's own terms (up to 4 lines):
  - `> why: ...` the problem or pain behind it
  - `> done when: ...` what success looks like
  - `> constraints: ...` hard requirements, preferences, things ruled out
  - `> from: ...` where it came from (a teammate, a ticket, a thread)
  If the human explained the goal at length, put the fuller brief in
  `details/<goal-name>.md` (see Write-ups).
- **q**: a question that was actually investigated and shaped later work. Not
  every lookup.
- **finding**: a conclusion later work relies on. If it was not verified (read
  the code, ran it, saw a test), say so in a note: `> unverified: inferred
  from function name`. This matters more than anything else you write.
- **decision**: a choice between real alternatives. Name the rejected option in
  the title or note if it's short.

Do NOT add: file reads, routine edits, retries, tool errors fixed immediately,
style nits, restatements of nodes that already exist.

## Next steps

At the end of a session, if work is unfinished, propose one `> ? next: ...`
note on the node where the human should pick up. Make it concrete enough to
act on cold a week later. Suggest removing `next:` notes that are now done.

## Write-ups (proof)

A goal's write-up is its brief: the problem in the human's words, examples
they gave, what done looks like, constraints. Quote them rather than
paraphrase where you can.

For a finding other work relies on, the evidence goes in
`details/<name>.md` next to the tree file, not in the outline. Write one only
when the evidence is concrete (code you read, a test you ran, a doc you
checked), and keep it under ~40 lines:

```
**Claim:** one or two sentences.

## Evidence
Minimal snippet (<= 15 lines) with a path and line numbers, plus a permalink
(https://github.com/org/repo/blob/<sha>/path#L10-L20) or doc URL.

## How it was verified
What was run or read. Say plainly if part of it is inferred.

## Caveats
What this does not establish.
```

If the node is `?`, start the write-up with `> ? proposed by agent`.

## Limits

- At most 5 new nodes per session; 0-3 is typical. Proposing nothing is fine.
- Titles at most 80 characters. At most one note line per node (goals: see above).
- Prefer updating existing nodes over adding new ones. Work often continues
  across chats and directories: if this session continues an existing node,
  attach the session there instead of creating a near-duplicate.
- Names: 1-3 lowercase hyphenated words that are memorable on their own
  (`pool-leak`, `pickle-slow`, `no-ttl`). Unique in the tree. Never numbered
  (no `q1`, `f2`).

## Marking your work

Everything you write must be reviewable by the human:

- New nodes start with `?`: `- ? finding pool-leak: Test fixture never closes clients`
- Suggestions about existing nodes are `?` notes under them:
  `> ? suggest #wrong: teammate says ttl_fn= exists`
- You may append `{session:}`, `{pr:}` or `{branch:}` attachments to existing
  lines directly. Never otherwise edit or delete the human's lines.
