#!/usr/bin/env python3
"""Decision tree helper.

  dtree serve [TREE]              serve the viewer, live-reloading TREE
  dtree sessions [--grep TEXT]    find transcripts across all projects (Claude Code + Codex)
  dtree condense TRANSCRIPT       print a compact version of a transcript
  dtree extract TRANSCRIPT...     ask `claude -p` to propose tree updates from one or
                                  more related sessions, e.g.
                                  dtree extract $(dtree sessions --grep invoice --paths)
                                  (--apply merges them into the tree as ? lines)
  dtree hooks install|uninstall   propose nodes automatically from Claude Code sessions

TREE defaults to $DTREE, then ~/.decision-tree/tree.md. Write-ups live in
details/<name>.md next to it. In Claude Code, run /tree to propose updates
from the current session. Full guide: README.md next to this script.
"""
import argparse
import fcntl
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "skill" / "tree" / "rules.md"
DEFAULT_TREE = Path(os.environ.get("DTREE", "~/.decision-tree/tree.md")).expanduser()
EXTRACT_PREAMBLE = "You are helping maintain a human's decision tree."
NEW_MARKER = "===== NEW SINCE LAST TREE UPDATE ====="
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
NODE_LINE = re.compile(r"^(\s*)[-*]\s+(?:\?\s+)?(\w+)\s+([a-z0-9][a-z0-9-]*)\s*:")
ATTACHABLE = re.compile(r"^\{(session|pr|branch):[^{}]+\}$")
STATE_DIR = DEFAULT_TREE.parent / ".hook-state"
HOOK_EVENTS = ("Stop", "PreCompact", "SessionEnd")
HOOK_TURNS = int(os.environ.get("DTREE_HOOK_TURNS", "6"))      # update after this many new prompts,
HOOK_MINUTES = int(os.environ.get("DTREE_HOOK_MINUTES", "30"))  # or after 2+ prompts and this long


def tree_path(arg):
    p = Path(arg).expanduser() if arg else DEFAULT_TREE
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# Decision tree\n\n")
        print(f"created {p}", file=sys.stderr)
    return p


# ---------- serve ----------

def cmd_serve(args):
    tree = tree_path(args.tree)
    details = tree.parent / "details"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self.send(HERE / "viewer.html", "text/html")
            elif path == "/tree.md":
                self.send(tree, "text/markdown", {"X-Tree-Path": str(tree)})
            elif path == "/details/":
                # {name: mtime} for every write-up, so the viewer knows which nodes have one
                found = {p.stem: p.stat().st_mtime for p in details.glob("*.md")} if details.is_dir() else {}
                self.send(json.dumps(found).encode(), "application/json")
            elif re.fullmatch(r"/details/[a-z0-9][a-z0-9-]*\.md", path) and (details / path[9:]).is_file():
                self.send(details / path[9:], "text/markdown")
            else:
                self.send_error(404)

        def send(self, src, ctype, extra=None):
            body = src if isinstance(src, bytes) else src.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"serving {tree} at {url}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------- transcripts ----------

def read_jsonl(path):
    """Yield (line number, parsed entry), skipping lines that aren't valid JSON."""
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f):
            try:
                yield n, json.loads(line)
            except json.JSONDecodeError:
                continue


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def tool_summary(name, inp):
    if not isinstance(inp, dict):
        return clip(inp, 150)
    for key in ("command", "file_path", "path", "pattern", "url", "query", "description", "prompt"):
        if key in inp:
            return clip(inp[key], 150)
    return clip(json.dumps(inp), 150)


