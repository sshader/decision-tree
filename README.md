# decision-tree

A hand-edited outline of *why* you're doing each piece of agent-assisted work,
with a viewer that shows what to re-check when something turns out wrong.

```
./install.sh                            # puts `dtree` on your PATH and installs the /tree skill
dtree serve examples/tree.md   # viewer, live-reloads as you edit
dtree sessions --grep invoice   # find related chats across all dirs (Claude Code + Codex)
dtree extract $(dtree sessions --grep invoice --paths)
                                        # propose nodes from those sessions together
```

Your tree lives at `$DTREE` or `~/.decision-tree/tree.md`.

## Format

```
- goal fresh-invoices: Invoices page p99 < 300ms; totals never > 1 min stale {repo:acme/billing-svc}
  - q cache-patterns: How does billing-svc cache today? {session:4f1c...}
    - finding no-ttl: @cached can't set a per-key TTL #wrong
      > Teammate: `ttl_fn=` exists.
      - decision raw-redis: Use raw RedisClient {pr:412}
```

- kinds: `goal`, `q`, `finding`, `decision`; a child is something you looked
  into *because of* its parent
- status: `#done` `#parked` `#wrong` `#kept` (re-checked under a wrong node, still valid)
- attachments: `{pr:}` `{session:<id> <dir>}` `{branch:}` `{repo:}` `{link:}`; `@name` refers to a node.
  One tree spans all your repos; a node can carry sessions from several chats and directories.
- `{at:2026-10-18 14:02}` dates a node (powers the Log view and "where was I");
  `> next: ...` notes are reminders shown at the top of each goal
- `details/<name>.md` next to the tree is the write-up/proof for node `<name>`
  (claim, snippet, permalinks, how verified); click a node in the viewer to read it
- `?` at the start of a node or note = proposed by an agent, not yet accepted.
  Delete the `?` to accept.

Full rules for agents: `skill/tree/rules.md`.

## Live capture with Claude Code

After `./install.sh`, run `/tree` in a session (optionally `/tree no-ttl was wrong`).
