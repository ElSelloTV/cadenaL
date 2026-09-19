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

## Flujo completo y arquitectura (para revisar con el software de radio)

Esta seccion documenta todo lo que hace cadenaL de punta a punta, para
que el equipo/desarrollador del software de radio pueda revisar si
necesita ajustar algo de su lado (spoiler: en el caso normal, no).

### Diagrama de flujo completo

```
 Software de radio (y cualquier otra app: VLC, etc.)
   │
   │  cada reproduccion es un "sink-input" independiente en
   │  PulseAudio/PipeWire, sin importar a que salida apunte
   │  originalmente ni cuantas instancias se creen/destruyan
   │
   ├── Stream de MASTER (u otro no protegido)
   │        │
   │        ▼  cadenal.service lo detecta e intercepta
   │        ▼  (evento "sink-input nuevo/cambiado")
   │   cadenal_mix          <- sink virtual (module-null-sink)
   │        │
   │        ▼  opcional: cadenal_fx procesa el monitor de cadenal_mix
   │   AutoGanancia -> Compresor -> Brillo (EQ) -> Limitador
   │        │
   │        ▼
   │   cadenal_fx           <- sink virtual con el audio ya procesado
   │        │
   │        ▼  --target apunta a la salida fisica real
   │   Salida fisica (ej. consola USB que sale al aire)
   │
   └── Stream de PREVIEW/CUE (si esta en un sink protegido)
            │
            ▼  cadenal.service lo ve pero lo IGNORA a proposito
            ▼  (esta en la lista --exclude-sink)
       Salida fisica separada (ej. auriculares del panel), sin tocar
```

### Como intercepta el audio (mecanismo tecnico)

- cadenaL no es un plugin ni una libreria que el software de radio
  tenga que cargar: es un **daemon en espacio de usuario** que habla
  con el servidor de audio (PulseAudio o PipeWire vía su capa de
  compatibilidad `pipewire-pulse`) usando el mismo protocolo que usa
  cualquier mezclador de volumen (`pavucontrol`, etc.).
- Se suscribe a los eventos `sink-input` (aparicion/cambio de streams
  de reproduccion) y `sink` (aparicion/desaparicion de salidas) del
  servidor. No hace polling ni lee/escribe audio el mismo: solo mueve
  la referencia del stream de un sink a otro (`sink_input_move`), una
  operacion instantanea del propio servidor de audio.
- **Esto pasa un nivel por debajo de cualquier configuracion interna
  del software de radio.** No importa a que "dispositivo de salida"
  este configurado el master dentro del software: cadenaL lo
  intercepta igual antes de que el audio llegue fisicamente a esa
  salida, y lo redirige.

### Que necesita el software de radio / sus motores de audio

En el caso normal, **nada.** Para que funcione sin tocar el software
de radio, alcanza con que sus motores de audio reproduzcan a traves
del servidor de audio del sistema (PulseAudio o PipeWire), que es el
camino por defecto en Linux para casi cualquier libreria de audio
(GStreamer, libVLC, SDL, PortAudio, Wine con su backend de audio
estandar, etc.). Puntos a confirmar con el equipo del software:

1. **Que no reproduzca por ALSA directo/exclusivo.** Si el motor de
   audio abre el hardware directamente (por ejemplo un dispositivo
   `hw:0,0` o `plughw:0,0` en vez del `pulse`/`default` que provee el
   servidor), ese audio nunca pasa por PulseAudio/PipeWire y cadenaL
   no puede verlo ni interceptarlo. Esto es lo unico que realmente
   rompe el enfoque. Si el software corre bajo Wine, revisar que el
   backend de audio de Wine este en `pulse` (o `alsa` apuntando al
   dispositivo virtual `pulse`/`default`, nunca a la placa directo).
2. **No hace falta que declare ningun nombre especial de aplicacion**
   (`application.name` en terminologia PulseAudio). cadenaL enruta por
   defecto sin mirar el nombre del proceso; ese campo solo se usa de
   forma opcional para excluir aplicaciones puntuales
   (`cadenal setup --exclude <nombre>`).
3. **No hay limite de instancias simultaneas.** Cada reproduccion que
   dispare el software (una voz, una cortina, una pista musical) es un
   stream independiente para el servidor de audio; cadenaL los procesa
   a todos igual, se creen y liberen con la frecuencia que sea.
4. **El orden de arranque no importa.** Si el software de radio ya
   esta sonando cuando arranca `cadenal.service` (o al reves), no hay
   problema: al iniciar, el daemon primero "barre" todo lo que ya este
   sonando y lo re-enruta, y de ahi en mas queda escuchando eventos
   nuevos indefinidamente.