def block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def condense(path, since=0):
    """Parse a Claude Code (or, best-effort, Codex) transcript into metadata + compact lines.

    With `since`, a marker goes before transcript line `since`, and meta["new_turns"]
    counts the user's prompts after it.
    """
    meta = {"path": str(path), "agent": "claude", "session": None, "cwd": None,
            "branches": [], "prs": set(), "start": None, "end": None, "first": "",
            "lines": 0, "new_turns": 0}
    out = []
    tool_names = {}  # tool_use id -> name, to recognize answers to the agent's questions
    marked = not since

    def note_meta(session=None, cwd=None, branch=None, ts=None):
        meta["session"] = meta["session"] or session
        meta["cwd"] = meta["cwd"] or cwd
        if branch and branch not in meta["branches"]:
            meta["branches"].append(branch)
        if ts:
            meta["start"] = meta["start"] or ts
            meta["end"] = ts

    def say(who, text, ts=None):
        if who == "USER" and not meta["first"]:
            meta["first"] = clip(text, 100)
        if who == "USER" and marked:
            meta["new_turns"] += 1
        stamp = f" [{local_time(ts)}]" if who == "USER" and ts else ""
        out.append(f"{who}{stamp}: {clip(text, 1500)}")

    for n, e in read_jsonl(path):
        meta["lines"] = n + 1
        if not marked and n >= since:
            out.append(NEW_MARKER)
            marked = True
        # Claude Code
        if e.get("type") in ("user", "assistant") and "message" in e:
            if e.get("isSidechain") or e.get("isMeta"):
                continue
            note_meta(e.get("sessionId"), e.get("cwd"), e.get("gitBranch"), e.get("timestamp"))
            content = e["message"].get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for b in content or []:
                t = b.get("type")
                if t == "text" and b.get("text", "").strip():
                    if b["text"].lstrip().startswith("<"):  # command wrappers, reminders
                        continue
                    say("USER" if e["type"] == "user" else "AGENT", b["text"], e.get("timestamp"))
                elif t == "tool_use":
                    tool_names[b.get("id")] = b.get("name")
                    out.append(f"  tool {b.get('name')}: {tool_summary(b.get('name'), b.get('input'))}")
                elif t == "tool_result":
                    text = block_text(b.get("content"))
                    meta["prs"].update(PR_URL.findall(text))
                    if tool_names.get(b.get("tool_use_id")) in ("AskUserQuestion", "ExitPlanMode"):
                        out.append(f"USER (answer): {clip(text, 800)}")
                    elif b.get("is_error"):
                        out.append(f"  error: {clip(text, 300)}")
        # Codex
        elif e.get("type") == "session_meta":
            meta["agent"] = "codex"
            p = e.get("payload", {})
            note_meta(p.get("id"), p.get("cwd"), (p.get("git") or {}).get("branch"), e.get("timestamp"))
        elif e.get("type") == "response_item":
            p = e.get("payload", {})
            note_meta(ts=e.get("timestamp"))
            if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
                text = block_text(p.get("content"))
                if text.strip() and not text.lstrip().startswith("<"):
                    say("USER" if p["role"] == "user" else "AGENT", text, e.get("timestamp"))
            elif p.get("type") == "function_call":
                out.append(f"  tool {p.get('name')}: {clip(p.get('arguments', ''), 150)}")
            elif p.get("type") == "function_call_output":
                meta["prs"].update(PR_URL.findall(str(p.get("output", ""))))
    return meta, out


def local_time(ts):
    """'2026-10-20T06:35:21.555Z' -> '2026-10-20 15:35' in local time, as {at:} expects."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts[:16].replace("T", " ")


def session_ref(meta):
    """The {session:...} attachment value for a transcript."""
    sid = meta["session"] if meta["agent"] == "claude" else f"codex:{meta['session']}"
    return f"{sid} {short_path(meta['cwd'])}" if meta["cwd"] else sid


def short_path(p):
    home = str(Path.home())
    return "~" + p[len(home):] if p and p.startswith(home) else p


def format_session(meta, lines):
    header = [
        f"session: {session_ref(meta)}   (attach as {{session:{session_ref(meta)}}})",
        f"agent: {meta['agent']}",
        f"cwd: {meta['cwd']}",
        f"branches: {', '.join(meta['branches']) or 'unknown'}",
        f"time: {meta['start']} .. {meta['end']}",
    ]
    if meta["prs"]:
        header.append(f"PRs seen: {', '.join(sorted(meta['prs']))}")
    return "\n".join(header) + "\n\n" + "\n".join(lines)


def cmd_condense(args):
    print(format_session(*condense(args.transcript)))


def all_transcripts():
    claude = Path("~/.claude/projects").expanduser().glob("*/*.jsonl")
    codex = Path("~/.codex/sessions").expanduser().glob("**/*.jsonl")
    return sorted([*claude, *codex], key=lambda p: p.stat().st_mtime, reverse=True)


def cmd_sessions(args):
    files = all_transcripts()
    if args.since:
        cutoff = datetime.fromisoformat(args.since).timestamp()
        files = [f for f in files if f.stat().st_mtime >= cutoff]
    if args.dir:
        files = [f for f in files if args.dir in str(f) or args.dir in (condense(f)[0]["cwd"] or "")]
    for needle in args.grep or []:
        needle = needle.lower().encode()
        files = [f for f in files if needle in f.read_bytes().lower()]
    shown = 0
    for f in files:
        if shown >= args.limit:
            break
        meta, _ = condense(f)
        if meta["first"].startswith(EXTRACT_PREAMBLE[:40]):  # our own `extract` runs
            continue
        shown += 1
        if args.paths:
            print(f)
            continue
        when = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        extras = [f"⎇ {b}" for b in meta["branches"]] + [u.rsplit("/", 3)[-3] + "#" + u.rsplit("/", 1)[-1] for u in sorted(meta["prs"])]
        print(f"{when}  {meta['agent']:6}  {short_path(meta['cwd'])}  {'  '.join(extras)}")
        print(f"    {meta['first']}\n    {f}")


TEXT_OUTPUT = """Do not edit any files. If a finding deserves a write-up, include it after the
proposals as "details/<name>.md:" followed by its contents. Output only proposals,
grouped like this:

