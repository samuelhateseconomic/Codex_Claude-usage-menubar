#!/bin/zsh
# Builds ClaudeUsageBar.app (Apple silicon + Intel) next to this script and installs it to /Applications.
#   ./build.sh          build and install
#   ./build.sh --zip    build and also make ClaudeUsageBar-<version>.zip for a GitHub release
set -euo pipefail
cd "$(dirname "$0")"

VERSION=1.0.0
APP=ClaudeUsageBar.app
SOURCES=(ClaudeUsageBar.swift SessionReports.swift Login.swift WeeklyReports.swift AccountsWindow.swift)
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

BUILD=$(mktemp -d)
for arch in arm64 x86_64; do
  swiftc -O -parse-as-library -target "$arch-apple-macos13.0" -o "$BUILD/$arch" "${SOURCES[@]}"
done
lipo -create -output "$APP/Contents/MacOS/ClaudeUsageBar" "$BUILD/arm64" "$BUILD/x86_64"
rm -rf "$BUILD"
cp assets/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ClaudeUsageBar</string>
  <key>CFBundleDisplayName</key><string>Claude Usage Bar</string>
  <key>CFBundleIdentifier</key><string>local.claude-usage-bar</string>
  <key>CFBundleExecutable</key><string>ClaudeUsageBar</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF

codesign --force --sign - "$APP" >/dev/null 2>&1 || true

if [[ "${1:-}" == "--zip" ]]; then
  rm -f "ClaudeUsageBar-$VERSION.zip"
  ditto -c -k --keepParent "$APP" "ClaudeUsageBar-$VERSION.zip"
  echo "Packaged $PWD/ClaudeUsageBar-$VERSION.zip"
fi

# Install to /Applications so "Launch at Login" keeps pointing at a stable place.
pkill -x ClaudeUsageBar 2>/dev/null || true
rm -rf /Applications/ClaudeUsageBar.app
ditto "$APP" /Applications/ClaudeUsageBar.app
echo "Built $PWD/$APP ($VERSION) and installed /Applications/ClaudeUsageBar.app"