5. **Distincion master/previo se resuelve del lado de cadenaL, no del
   software.** Si el software manda el previo/cue a una salida fisica
   fija (por ejemplo siempre al mismo dispositivo de auriculares del
   panel), alcanza con decirle a cadenaL que proteja esa salida
   (`cadenal setup --exclude-sink <nombre_del_sink>`); no hace falta
   ningun cambio de configuracion en el software de radio para lograr
   esa separacion.
6. **Formato/sample rate:** si el motor de audio reproduce en una
   frecuencia o formato distinto al del sink virtual, el servidor de
   audio resamplea automaticamente (es su comportamiento estandar para
   cualquier sink); no requiere ninguna configuracion adicional.

### Limitaciones conocidas (a tener en cuenta, no bloqueantes para uso en radio)

- Hay una ventana minima entre que un stream nuevo aparece y cadenaL
  lo mueve (un evento + una llamada al servidor de audio, tipicamente
  milisegundos). En teoria el primerisimo instante de audio podria
  sonar en la salida original antes del cambio. Para este uso (audio
  continuo de radio) es inaudible e irrelevante; el diseño prioriza
  estabilidad por sobre latencia cero, tal como fue pedido.
- Si el sink virtual `cadenal_mix` se elimina manualmente o el
  servidor de audio se reinicia de forma abrupta, cadenaL lo recrea
  solo y re-enruta todo lo que este sonando en ese momento (ver
  "Notas de diseno" mas abajo).
- `cadenal fx` (el procesador AutoGanancia/Compresor/Brillo/Limitador)
  depende de que PipeWire este compilado con soporte LV2 (lo estandar
  en Debian/Q4OS) y de tener instalados los plugins de Calf y LSP;
  `cadenal fx check` valida esto antes de instalar la cadena.

## Requisitos

- Debian / Q4OS con PipeWire (`pipewire-pulse`) o PulseAudio.
- Python 3.9+
- Libreria `libpulse0` (normalmente ya instalada junto con el servidor
  de audio).
- `python3-tk` si vas a usar la ventana de configuracion grafica.
- Para el icono de bandeja (junto al reloj): `python3-gi` y
  `gir1.2-ayatanaappindicator3-0.1` (o `gir1.2-appindicator3-0.1` en
  distros mas viejas) para que se integre nativo con el panel. Si tu
  escritorio no los tiene, el icono cae solo a un modo compatible por
  X11 (necesita `python3-xlib`, que se instala solo via pip).

## Instalacion completa (recomendado)

Un solo script instala todo lo que se puede automatizar: paquetes del
sistema (incluyendo los del procesador `fx`: PipeWire, Calf, LSP,
lv2-utils), la app (`cadenal`, `cadenal-gui`, `cadenal-tray`), el
servicio systemd, y los iconos de menu/bandeja.

```bash
chmod +x install.sh
./install.sh
```

Te va a pedir la contrasena de `sudo` para los paquetes de `apt`. Al
final del todo te muestra los pasos que quedan pendientes porque
dependen de tu hardware especifico (nombres de tus salidas de audio):
`cadenal scan`, `cadenal setup`, `cadenal fx setup --target ...`, etc.
Es seguro volver a correr `./install.sh` mas de una vez.

### Instalacion manual (paso a paso)

Si preferis hacerlo a mano o algo del script no te sirve para tu caso:

```bash
sudo apt install python3-pip python3-tk pipewire pipewire-pulse \
    python3-gi gir1.2-ayatanaappindicator3-0.1 \
    lv2-utils calf-plugins lsp-plugins-lv2   # si no los tenes ya
pip install --user ".[tray]"
```

(Si no te interesa el icono de bandeja, alcanza con `pip install --user .`;
si no vas a usar el procesador `fx`, podes omitir `lv2-utils calf-plugins
lsp-plugins-lv2`)

Esto instala en `~/.local/bin` (asegurate de que ese directorio este
en tu `PATH`):

- `cadenal` — CLI (`scan`, `setup`, `status`, `start`, `fx`).
- `cadenal-gui` — ventana de configuracion.
- `cadenal-tray` — icono de bandeja junto al reloj.

