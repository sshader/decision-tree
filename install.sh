#!/bin/sh
# Symlink the CLI and the /tree skill so a `git pull` here updates both.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
bin="${BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$bin" "$HOME/.claude/skills"
chmod +x "$here/dt.py"
ln -sfn "$here/dt.py" "$bin/dtree"
ln -sfn "$here/skill/tree" "$HOME/.claude/skills/tree"
echo "installed: $bin/dtree -> $here/dt.py"
echo "installed: ~/.claude/skills/tree -> $here/skill/tree"
case ":$PATH:" in *":$bin:"*) ;; *) echo "note: $bin is not on your PATH";; esac
