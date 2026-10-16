#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$PROJECT_DIR/.package-root"

"$PROJECT_DIR/build.sh"
rm -rf "$PACKAGE_ROOT"
mkdir -p "$PACKAGE_ROOT/DEBIAN" "$PACKAGE_ROOT/usr/bin" "$PACKAGE_ROOT/usr/share/applications" "$PACKAGE_ROOT/usr/share/icons/hicolor/512x512/apps"
cp "$PROJECT_DIR/packaging/debian/control" "$PACKAGE_ROOT/DEBIAN/control"
cp "$PROJECT_DIR/dist/foliomind" "$PACKAGE_ROOT/usr/bin/foliomind"
cp "$PROJECT_DIR/packaging/debian/foliomind.desktop" "$PACKAGE_ROOT/usr/share/applications/foliomind.desktop"
cp "$PROJECT_DIR/assets/foliomind-icon.png" "$PACKAGE_ROOT/usr/share/icons/hicolor/512x512/apps/foliomind.png"
chmod 755 "$PACKAGE_ROOT/usr/bin/foliomind"
dpkg-deb --build "$PACKAGE_ROOT" "$PROJECT_DIR/dist/foliomind_0.0.1_amd64.deb"
echo "Installer complete: $PROJECT_DIR/dist/foliomind_0.0.1_amd64.deb"
