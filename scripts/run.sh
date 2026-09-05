#!/bin/bash
# Runs the app in the foreground - handy for seeing tracebacks.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m claude_usage_bar
