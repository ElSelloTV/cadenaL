# cadenaL

Utilidad de audio para Debian/Q4OS que "casa" todas las salidas de audio
de la maquina (sinks fisicos, sinks virtuales, instancias de VLC u otro
motor que se abren y cierran continuamente, streams de un software de
radio, etc.) y las encapsula en una **unica salida de audio virtual**
con el nombre que elijas. Pensada para alimentar despues esa salida a
[Viper4Linux](https://github.com/Ferion12345/viper4linux) u otro
procesador, sin tener que perseguir cada instancia nueva a mano.

## Como funciona

En vez de intentar enrutar "por salida fisica", cadenaL intercepta a
nivel de **stream de reproduccion** (`sink-input` en terminologia
PulseAudio/PipeWire): cada vez que aparece un stream nuevo -una
instancia de VLC, una voz que dispara el software de radio, cualquier
motor- lo mueve automaticamente al sink virtual de destino si todavia
no esta ahi. Es un daemon liviano, basado 100% en eventos del propio
servidor de audio (sin polling), por lo que funciona igual si las
instancias se crean y se liberan constantemente.

Funciona tanto si la maquina corre PulseAudio nativo como PipeWire con
`pipewire-pulse` (el default actual en Debian/Q4OS), porque en ambos
casos se habla el protocolo de PulseAudio.

## Requisitos

- Debian / Q4OS con PipeWire (`pipewire-pulse`) o PulseAudio.
- Python 3.9+
- Libreria `libpulse0` (normalmente ya instalada junto con el servidor
  de audio).
- `python3-tk` si vas a usar la ventana de configuracion grafica.

## Instalacion

```bash
sudo apt install python3-pip python3-tk pipewire-pulse   # si no los tenes ya
pip install --user .
```

Esto instala dos comandos en `~/.local/bin` (asegurate de que ese
directorio este en tu `PATH`):

- `cadenal` — CLI (`scan`, `setup`, `status`, `start`).
- `cadenal-gui` — ventana de configuracion.

### Icono en el menu de aplicaciones

```bash
./desktop/install-desktop-entry.sh
```

Esto copia el `.desktop` y el icono a las carpetas estandar de tu
usuario (`~/.local/share/applications` y
`~/.local/share/icons/hicolor/scalable/apps`). Deberia aparecer
"cadenaL" en el menu de tu escritorio (Trinity/Plasma/lo que uses en
Q4OS) para abrir la ventana de configuracion sin usar la terminal.

## Uso

Los pasos 1 y 2 se pueden hacer desde la ventana grafica (`cadenal-gui`
o el icono del menu) en vez de la terminal: escanea las salidas
fisicas, define el nombre del sink virtual, permite excluir
aplicaciones y tiene botones para habilitar/detener el servicio y ver
que streams estan enrutados en cada momento.

Por linea de comandos es el mismo flujo:

1. Escanear las salidas fisicas actuales (informativo, queda guardado
   en la configuracion):

   ```bash
   cadenal scan
   ```

2. Configurar el nombre de la salida virtual que vas a usar como
   destino unico:

   ```bash
   cadenal setup --name cadenal_mix --description "CadenaL - Mezcla de audio"
   ```

   Opcionalmente se puede excluir alguna aplicacion por
   `application.name` para que no se enrute (por ejemplo sonidos del
   sistema):

   ```bash
   cadenal setup --exclude "GNOME Shell"
   ```

3. Instalar y habilitar el servicio para que quede corriendo siempre
   (incluso si PulseAudio/PipeWire se reinicia):

   ```bash
   mkdir -p ~/.config/systemd/user
   cp systemd/cadenal.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now cadenal.service
   ```

4. Verificar el estado:

   ```bash
   cadenal status
   ```

## Integracion con Viper4Linux

Una vez que el daemon esta corriendo, todo el audio de la maquina
termina llegando al sink virtual (por defecto `cadenal_mix`). En
Viper4Linux (o `pavucontrol`/`qpwgraph`) elegi como entrada el
**monitor** de ese sink, que aparece como `cadenal_mix.monitor`. De ahi
en adelante el procesamiento y la salida final hacia tus parlantes la
maneja Viper4Linux como siempre.

## Notas de diseno

- El objetivo es estabilidad, no latencia: si un stream tarda un
  instante en moverse al sink virtual apenas se crea, no es un
  problema para este uso.
- Si el sink virtual desaparece (por ejemplo, alguien lo descarga a
  mano o el servidor de audio se reinicia de forma abrupta), el daemon
  lo vuelve a crear solo y re-enruta todo lo que este sonando.
- Si se corta la conexion con el servidor de audio, el daemon reintenta
  la conexion con backoff creciente; `systemd` ademas lo reinicia si el
  proceso llegara a morir.
