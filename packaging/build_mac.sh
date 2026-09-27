#!/bin/bash
# Build the two Alert Mesh desktop apps for macOS.
#
#   packaging/build_mac.sh            (from python-prototype/)
#
# Makes dist/Alert Mesh.app (the phone app) and dist/Alert Mesh Warnings.app (the
# warning app), and each zipped for sharing: dist/Alert-Mesh-mac.zip and
# dist/Alert-Mesh-Warnings-mac.zip.
# The first run makes a separate build environment, packaging/.venv-mac, with the
# Python named by PYTHON (default: python3; needs 3.10 or newer, tested with python.org
# 3.14). Later runs reuse it. Downloads the build tools from PyPI on the first run.
#
# This is free and unencumbered software released into the public domain.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
VENV=packaging/.venv-mac
SWIFT_APP=../alert-mesh
ICONS="$SWIFT_APP/AlertMesh/Assets.xcassets/AppIcon.appiconset"

if [ ! -d "$SWIFT_APP" ]; then
    echo "The Swift app folder ($SWIFT_APP) is missing: the build copies the town list and the icon from it." >&2
    exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
    if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        echo "Needs Python 3.10 or newer; $PYTHON is $("$PYTHON" --version 2>&1). Set PYTHON=/path/to/python3." >&2
        exit 1
    fi
    echo "Making the build environment ($VENV) with $("$PYTHON" --version 2>&1)"
    "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r packaging/requirements-build.txt

echo "Making the icon from the Swift app's icon images"
rm -rf build/icon
mkdir -p build/icon/AlertMesh.iconset
for size in 16x16 16x16@2x 32x32 32x32@2x 128x128 128x128@2x 256x256 256x256@2x 512x512 512x512@2x; do
    cp "$ICONS/icon_$size.png" build/icon/AlertMesh.iconset/
done
iconutil -c icns build/icon/AlertMesh.iconset -o build/icon/AlertMesh.icns

echo "Building the apps (a few minutes)"
"$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN \
    --distpath dist --workpath build/pyinstaller packaging/alert_mesh.spec

echo "Checking each finished app has every part it needs"
"dist/Alert Mesh.app/Contents/MacOS/Alert Mesh" --check
"dist/Alert Mesh Warnings.app/Contents/MacOS/Alert Mesh Warnings" --check

rm -f dist/Alert-Mesh-mac.zip dist/Alert-Mesh-Warnings-mac.zip
ditto -c -k --keepParent "dist/Alert Mesh.app" dist/Alert-Mesh-mac.zip
ditto -c -k --keepParent "dist/Alert Mesh Warnings.app" dist/Alert-Mesh-Warnings-mac.zip

echo
echo "Done:"
du -sh "dist/Alert Mesh.app" "dist/Alert Mesh Warnings.app" dist/Alert-Mesh-mac.zip dist/Alert-Mesh-Warnings-mac.zip
echo "Open them with:  open \"dist/Alert Mesh.app\"   and   open \"dist/Alert Mesh Warnings.app\""
