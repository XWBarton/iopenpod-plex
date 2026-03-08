#!/bin/bash
# Build iOpenPod.app
# Usage: ./packaging/build.sh
# Output: dist/iOpenPod.app

set -e
cd "$(dirname "$0")/.."

echo "==> Cleaning previous build..."
rm -rf build/ dist/

echo "==> Running PyInstaller..."
uv run pyinstaller packaging/iOpenPod.spec

echo ""
echo "==> Done: dist/iOpenPod.app"
echo "    To package as a DMG: hdiutil create -volname iOpenPod -srcfolder dist/iOpenPod.app -ov -format UDZO dist/iOpenPod.dmg"
