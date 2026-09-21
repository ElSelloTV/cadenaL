#!/bin/sh
# cadenaL — instalador para la PC procesadora dedicada (Debian 13 trixie).
#
# Instala PipeWire + plugins LV2 (Calf, LSP), copia la configuracion de
# config/ a su lugar, deja la maquina bootenado headless (sin escritorio,
# governor de CPU en "performance") y habilita todo para que arranque
# solo tras un reinicio/corte de luz, sin que nadie tenga que loguearse.
#
# Correr como root (sudo ./install.sh). Al final indica los pasos que
# dependen de TU hardware (nombres reales de la interfaz MVSilicon).
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Este script necesita permisos de root (correlo con sudo)." >&2
    exit 1
fi

DIR="$(cd "$(dirname "$0")" && pwd)"

# El usuario que corre PipeWire --user. Por defecto el que invoco sudo;
# se puede forzar con: sudo AUDIO_USER=radio ./install.sh
AUDIO_USER="${AUDIO_USER:-${SUDO_USER:-$(logname 2>/dev/null || echo root)}}"

echo "=== cadenaL: instalacion (usuario de audio: $AUDIO_USER) ==="

# --- 1. Paquetes del sistema -------------------------------------------------
echo
echo "--- Paso 1/5: paquetes del sistema (apt) ---"
apt update
apt install -y \
    pipewire pipewire-audio-client-libraries pipewire-alsa \
    wireplumber \
    lv2-utils calf-plugins lsp-plugins-lv2 \
    rtkit \
    linux-cpupower \
    carla

# --- 2. Sin entorno grafico / arranque headless -----------------------------
echo
echo "--- Paso 2/5: arranque headless (multi-user.target) ---"
systemctl set-default multi-user.target

# --- 3. Copiar configuracion -------------------------------------------------
echo
echo "--- Paso 3/5: copiando configuracion ---"
mkdir -p /etc/pipewire/pipewire.conf.d
cp "$DIR/config/pipewire/98-quantum-fm.conf" /etc/pipewire/pipewire.conf.d/
cp "$DIR/config/pipewire/99-filter-chain-fm.conf" /etc/pipewire/pipewire.conf.d/

cp "$DIR/config/limits.d/audio.conf" /etc/security/limits.d/audio.conf
sed -i "s/@radio/@${AUDIO_USER}/g" /etc/security/limits.d/audio.conf

cp "$DIR/config/systemd/cpu-performance.service" /etc/systemd/system/

# --- 4. Habilitar servicios --------------------------------------------------
echo
echo "--- Paso 4/5: habilitando servicios ---"
systemctl daemon-reload
systemctl enable --now cpu-performance.service

loginctl enable-linger "$AUDIO_USER"
runuser -l "$AUDIO_USER" -c 'systemctl --user daemon-reload'
runuser -l "$AUDIO_USER" -c 'systemctl --user enable --now pipewire.socket pipewire wireplumber'

# --- 5. Apagar servicios innecesarios ----------------------------------------
echo
echo "--- Paso 5/5: apagando servicios que no hacen falta en una maquina dedicada ---"
for svc in bluetooth cups cups-browsed avahi-daemon ModemManager ; do
    systemctl disable --now "$svc" >/dev/null 2>&1 || true
done

cat <<EOF

=== Instalacion base completa ===

Falta lo que depende de TU hardware especifico (la interfaz MVSilicon):

  1) Identificar el nombre real de entrada/salida de la MVSilicon:
       wpctl status

  2) Editar /etc/pipewire/pipewire.conf.d/99-filter-chain-fm.conf y
     completar los dos placeholders (capture.props / playback.props)
     con esos nombres.

  3) Fijar la MVSilicon como dispositivo por defecto si no queda sola:
       wpctl set-default <ID_de_wpctl_status>

  4) Reiniciar PipeWire para aplicar la cadena:
       systemctl --user restart pipewire wireplumber

  5) Verificar que no hay xruns con audio real sonando:
       pw-top

  6) Afinar compresion/EQ/ancho estereo con Carla (ya instalado), y
     volcar los valores definitivos al propio archivo de config (ver
     seccion "Afinar niveles" del README) para que sobrevivan al
     proximo reinicio.

EOF
