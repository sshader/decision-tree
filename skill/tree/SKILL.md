---
name: tree
description: Propose updates to the user's decision tree (goals, questions, findings, decisions) based on this session. Use when the user runs /tree or asks to update their decision tree.
---

1. The tree file is `$DTREE` if set, otherwise `~/.decision-tree/tree.md`
   (`echo "${DTREE:-$HOME/.decision-tree/tree.md}"`). Create it if missing.
2. Read `rules.md` in this skill's directory and follow it exactly.
3. Read the whole tree, which spans all repos. Find the node this session is
   working under; it may have been started in another chat or directory. If it is
   genuinely unclear, ask one short question instead of guessing.
4. Gather attachments:
   - session: `{session:${CLAUDE_SESSION_ID} <cwd>}` with `<cwd>` from `pwd`, using `~`
     for the home directory (if the id shows as a literal placeholder, omit it)
   - branch: `git branch --show-current`
   - PR: `gh pr view --json number,state` if `gh` is available
   - time: `date '+%Y-%m-%d %H:%M'` for `{at:...}`
5. Edit the tree file directly. Write-ups go in `details/<name>.md` next to it.
6. Reply in at most 5 lines: what you added or suggested (by name), and
   anything you deliberately left out.

If the user passed text after /tree, treat it as guidance for this update
(e.g. "/tree no-ttl was wrong, teammate says ttl_fn exists"): $ARGUMENTS
