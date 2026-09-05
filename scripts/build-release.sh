#!/bin/bash
# Builds a self-contained ClaudeUsageBar.app and zips it for a GitHub release.
#
#   ./scripts/build-release.sh [version]
#
# The bundle carries its own copy of the package and of PyObjC, and runs them on the
# system's /usr/bin/python3 - which every macOS install has. That is deliberately not a
# frozen binary: a PyInstaller bundle launched from Finder never showed its status item,
# because the bootloader is not the process that ends up owning the menu bar.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
VERSION="${1:-$(git describe --tags --abbrev=0 2>/dev/null || echo 1.0.0)}"
VERSION="${VERSION#v}"

BUNDLE_ID="$(/usr/bin/python3 -c "import sys; sys.path.insert(0, '$REPO'); from claude_usage_bar.identity import BUNDLE_ID; print(BUNDLE_ID)")"
APP="dist/ClaudeUsageBar.app"

rm -rf dist
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/lib"

echo "› vendoring dependencies"
/usr/bin/python3 -m pip install --quiet --upgrade --target "$APP/Contents/Resources/lib" \
    -r requirements.txt
find "$APP/Contents/Resources/lib" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

cp -R claude_usage_bar "$APP/Contents/Resources/claude_usage_bar"
find "$APP/Contents/Resources/claude_usage_bar" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
cp docs/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

# The interpreter runs as a child, not via exec: replacing the process LaunchServices
# started leaves the app without a usable status item.
cat > "$APP/Contents/MacOS/ClaudeUsageBar" <<'LAUNCHER'
#!/bin/bash
RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PYTHONPATH="$RESOURCES:$RESOURCES/lib"
/usr/bin/python3 -m claude_usage_bar &
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
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key><string>ClaudeUsageBar</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <!-- Menu bar only: no Dock icon, no app switcher entry. -->
    <key>LSUIElement</key><true/>
    <!-- Two copies would fight over one cache file. -->
    <key>LSMultipleInstancesProhibited</key><true/>
</dict>
</plist>
PLIST

if ! codesign --force --deep --sign - "$APP" >/dev/null 2>&1; then
    echo "  (codesign unavailable - Gatekeeper will complain louder)"
fi

ZIP="dist/ClaudeUsageBar-$VERSION.zip"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo "built $APP"
echo "      $ZIP  ($(du -h "$ZIP" | cut -f1))"
echo "      sha256 $(shasum -a 256 "$ZIP" | cut -d' ' -f1)"
