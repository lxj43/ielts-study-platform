#!/bin/zsh
set -eu
cd "${0:A:h:h}"

launcher_bundle='词间悬浮学习.app'
stage=$(mktemp -d "$PWD/.desktop-build.XXXXXX")
trap 'python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$stage"' EXIT
bundle="$stage/$launcher_bundle"

mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
iconset="$stage/AppIcon.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    double=$((size * 2))
    sips -z "$size" "$size" desktop/AppIcon.png --out "$iconset/icon_${size}x${size}.png" >/dev/null
    sips -z "$double" "$double" desktop/AppIcon.png --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$bundle/Contents/Resources/AppIcon.icns"
MACOSX_DEPLOYMENT_TARGET=13.0 xcrun swiftc -parse-as-library -O desktop/StudyLauncher.swift \
    -o "$bundle/Contents/MacOS/StudyLauncher" -framework Cocoa -framework WebKit
cat > "$bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>StudyLauncher</string>
<key>CFBundleIdentifier</key><string>local.ielts.studylauncher.sample</string>
<key>CFBundleName</key><string>词间</string>
<key>CFBundleDisplayName</key><string>词间</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon.icns</string>
<key>CFBundleVersion</key><string>4</string>
<key>CFBundleShortVersionString</key><string>2.0</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key>
<dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
codesign --force --sign - "$bundle"
codesign --verify --strict "$bundle"

if [[ -e "$launcher_bundle" ]]; then
    mv "$launcher_bundle" "$stage/previous.app"
fi
if ! mv "$bundle" "$launcher_bundle"; then
    if [[ -e "$stage/previous.app" ]]; then
        mv "$stage/previous.app" "$launcher_bundle"
    fi
    exit 1
fi
