#!/bin/bash
# Builds a standalone ClaudeUsageBar.app that needs no Python on the user's machine,
# and zips it for a GitHub release.
#
#   ./scripts/build-release.sh [version]
#
# The result is dist/ClaudeUsageBar.app and dist/ClaudeUsageBar-<version>.zip.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
VERSION="${1:-$(git describe --tags --abbrev=0 2>/dev/null || echo 1.0.0)}"
VERSION="${VERSION#v}"
PYTHON="$REPO/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "no venv - run ./scripts/setup.sh first" >&2
    exit 1
fi
"$PYTHON" -m pip install --quiet pyinstaller

BUNDLE_ID="$("$PYTHON" -c "from claude_usage_bar.identity import BUNDLE_ID; print(BUNDLE_ID)")"

rm -rf build dist
"$PYTHON" -m PyInstaller \
    --name ClaudeUsageBar \
    --windowed \
    --noconfirm \
    --clean \
    --osx-bundle-identifier "$BUNDLE_ID" \
    --icon docs/AppIcon.icns \
    --add-data "claude_usage_bar/assets/claude-mark.svg:claude_usage_bar/assets" \
    --hidden-import PyObjCTools.AppHelper \
    --paths . \
    --log-level WARN \
    scripts/pyinstaller-entry.py >/dev/null

APP="dist/ClaudeUsageBar.app"
PLIST="$APP/Contents/Info.plist"

# Menu bar only, and one instance at a time.
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMultipleInstancesProhibited bool true" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :LSMultipleInstancesProhibited true" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$PLIST" 2>/dev/null || true

# Ad-hoc signature. Without an Apple Developer certificate the first launch still needs
# right-click -> Open; the README says so.
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || \
    echo "  (codesign unavailable - Gatekeeper will complain louder)"

ZIP="dist/ClaudeUsageBar-$VERSION.zip"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo "built $APP"
echo "      $ZIP  ($(du -h "$ZIP" | cut -f1))"
echo "      sha256 $(shasum -a 256 "$ZIP" | cut -d' ' -f1)"
