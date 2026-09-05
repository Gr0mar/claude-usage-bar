#!/bin/bash
# Creates the venv, installs PyObjC, runs the tests and builds the app.
set -euo pipefail
cd "$(dirname "$0")/.."

# Same interpreter the installed app runs, so the tests exercise the shipped version.
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python -m unittest discover -s tests
./scripts/install.sh

echo
echo "done. start it with:  open -a QuotaBar"
