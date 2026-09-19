#!/bin/sh
# Instalacion completa de cadenaL en Debian/Q4OS: paquetes del sistema
# (incluyendo los del procesador fx), la app en si, el servicio
# systemd, y los iconos de menu/bandeja.
#
# Lo unico que queda afuera son los pasos que dependen de TU hardware
# especifico (nombres de tus salidas de audio), que se muestran al
# final para que los corras vos.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== cadenaL: instalacion completa ==="

# --- 1. Paquetes del sistema -------------------------------------------------
echo
echo "--- Paso 1/5: paquetes del sistema (apt) ---"

BASE_PACKAGES="python3-pip python3-tk pipewire pipewire-pulse python3-gi"
FX_PACKAGES="lv2-utils calf-plugins lsp-plugins-lv2"

APPINDICATOR_PKG=""
if apt-cache show gir1.2-ayatanaappindicator3-0.1 >/dev/null 2>&1; then
  APPINDICATOR_PKG="gir1.2-ayatanaappindicator3-0.1"
elif apt-cache show gir1.2-appindicator3-0.1 >/dev/null 2>&1; then
  APPINDICATOR_PKG="gir1.2-appindicator3-0.1"
else
  echo "Aviso: no se encontro un paquete de appindicator3 disponible en tus repos."
  echo "El icono de bandeja va a caer al modo compatible por X11 (usa python3-xlib,"
  echo "que se instala solo via pip mas abajo)."
fi

sudo apt update
sudo apt install -y $BASE_PACKAGES $FX_PACKAGES $APPINDICATOR_PKG

# --- 2. Instalar cadenaL (Python) -------------------------------------------
echo
echo "--- Paso 2/5: instalando cadenaL (pip --user) ---"
pip install --user "${DIR}[tray]"

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

# --- 3. Servicio systemd --user ---------------------------------------------
echo
echo "--- Paso 3/5: servicio systemd --user ---"
mkdir -p "$HOME/.config/systemd/user"
cp "$DIR/systemd/cadenal.service" "$HOME/.config/systemd/user/cadenal.service"
systemctl --user daemon-reload
systemctl --user enable cadenal.service

# --- 4. Icono de menu y de bandeja -------------------------------------------
echo
echo "--- Paso 4/5: icono de menu y de bandeja ---"
"$DIR/desktop/install-desktop-entry.sh"

# --- 5. Verificar plugins del procesador (fx) --------------------------------
echo
echo "--- Paso 5/5: verificando plugins del procesador (fx) ---"
if command -v cadenal >/dev/null 2>&1; then
  cadenal fx check || true
else
  echo "Aviso: 'cadenal' no se encontro en el PATH de esta sesion de shell."
  echo "Abri una terminal nueva, o corre: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

cat <<'EOF'

=== Instalacion base completa ===

Lo que sigue depende de TU hardware especifico (que salidas de audio
tenes conectadas), asi que no se puede automatizar a ciegas:

  1) Escanear tus salidas fisicas:
       cadenal scan

  2) Configurar el sink virtual. Si tenes una salida separada para
     preview/cue (ej. auriculares del panel) que no debe mezclarse
     con el master, protegela con --exclude-sink:
       cadenal setup --exclude-sink <nombre_salida_previo>

  3) Arrancar el enrutador:
       systemctl --user start cadenal.service

  4) Instalar la cadena de procesamiento, apuntando a tu salida real
     (ej. la consola USB que sale al aire):
       cadenal fx setup --target <nombre_salida_usb>
       systemctl --user restart pipewire pipewire-pulse wireplumber

  5) Verificar todo:
       cadenal status
       cadenal fx status

EOF