under <existing-node-name>:
  - ? finding some-name: ...
on <existing-node-name>:
  > ? suggest #done: ...
top level:
  - ? goal some-name: ...

Proposals may nest under each other. Then one final line starting "Skipped:"
listing, briefly, what you deliberately left out."""

JSON_OUTPUT = """Output ONLY a JSON object, with no prose and no code fence:

{"ops": [
  {"op": "add", "parent": "<existing node name, or null for a new top-level goal>",
   "lines": ["- ? finding some-name: Title {at:...}", "  > unverified: ...", "  - ? decision child-name: ..."]},
  {"op": "note", "target": "<existing node name>", "text": "? next: ..."},
  {"op": "attach", "target": "<existing node name>", "value": "{session:<id> <dir>}"},
  {"op": "details", "name": "<node name>", "content": "<markdown write-up>"}
 ],
 "skipped": "<one line: what you deliberately left out>"}

"lines" is an outline fragment indented relative to its first line. "attach" only
takes {session:...}, {pr:...} or {branch:...}. Many sessions contain nothing worth
tracking; then return {"ops": [], "skipped": "..."}."""

INCREMENTAL = f"""The transcript contains the line "{NEW_MARKER}". Everything before it
was handled by an earlier update: use it only as context, and don't re-propose
things from it (the human may have deleted those proposals on purpose). Propose
only for what happened after the marker."""


def build_prompt(sessions, tree_text, as_json, incremental):
    blocks = "\n\n".join(f'<session n="{i + 1}">\n{format_session(m, lines)}\n</session>'
                         for i, (m, lines) in enumerate(sessions))
    return f"""{EXTRACT_PREAMBLE} Read the rules, the current tree and condensed transcripts of {len(sessions)} agent session(s), then propose updates.

The sessions are in chronological order. They may be in different directories or
repos, may use different agents, and are often one investigation spread across
several chats: a later session picks up a question, error or slowdown an earlier
one raised. Connect them using shared branches, PRs, file names and topics, and
put each node under the node that *caused* it, even when cause and effect are in
different sessions. Some sessions may be unrelated; give those their own goal or
leave them out. Attach each session's {{session:...}} value to the node(s) where
its main work happened.
{INCREMENTAL if incremental else ""}
<rules>
{RULES.read_text()}
</rules>

<current_tree>
{tree_text}
</current_tree>

<transcripts>
{blocks}
</transcripts>

