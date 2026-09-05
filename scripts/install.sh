#!/bin/bash
# Installs the runtime outside the home folders macOS protects, then builds
# /Applications/ClaudeUsageBar.app around it.
#
# An app launched from Finder has no access to ~/Desktop or ~/Documents, so a bundle
# that pointed at a checkout living there would die on startup. The runtime therefore
# gets its own copy under Application Support; this checkout stays the source.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"

RUNTIME="$HOME/Library/Application Support/ClaudeUsageBar"
APP="/Applications/ClaudeUsageBar.app"
PYTHON="$RUNTIME/venv/bin/python"

echo "› runtime → $RUNTIME"
mkdir -p "$RUNTIME"
if [ ! -x "$PYTHON" ]; then
    /usr/bin/python3 -m venv "$RUNTIME/venv"
    "$PYTHON" -m pip install --quiet --upgrade pip
fi
# Unconditional: an interrupted first run can leave an interpreter with no dependencies,
# and a guarded install would then ship an app that crashes on import.
"$PYTHON" -m pip install --quiet -r "$REPO/requirements.txt"

rm -rf "$RUNTIME/claude_usage_bar"
cp -R "$REPO/claude_usage_bar" "$RUNTIME/claude_usage_bar"
find "$RUNTIME/claude_usage_bar" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Match the module invocation, not the loose string "claude_usage_bar": -f matches whole
# command lines, so the loose pattern would also kill an editor or grep in this checkout.
# The venv interpreter is a symlink and reports the framework path in ps, so matching on
# the venv path would find nothing.
RUNNING_PATTERN="\-m claude_usage_bar"
if pgrep -f "$RUNNING_PATTERN" >/dev/null; then
    echo "› quitting the running copy"
    pkill -f "$RUNNING_PATTERN" || true
    sleep 1
fi

echo "› bundle → $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# The interpreter runs as a child, not via exec: replacing the launcher process
# that LaunchServices started leaves the app without a usable status item.
cat > "$APP/Contents/MacOS/ClaudeUsageBar" <<LAUNCHER
#!/bin/bash
export PYTHONPATH="$RUNTIME"
"$PYTHON" -m claude_usage_bar &
wait
LAUNCHER
chmod +x "$APP/Contents/MacOS/ClaudeUsageBar"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Claude Usage Bar</string>
    <key>CFBundleDisplayName</key><string>Claude Usage Bar</string>
    <key>CFBundleIdentifier</key><string>deals.clutch.ClaudeUsageBar</string>
    <key>CFBundleExecutable</key><string>ClaudeUsageBar</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <!-- Menu bar only: no Dock icon, no app switcher entry. -->
    <key>LSUIElement</key><true/>
    <!-- Two copies would fight over one cache file. -->
    <key>LSMultipleInstancesProhibited</key><true/>
</dict>
</plist>
PLIST

if ! codesign --force --sign - "$APP" >/dev/null 2>&1; then
    echo "  (codesign unavailable - the app still runs, but macOS may re-ask for keychain access)"
fi

echo "› installed. start it with:  open -a ClaudeUsageBar"
