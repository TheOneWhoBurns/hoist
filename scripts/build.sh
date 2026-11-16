#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
HOIST_ARCH="$(uname -m)"
HOIST_APP="$PWD/dist/Hoist.app"
HOIST_PYTHON="${HOIST_PYTHON:-$PWD/.venv/bin/python}"
if [ ! -x "$HOIST_PYTHON" ]; then
    uv venv --python 3.13 .venv
fi
uv pip sync --python "$HOIST_PYTHON" requirements-build.txt
mkdir -p build dist
"$HOIST_PYTHON" -m PyInstaller --noconfirm --clean --onedir --name hoist-service --distpath build/service-dist --workpath build/service-work --specpath build --collect-all pychromecast --collect-all zeroconf service/hoist_service.py > build/service-build.log 2>&1
mkdir -p "$HOIST_APP/Contents/MacOS" "$HOIST_APP/Contents/Resources"
rm -rf "$HOIST_APP/Contents/Resources/service"
cp -R build/service-dist/hoist-service "$HOIST_APP/Contents/Resources/service"
xcrun swiftc -O -target "$HOIST_ARCH-apple-macosx13.0" Sources/Hoist.swift -o "$HOIST_APP/Contents/MacOS/Hoist"
"$HOIST_PYTHON" scripts/package_metadata.py "$HOIST_APP" "$HOIST_ARCH"
xcrun swift scripts/icon.swift "$PWD/build/Hoist.iconset"
iconutil -c icns build/Hoist.iconset -o "$HOIST_APP/Contents/Resources/Hoist.icns"
codesign --force --deep --sign - "$HOIST_APP"
codesign --verify --deep --strict "$HOIST_APP"
ditto -c -k --sequesterRsrc --keepParent "$HOIST_APP" "dist/Hoist-0.1.0-$HOIST_ARCH.zip"
shasum -a 256 "dist/Hoist-0.1.0-$HOIST_ARCH.zip" > "dist/Hoist-0.1.0-$HOIST_ARCH.zip.sha256"
printf 'Built %s\n' "$HOIST_APP"