Instalar el servicio persistente:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/cadenal.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable cadenal.service
```

Instalar el icono de menu y de bandeja:

```bash
./desktop/install-desktop-entry.sh
```

Esto copia el `.desktop` a `~/.local/share/applications` (para que
"cadenaL" aparezca en el menu de tu escritorio y abra la ventana de
configuracion), el icono a
`~/.local/share/icons/hicolor/scalable/apps`, y un autostart a
`~/.config/autostart` para que el icono de bandeja se abra solo en
cada inicio de sesion. Ademas lo arranca de una vez, sin esperar al
proximo login.

El icono de bandeja muestra en gris si el servicio esta detenido y en
celeste si esta activo, y su menu contextual permite abrir la
configuracion, ver el estado de enrutamiento, iniciar/detener el
servicio, o salir (esto ultimo solo cierra el icono, el daemon sigue
corriendo aparte).

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

   Si ademas tenes una salida fisica separada para preview/cue (por
   ejemplo unos parlantes o auriculares conectados al panel frontal,
   usados para escuchar el "previo" del software antes de salir al
   aire) que **no** queres que se mezcle con el master, protegela con
   `--exclude-sink` usando el nombre que te dio `cadenal scan`:

   ```bash
   cadenal setup \
     --exclude-sink alsa_output.pci-0000_00_1f.3.analog-stereo
   ```

   Esto es necesario porque el master y el previo suelen salir del
   mismo programa (mismo `application.name`): la unica forma de
   distinguirlos es por a que salida fisica apunta cada uno. Un stream
   que ya este sonando en un sink protegido se deja intacto; todo lo
   demas (tipicamente el master, que apunta a tu consola USB) se
   enruta igual que siempre hacia `cadenal_mix`.

3. Arrancar el servicio (si usaste `install.sh` ya quedo habilitado,
   solo falta iniciarlo la primera vez):

   ```bash
   systemctl --user start cadenal.service
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

## Procesador de aire ultra-liviano (`cadenal fx`)

Alternativa a Viper4Linux para equipos modestos (pensado para PCs de 2
nucleos corriendo una FM): una cadena de procesamiento tipo
Breakaway/procesador de aire, pero hospedando plugins LV2 nativos en C
dentro del propio proceso de PipeWire (sin proceso aparte, sin
convolucion), via su modulo `filter-chain`.

Cadena de senal (el limitador siempre va al final, como ultima
barrera contra picos):

```
cadenal_mix.monitor -> AutoGanancia -> Compresor -> Brillo (EQ) -> Limitador -> cadenal_fx
```

- **AutoGanancia**: LSP Autogain
- **Compresor**: Calf Compressor
- **Brillo / cristalizador**: Calf Equalizer 5 Band (realce de agudos,
  el equivalente al "HF EQ"/"Tilt" de un FM Mode de Breakaway)
- **Limitador**: Calf Limiter

### Instalacion

```bash
sudo apt install pipewire lv2-utils calf-plugins lsp-plugins-lv2
cadenal fx check     # verifica que este todo instalado
cadenal fx setup     # instala la cadena (opcional: --target <sink_fisico>)
systemctl --user restart pipewire pipewire-pulse wireplumber
cadenal fx status
```

Ejemplo con una consola USB como salida al aire (el caso tipico de una
FM): el master de tu software se enruta a `cadenal_mix`, se procesa, y
`--target` manda el resultado de vuelta a la misma interfaz USB:

```bash
cadenal fx setup --target alsa_output.usb-XXXX.analog-stereo
```

Si no pasaste `--target`, el resultado queda expuesto como el sink
`cadenal_fx`: elegilo a mano como salida final en `pavucontrol` o
`qpwgraph` (por ejemplo, apuntandolo hacia tu tarjeta de sonido o hacia
el software que alimenta el transmisor).

### Afinar los parametros

La cadena se instala con los valores por defecto de cada plugin (no
son necesariamente los de tu configuracion de Breakaway). Para ajustar
compresion, umbral, cantidad de brillo, etc. a algo similar a esa
captura, la forma mas simple es abrir el nodo "CadenaL FX" con un host
de plugins con interfaz grafica, por ejemplo:

```bash
sudo apt install carla
```

y desde ahi mover los controles de cada plugin (Autogain, Compressor,
Equalizer 5 Band, Limiter) escuchando el resultado en vivo.

### Quitar la cadena

```bash
cadenal fx remove
systemctl --user restart pipewire pipewire-pulse wireplumber
```

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
- `cadenal fx` genera la configuracion de PipeWire pero no fue probado
  todavia contra una instalacion real (se desarrollo sin acceso a un
  entorno Linux). `cadenal fx check` sirve para detectar temprano si
  falta algun paquete antes de instalar la cadena.
