#!/bin/sh
# Instala el icono, el lanzador de menu y el autostart del icono de
# bandeja para el usuario actual.
# Requiere que 'cadenal-gui' y 'cadenal-tray' ya esten instalados
# (pip install --user ".[tray]")
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

mkdir -p "$ICON_DIR" "$APPS_DIR" "$AUTOSTART_DIR"
cp "$DIR/cadenal.svg" "$ICON_DIR/cadenal.svg"
cp "$DIR/cadenal.desktop" "$APPS_DIR/cadenal.desktop"
cp "$DIR/cadenal-tray.desktop" "$AUTOSTART_DIR/cadenal-tray.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "Listo. 'cadenaL' deberia aparecer en el menu de aplicaciones,"
echo "y el icono de bandeja se va a iniciar solo en tu proxima sesion."

if command -v cadenal-tray >/dev/null 2>&1; then
  echo "Iniciando el icono de bandeja ahora mismo..."
  nohup cadenal-tray >/dev/null 2>&1 &
  disown || true
else
  echo "Aviso: no se encontro 'cadenal-tray' en el PATH todavia."
  echo "Instala las dependencias del icono con: pip install --user \".[tray]\""
fi