Use the [timestamps] on USER lines (local time) for {{at:...}}.
{JSON_OUTPUT if as_json else TEXT_OUTPUT}
"""


def run_claude(prompt, capture):
    # DTREE_CHILD stops our own hook from firing inside this nested session
    env = {**os.environ, "DTREE_CHILD": "1"}
    r = subprocess.run(["claude", "-p"], input=prompt, text=True, env=env, check=False,
                       capture_output=capture)
    return r.stdout if capture else None


def cmd_extract(args):
    tree = tree_path(args.tree)
    sessions = sorted((condense(t, since=args.since) for t in args.transcripts),
                      key=lambda s: s[0]["start"] or "")
    prompt = build_prompt(sessions, tree.read_text(), args.apply, args.since > 0)
    if len(prompt) > 400_000:
        print(f"warning: prompt is {len(prompt) // 1000}K chars; consider fewer sessions", file=sys.stderr)
    if args.print_prompt:
        print(prompt)
        return
    if not args.apply:
        run_claude(prompt, capture=False)
        return

    reply = run_claude(prompt, capture=True) or ""
    try:
        data = json.loads(reply[reply.index("{"): reply.rindex("}") + 1])
    except ValueError:
        print(f"{datetime.now():%Y-%m-%d %H:%M} could not parse reply:\n{reply[:2000]}")
        return
    done = apply_ops(tree, data.get("ops", []))
    summary = "; ".join(done) or "nothing to add"
    print(f"{datetime.now():%Y-%m-%d %H:%M} {Path(args.transcripts[0]).stem[:8]}: {summary}"
          f" | skipped: {data.get('skipped', '')}")
    if args.notify and done:
        update_state(args.notify, notice=f"{summary} (review the ? lines in {short_path(str(tree))})")


# ---------- merging proposals into the tree ----------

def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def node_index(lines):
    idx = {}
    for i, line in enumerate(lines):
        m = NODE_LINE.match(line)
        if m:
            idx.setdefault(m.group(3), i)
    return idx


def block_end(lines, i):
    """Index just past node i's notes and children."""
    j = i + 1
    while j < len(lines) and lines[j].strip() and indent_of(lines[j]) > indent_of(lines[i]):
        j += 1
    return j


def notes_end(lines, i):
    """Index just past node i's own notes."""
    j = i + 1
    while j < len(lines) and lines[j].lstrip().startswith(">") and indent_of(lines[j]) > indent_of(lines[i]):
        j += 1
    return j


def mark_proposed(line):
    """Make sure a node line written by an agent starts with `- ?`."""
    m = re.match(r"^(\s*[-*]\s+)(?!\?\s)", line)
    return f"{m.group(1)}? {line[m.end():]}" if m else line


def apply_ops(tree, ops):
    """Merge proposal ops into the tree file. Only ever adds; returns a summary per change."""
    done = []
    with open(tree.parent / ".tree.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = tree.read_text().splitlines()
        for op in ops:
            idx, kind, target = node_index(lines), op.get("op"), op.get("target")
            if kind == "add":
                frag = [l.rstrip() for l in op.get("lines", []) if l.strip()]
                names = [m.group(3) for m in map(NODE_LINE.match, frag) if m]
                if not frag or not NODE_LINE.match(frag[0]) or any(n in idx for n in names):
                    continue
                base = min(indent_of(l) for l in frag)
                parent = op.get("parent")
                if parent in idx:
                    at, pad = block_end(lines, idx[parent]), indent_of(lines[idx[parent]]) + 2
                else:
                    while lines and not lines[-1].strip():
                        lines.pop()
                    lines.append("")
                    at, pad, parent = len(lines), 0, None
                lines[at:at] = [" " * pad + mark_proposed(l[base:]) for l in frag]
                done.append(f"added {', '.join(names)}" + (f" under {parent}" if parent else ""))
            elif kind == "note" and target in idx and op.get("text", "").strip():
                text = op["text"].strip()
                text = text if text.startswith("?") else f"? {text}"
                i = idx[target]
                lines.insert(notes_end(lines, i), " " * (indent_of(lines[i]) + 2) + "> " + text)
                done.append(f"note on {target}")
            elif kind == "attach" and target in idx:
                value = op.get("value", "").strip()
                if ATTACHABLE.match(value) and value not in lines[idx[target]]:
                    lines[idx[target]] += " " + value
                    done.append(f"attached {value[1:value.index(':')]} to {target}")
            elif kind == "details" and re.fullmatch(r"[a-z0-9][a-z0-9-]*", op.get("name", "")):
                path = tree.parent / "details" / f"{op['name']}.md"
                content = op.get("content", "").strip()
                if content and not path.exists():
                    path.parent.mkdir(exist_ok=True)
                    if not content.startswith("> ?"):
                        content = "> ? proposed by agent\n\n" + content
                    path.write_text(content + "\n")
                    done.append(f"write-up for {op['name']}")
        tmp = tree.with_suffix(".md.tmp")
        tmp.write_text("\n".join(lines) + "\n")
        tmp.replace(tree)
    return done


# ---------- Claude Code hook ----------

def load_state(session):
    try:
        return json.loads((STATE_DIR / f"{session}.json").read_text())
    except (OSError, ValueError):
        return None


def update_state(session, **changes):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {**(load_state(session) or {}), **changes}
    (STATE_DIR / f"{session}.json").write_text(json.dumps(state))
    return state


def cmd_hook(args):
    """Runs on Stop / PreCompact / SessionEnd. Every so often, kicks off a background
    `extract --apply` over what's new in this session. Never blocks the session."""
    if os.environ.get("DTREE_CHILD") or os.environ.get("DTREE_HOOK") == "off":
        return
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    session, transcript = data.get("session_id"), data.get("transcript_path")
    cwd = Path(data.get("cwd") or os.getcwd())
    if not session or not transcript or not Path(transcript).exists():
        return
    if any((d / ".dtree-ignore").exists() for d in (cwd, *cwd.parents)):
        return

    state = load_state(session) or update_state(session, line=0, at=time.time())
    out = {}
    if state.get("notice"):
        out["systemMessage"] = f"dtree: {state['notice']}"
        update_state(session, notice=None)

    meta, _ = condense(transcript, since=state["line"])
    if not meta["first"].startswith(EXTRACT_PREAMBLE[:40]):
        turns, minutes = meta["new_turns"], (time.time() - state["at"]) / 60
        if data.get("hook_event_name") in ("PreCompact", "SessionEnd"):
            due = turns >= 1
        else:
            due = turns >= HOOK_TURNS or (turns >= 2 and minutes >= HOOK_MINUTES)
        if due:
            log = open(DEFAULT_TREE.parent / "hook.log", "a")
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "extract", transcript, "--apply",
                 "--since", str(state["line"]), "--notify", session],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                env={**os.environ, "DTREE_CHILD": "1"})
            update_state(session, line=meta["lines"], at=time.time())
    if out:
        print(json.dumps(out))


