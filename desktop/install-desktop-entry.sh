#!/bin/sh
# Instala el icono y el lanzador de menu para el usuario actual.
# Requiere que 'cadenal-gui' ya este instalado (pip install --user .)
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS_DIR="$HOME/.local/share/applications"

mkdir -p "$ICON_DIR" "$APPS_DIR"
cp "$DIR/cadenal.svg" "$ICON_DIR/cadenal.svg"
cp "$DIR/cadenal.desktop" "$APPS_DIR/cadenal.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "Listo. Deberia aparecer 'cadenaL' en el menu de aplicaciones."
