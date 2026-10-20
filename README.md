# decision-tree

A lightweight map of your agent-assisted work: what you're trying to achieve,
what you looked into *because of* what, which conclusions turned out wrong, and
where to pick up again. It's a Markdown outline you edit by hand, a viewer, and
a small CLI plus a Claude Code skill that propose updates from your sessions.

## Install

Requires Python 3.9+, and the `claude` CLI for `dtree extract`.

```sh
git clone <this repo> ~/src/decision-tree
cd ~/src/decision-tree
./install.sh
```

`install.sh` creates two symlinks, so a `git pull` updates both:

- `~/.local/bin/dtree` → `dt.py` (set `BIN_DIR` to put it elsewhere)
- `~/.claude/skills/tree` → `skill/tree/` (the `/tree` skill)

Your tree lives at `~/.decision-tree/tree.md`, with write-ups in
`~/.decision-tree/details/`. Set `DTREE=/path/to/tree.md` to use a different
file. One tree covers all your repos.

To uninstall, delete the two symlinks.

## Daily use

```sh
dtree serve                     # open the viewer; it reloads as you edit
```

At the end of a Claude Code session, run:

```
/tree
/tree no-ttl was wrong, teammate says ttl_fn= exists     # with guidance
```

The agent reads your tree, finds where this session fits, and adds a few
proposed nodes (lines starting with `?`), plus a `next:` reminder if the work
is unfinished. Review them in your editor: delete the `?` to accept, rewrite,
or delete.

For past sessions, or chats where you forgot to run `/tree`:

```sh
dtree sessions --grep "connection pool"       # find related chats in any directory
dtree extract $(dtree sessions --grep "connection pool" --paths)
```

`extract` prints proposals and doesn't change any files. Paste the ones you
want into the tree.

## The tree file

```markdown
- goal fresh-invoices: Invoices page p99 < 300ms; totals never > 1 min stale {repo:acme/billing-svc}
  > why: customers see stale totals right after paying
  > done when: p99 < 300ms on the 10MB invoice fixture
  > next: decide between @cached + ttl_fn and keeping #412
  - q cache-patterns: How does billing-svc cache today? {session:4f1c2a9e ~/src/billing-svc} {at:2026-10-02 10:05}
    - finding no-ttl: @cached can't set a per-key TTL #wrong
      > Teammate: `ttl_fn=` exists. Agent never read the source.
      - decision raw-redis: Use raw RedisClient {pr:412} {branch:sarah/invoice-cache}
```

A node is `- <kind> <name>: <title>`. A child is something you looked into
*because of* its parent.

| Part | Values |
|---|---|
| kind | `goal` (phrased as an outcome, not the work), `q` (question), `finding`, `decision` |
| name | short and memorable: `no-ttl`, `pool-leak`. Use `@name` to refer to it elsewhere |
| status | none (open), `#done`, `#parked`, `#wrong`, `#kept` (re-checked under a wrong node, still valid) |
| attachments | `{pr:412}` `{pr:org/repo#412 merged}` `{session:<id> <dir>}` `{session:codex:<id> <dir>}` `{branch:x}` `{repo:org/repo}` `{link:url}` |
| time | `{at:2026-10-18 14:02}` puts the node in the Log view and "where was I" |
| notes | `> text` on the lines below a node. On goals, use `why:`, `done when:`, `constraints:`, `from:`. `next:` marks a reminder |
| proposed | a node or note starting with `?` was written by an agent and hasn't been accepted yet |

**Write-ups.** `details/<name>.md` next to the tree holds the long form for node
`<name>`. For a goal, that's the brief. For a finding, it's the proof: the
claim, a minimal snippet, permalinks to code and docs, how it was verified, and
caveats. Click a node in the viewer to read it.

**When something turns out wrong,** mark it `#wrong` and add a note saying why.
Everything under it is flagged "re-check" in the viewer. Re-check those, then
mark the ones that still hold `#kept`.

## The viewer

- **Overview:** one card per goal, most recent first, with its why, its `next:`
  reminders, counts, and the latest session.
- **Goal tabs:** the tree for one goal, or switch to **Log** for a
  chronological list. The side panel shows where you were, a resume command
  (click to copy `cd <dir> && claude --resume <id>`), `next:` reminders, things
  to re-check, open questions, and unconfirmed proposals.
- **Click a node** to see its details and write-up. Press Esc to close.

`dtree serve examples/tree.md` shows a made-up example with every feature.

## CLI reference

```
dtree serve [TREE] [--port 8765] [--no-open]
dtree sessions [--grep TEXT]... [--dir TEXT] [--since YYYY-MM-DD] [--limit N] [--paths]
dtree condense TRANSCRIPT          # compact text version of one transcript
dtree extract TRANSCRIPT... [--tree TREE] [--print-prompt]
```

`sessions` searches Claude Code transcripts (`~/.claude/projects`) and Codex
transcripts (`~/.codex/sessions`), and leaves out the runs `extract` itself
creates. `extract` sends condensed transcripts, your tree and
`skill/tree/rules.md` to `claude -p`. Use `--print-prompt` to see exactly what
gets sent.

## Tuning

`skill/tree/rules.md` controls what agents propose (when a node is worth
adding, limits, naming, write-up template). Both `/tree` and `extract` use it,
so edit that one file when proposals are too chatty or miss things.
