#!/usr/bin/env python3
"""Decision tree helper.

  dtree serve [TREE]              serve the viewer, live-reloading TREE
  dtree sessions [--grep TEXT]    find transcripts across all projects (Claude Code + Codex)
  dtree condense TRANSCRIPT       print a compact version of a transcript
  dtree extract TRANSCRIPT...     ask `claude -p` to propose tree updates from one or
                                  more related sessions, e.g.
                                  dtree extract $(dtree sessions --grep invoice --paths)

TREE defaults to $DTREE, then ~/.decision-tree/tree.md.
"""
import argparse
import http.server
import json
import os
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "skill" / "tree" / "rules.md"
DEFAULT_TREE = Path(os.environ.get("DTREE", "~/.decision-tree/tree.md")).expanduser()
EXTRACT_PREAMBLE = "You are helping maintain a human's decision tree."
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")


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
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
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


def condense(path):
    """Parse a Claude Code (or, best-effort, Codex) transcript into metadata + compact lines."""
    meta = {"path": str(path), "agent": "claude", "session": None, "cwd": None,
            "branches": [], "prs": set(), "start": None, "end": None, "first": ""}
    out = []
    tool_names = {}  # tool_use id -> name, to recognize answers to the agent's questions

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
        stamp = f" [{local_time(ts)}]" if who == "USER" and ts else ""
        out.append(f"{who}{stamp}: {clip(text, 1500)}")

    for e in read_jsonl(path):
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


def cmd_extract(args):
    tree = tree_path(args.tree)
    sessions = sorted((condense(t) for t in args.transcripts), key=lambda s: s[0]["start"] or "")
    blocks = "\n\n".join(f'<session n="{i + 1}">\n{format_session(m, lines)}\n</session>'
                         for i, (m, lines) in enumerate(sessions))
    prompt = f"""{EXTRACT_PREAMBLE} Read the rules, the current tree and condensed transcripts of {len(sessions)} agent session(s), then propose updates.

The sessions are in chronological order. They may be in different directories or
repos, may use different agents, and are often one investigation spread across
several chats: a later session picks up a question, error or slowdown an earlier
one raised. Connect them using shared branches, PRs, file names and topics, and
put each node under the node that *caused* it, even when cause and effect are in
different sessions. Some sessions may be unrelated; give those their own goal or
leave them out. Attach each session's {{session:...}} value to the node(s) where
its main work happened.

<rules>
{RULES.read_text()}
</rules>

<current_tree>
{tree.read_text()}
</current_tree>

<transcripts>
{blocks}
</transcripts>

Use the [timestamps] on USER lines (local time) for {{at:...}}. Do not edit any files.
If a finding deserves a write-up, include it after the proposals as
"details/<name>.md:" followed by its contents. Output only proposals, grouped like this:

under <existing-node-name>:
  - ? finding some-name: ...
on <existing-node-name>:
  > ? suggest #done: ...
top level:
  - ? goal some-name: ...

Proposals may nest under each other. Then one final line starting "Skipped:"
listing, briefly, what you deliberately left out.
"""
    if len(prompt) > 400_000:
        print(f"warning: prompt is {len(prompt) // 1000}K chars; consider fewer sessions", file=sys.stderr)
    if args.print_prompt:
        print(prompt)
        return
    subprocess.run(["claude", "-p"], input=prompt, text=True, check=False)


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
    p.add_argument("--print-prompt", action="store_true", help="print the prompt instead of running claude")
    p.set_defaults(func=cmd_extract)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
