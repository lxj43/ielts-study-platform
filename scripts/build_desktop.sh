#!/bin/zsh
set -eu
cd "${0:A:h:h}"
launcher_bundle='词间悬浮学习.app'
mkdir -p "$launcher_bundle/Contents/MacOS"
swiftc desktop/StudyLauncher.swift -o "$launcher_bundle/Contents/MacOS/StudyLauncher" -framework Cocoa
cat > "$launcher_bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>StudyLauncher</string>
<key>CFBundleIdentifier</key><string>local.ielts.studylauncher.sample</string>
<key>CFBundleName</key><string>词间悬浮学习</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
<key>CFBundleVersion</key><string>1</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
</dict></plist>
PLIST
codesign --force --sign - "$launcher_bundle"
