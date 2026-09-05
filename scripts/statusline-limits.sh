#!/bin/bash
# Mirrors Claude Code's quota windows to a file the menu bar app can read.
#
# Claude Code pipes a JSON blob into the statusline command on every turn; that blob
# carries `rate_limits.five_hour` / `.seven_day` for subscribers. This script saves
# those windows and then hands the untouched JSON to your real statusline command,
# so it works as a wrapper around whatever you already use.
#
# Install (in ~/.claude/settings.json):
#
#   "statusLine": {
#     "type": "command",
#     "command": "/path/to/claude-usage-bar/scripts/statusline-limits.sh 'your existing command'"
#   }
#
# With no argument it prints a small "5h / 7d" line of its own.
set -uo pipefail

OUT_DIR="$HOME/.claude/usage-bar"
OUT_FILE="$OUT_DIR/limits.json"
INPUT=$(cat)

mkdir -p "$OUT_DIR"
printf '%s' "$INPUT" \
    | /usr/bin/python3 -c '
import json, sys
try:
    payload = json.load(sys.stdin)
    limits = payload.get("rate_limits") or {}
except Exception:
    limits = {}
print(json.dumps({"rate_limits": limits}))
' > "$OUT_FILE.tmp" 2>/dev/null && mv "$OUT_FILE.tmp" "$OUT_FILE" || rm -f "$OUT_FILE.tmp"

if [ "$#" -gt 0 ] && [ -n "$1" ]; then
    printf '%s' "$INPUT" | eval "$1"
    exit $?
fi

printf '%s' "$INPUT" | /usr/bin/python3 -c '
import json, sys
try:
    limits = (json.load(sys.stdin).get("rate_limits") or {})
except Exception:
    limits = {}
parts = []
for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
    window = limits.get(key)
    if window and window.get("used_percentage") is not None:
        parts.append("%s %.0f%%" % (label, window["used_percentage"]))
print(" · ".join(parts))
'
