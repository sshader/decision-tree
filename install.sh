#!/bin/sh
# Symlink the CLI and the /tree skill so a `git pull` here updates both, and add
# the Claude Code hook that proposes nodes automatically (skip with --no-hooks).
set -e
here="$(cd "$(dirname "$0")" && pwd)"
bin="${BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$bin" "$HOME/.claude/skills"
chmod +x "$here/dt.py"
ln -sfn "$here/dt.py" "$bin/dtree"
ln -sfn "$here/skill/tree" "$HOME/.claude/skills/tree"
echo "installed: $bin/dtree -> $here/dt.py"
echo "installed: ~/.claude/skills/tree -> $here/skill/tree"
if [ "$1" != "--no-hooks" ]; then
  PATH="$bin:$PATH" dtree hooks install
fi
case ":$PATH:" in *":$bin:"*) ;; *) echo "note: $bin is not on your PATH";; esac
