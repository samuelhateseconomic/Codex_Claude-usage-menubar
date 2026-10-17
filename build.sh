#!/bin/zsh
# Builds ClaudeUsageBar.app next to this script.
set -euo pipefail
cd "$(dirname "$0")"

APP=ClaudeUsageBar.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

swiftc -O -parse-as-library -o "$APP/Contents/MacOS/ClaudeUsageBar" ClaudeUsageBar.swift SessionReports.swift Login.swift WeeklyReports.swift

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ClaudeUsageBar</string>
  <key>CFBundleIdentifier</key><string>local.claude-usage-bar</string>
  <key>CFBundleExecutable</key><string>ClaudeUsageBar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF

codesign --force --sign - "$APP" >/dev/null 2>&1 || true
# Install to /Applications so "Launch at Login" keeps pointing at a stable place.
pkill -x ClaudeUsageBar 2>/dev/null || true
rm -rf /Applications/ClaudeUsageBar.app
ditto "$APP" /Applications/ClaudeUsageBar.app
echo "Built $PWD/$APP and installed /Applications/ClaudeUsageBar.app"