def is_our_hook(h):
    cmd = h.get("command", "")
    return cmd.endswith(" hook") and ("dtree" in cmd or "dt.py" in cmd)


def cmd_hooks(args):
    """Add or remove our hook in ~/.claude/settings.json, keeping everything else."""
    path = Path("~/.claude/settings.json").expanduser()
    original = path.read_text() if path.exists() else "{}"
    settings = json.loads(original)
    exe = shutil.which("dtree")
    command = f'"{exe}" hook' if exe else f'"{sys.executable}" "{Path(__file__).resolve()}" hook'
    hooks = settings.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        groups = []
        for g in hooks.get(event, []):
            g = {**g, "hooks": [h for h in g.get("hooks", []) if not is_our_hook(h)]}
            if g["hooks"]:
                groups.append(g)
        if args.action == "install":
            groups.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks")
    if path.exists():
        path.with_name("settings.json.dtree-backup").write_text(original)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    verb = "installed" if args.action == "install" else "removed"
    print(f"{verb} dtree hook ({', '.join(HOOK_EVENTS)}) in {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="serve the viewer")
    p.add_argument("tree", nargs="?")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("sessions", help="list recent Claude Code and Codex transcripts")
    p.add_argument("--grep", action="append", help="only transcripts containing this text (repeatable, case-insensitive)")
    p.add_argument("--dir", help="only transcripts whose project directory contains this")
    p.add_argument("--since", help="only transcripts modified since this date (YYYY-MM-DD)")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--paths", action="store_true", help="print only paths, e.g. for $(...) into extract")
    p.set_defaults(func=cmd_sessions)

    p = sub.add_parser("condense", help="print a compact transcript")
    p.add_argument("transcript")
    p.set_defaults(func=cmd_condense)

    p = sub.add_parser("extract", help="propose tree updates from a transcript")
    p.add_argument("transcripts", nargs="+")
    p.add_argument("--tree")
    p.add_argument("--apply", action="store_true", help="merge proposals into the tree as ? lines instead of printing them")
    p.add_argument("--since", type=int, default=0, help="only propose for transcript lines after this one")
    p.add_argument("--notify", help=argparse.SUPPRESS)  # session to tell about the result (used by the hook)
    p.add_argument("--print-prompt", action="store_true", help="print the prompt instead of running claude")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("hook", help="Claude Code hook entry point (reads hook JSON on stdin)")
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("hooks", help="install or remove the Claude Code hook in ~/.claude/settings.json")
    p.add_argument("action", choices=["install", "uninstall"])
    p.set_defaults(func=cmd_hooks)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
