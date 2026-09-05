#!/bin/bash
# Builds a self-contained QuotaBar.app and zips it for a GitHub release.
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
VERSION="${1:-}"
VERSION="${VERSION#v}"

read_identity() {
    REPO="$REPO" /usr/bin/python3 -c "import os, sys; sys.path.insert(0, os.environ['REPO']); import quotabar.identity as i; print(getattr(i, '$1'))"
}
BUNDLE_ID="$(read_identity BUNDLE_ID)"
[ -n "$VERSION" ] || VERSION="$(read_identity VERSION)"
APP="dist/QuotaBar.app"

rm -rf dist
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/lib"

echo "› vendoring dependencies"
# Universal wheels for the system interpreter, so the bundle runs on Intel too and does
# not silently depend on whatever CPython this machine happens to have.
/usr/bin/python3 -m pip install --quiet --upgrade --target "$APP/Contents/Resources/lib" \
    --only-binary=:all: --platform macosx_11_0_universal2 \
    --python-version "$(/usr/bin/python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" \
    -r requirements.txt
find "$APP/Contents/Resources/lib" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

cp -R quotabar "$APP/Contents/Resources/quotabar"
find "$APP/Contents/Resources/quotabar" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
cp docs/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
cp scripts/statusline-limits.sh "$APP/Contents/Resources/statusline-limits.sh"
chmod +x "$APP/Contents/Resources/statusline-limits.sh"

# The interpreter runs as a child, not via exec: replacing the process LaunchServices
# started leaves the app without a usable status item.
cat > "$APP/Contents/MacOS/QuotaBar" <<'LAUNCHER'
#!/bin/bash
RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PYTHONPATH="$RESOURCES:$RESOURCES/lib"

# /usr/bin/python3 is a stub until the Command Line Tools are installed; without this
# the app would exit silently and never appear in the menu bar.
if ! /usr/bin/python3 -c "pass" >/dev/null 2>&1; then
    /usr/bin/osascript -e 'display alert "QuotaBar needs the Xcode Command Line Tools" message "Run xcode-select --install in Terminal, then open QuotaBar again."' >/dev/null 2>&1
    exit 1
fi

/usr/bin/python3 -m quotabar &
wait
LAUNCHER
chmod +x "$APP/Contents/MacOS/QuotaBar"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>QuotaBar</string>
    <key>CFBundleDisplayName</key><string>QuotaBar</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key><string>QuotaBar</string>
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

ZIP="dist/QuotaBar-$VERSION.zip"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo "built $APP"
echo "      $ZIP  ($(du -h "$ZIP" | cut -f1))"
echo "      sha256 $(shasum -a 256 "$ZIP" | cut -d' ' -f1)"
