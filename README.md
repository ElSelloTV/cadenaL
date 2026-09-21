# cadenaL — Procesador de aire dedicado para FM

PC dedicada **exclusivamente** a procesar la señal de audio antes del
transmisor. No corre software de automatización ni ningún programa que no
sea el sistema operativo y el motor de audio: recibe la mezcla de la PC de
radio + consola, la procesa (compresión, ecualización, realce estéreo,
limitador) y entrega el resultado al codificador estéreo.

## Cadena de señal

```
PC de radio (automatización) ──┐
Micrófonos ─────────────────────┼──> Mix USB Silicon (consola/mezcladora)
                                 │
                                 ▼  salida balanceada XLR
                    Entrada Line-In de esta PC (Realtek ALC662, analógica)
                                 │
                                 ▼
                 ┌───────────────────────────────┐
                 │   cadenaL — cadena LV2 nativa   │
                 │  Autogain → Compresor → EQ →    │
                 │  Estéreo (widening) → Limitador │
                 └───────────────────────────────┘
                                 │
                                 ▼
                    Salida de esta PC (interfaz USB MVSilicon)
                                 │
                                 ▼
                       Codificador estéreo → Transmisor
```

**Entrada y salida NO usan el mismo dispositivo de audio:** la entrada
es la Line-In analógica de la placa (Realtek ALC662) porque es el único
puerto de línea "de verdad" que tiene esta PC; la MVSilicon USB se
reserva para la salida hacia el codificador, donde su DAC rinde mejor
que el de la placa. Ver "Nivel de entrada" más abajo — es el punto más
importante para no arruinar el audio antes de que llegue a cualquier
plugin.

Esta PC es un eslabón puramente de procesamiento: **una entrada, una
salida**, sin mezcla ni ruteo dinámico de múltiples streams (eso ya lo
resuelve la consola física aguas arriba). Por eso no necesita nada del
viejo enfoque de "daemon que casa sink-inputs" — solo un grafo de audio
fijo, liviano y que sobreviva reinicios sin intervención.

## Hardware disponible

| Componente | Detalle |
|---|---|
| Placa | ASRock AM1B-M (socket AM1) |
| CPU | AMD Sempron 2650 (APU Radeon R3) — 2 núcleos, 1 hilo c/u, 800–1450 MHz |
| RAM | ~3.3 GB usables |
| Audio integrado | Realtek ALC662 (analógico) — **entrada** (Line-In) |
| Audio USB | MV-SILICON MVSilicon — **salida** hacia el codificador |
| SO actual | Debian 13 "trixie", PipeWire 1.4.2 |

Es una CPU floja (Jaguar de bajo clock, sin SMT). El diseño de abajo está
pensado explícitamente para no pedirle más de lo que puede dar de forma
sostenida, 24/7, sin nadie mirando.

## Nivel de entrada: XLR balanceado → Line-In (el punto crítico)

La salida XLR de la consola es nivel de línea **profesional** (+4 dBu,
~1,23 V RMS nominal, con picos más altos). La Line-In de la Realtek
ALC662 espera nivel de línea de **consumo** (-10 dBV, ~0,32 V RMS). La
diferencia es de **~12 dB**: conectado directo, la entrada va a clipear
antes de llegar a cualquier plugin, y eso no lo arregla ningún software
de acá — hay que resolverlo en el tramo analógico. Opciones, de más a
menos recomendable:

1. **Trim en la consola**: si la salida XLR tiene un atenuador/trim,
   bajarlo hasta que el pico, visto con `alsamixer` (barra de captura)
   o `arecord -f S16_LE -d 5 test.wav && sox test.wav -n stat` ronde
   -10/-6 dBFS. Cero hardware extra.
2. **Cable/adaptador XLR→TRS con pad resistivo** (atenuador pasivo,
   ~10-15 dB): si la consola no tiene trim, es la solución más barata
   y no depende de tocar nada del lado de la consola.
3. **Interfaz USB chica con entrada de línea balanceada real y trim**
   (Behringer UCA202/222, Focusrite Scarlett Solo, etc.): la opción más
   robusta si esto va a quedar operativo de forma permanente — resuelve
   el nivel de raíz y de paso reemplaza el ADC mediocre de la ALC662.
   No agrega carga de CPU relevante.

Sin uno de estos tres pasos, cualquier ajuste de compresor/EQ que hagas
después va a estar compensando un clipping que ya ocurrió en el
conversor A/D, y eso es irreversible.

## Decisiones y por qué

### 1. Distro: quedarse con Debian 13, pero *sin escritorio*

No hace falta migrar a Alpine/Void/DietPi para ganar liviandad. La
diferencia real de consumo entre esas distros y un Debian **sin entorno
gráfico, sin display manager, arrancando en `multi-user.target`** es
marginal comparada con lo que pesa PipeWire + los plugins LV2 en sí. Y
Debian trixie ya:

- Tiene PipeWire 1.4.2 empaquetado y probado (no hay que compilar nada).
- Tiene los plugins Calf y LSP en repos oficiales, con builds `glibc`
  bien probados (en Alpine, que usa `musl`, hay más chances de tropezar
  con algún plugin LV2 compilado raro o con `pulseaudio`-isms rotos).
- Es la que ya está instalada: cero riesgo de reinstalar en hardware que
  ya funciona, cero tiempo perdido.

Lo único que cambia es el **modo de arranque**: no instalar/dejar
ningún entorno gráfico, ni `gdm`/`lightdm`, y bootear directo a consola
de texto (target `multi-user.target`, nunca `graphical.target`). Ver
sección "Arranque headless" más abajo.

Si en algún momento se reinstala desde cero, alcanza con el instalador
Debian eligiendo únicamente la tarea **"standard system utilities"**
(sin "Debian desktop environment", sin "print server", etc.).

### 2. Motor de audio: PipeWire `filter-chain`, no JACK, no ALSA directo, no EasyEffects

| Opción | Veredicto |
|---|---|
| **PipeWire `filter-chain`** | ✅ Elegido |
| JACK | ❌ Otra capa de servidor de audio encima, sin beneficio real acá: no hay múltiples clientes profesionales que necesiten grafo dinámico, y en un CPU de 2 núcleos sin SMT la sincronización de xruns de JACK es más delicada de afinar que la de PipeWire nativo. |
| ALSA directo (`hw:`) | ❌ Serviría para *no* procesar, pero justamente lo que necesitás es insertar una cadena de plugins entre entrada y salida. Sin un servidor de audio no hay dónde alojar esa cadena sin escribir tu propio programa. |
| EasyEffects | ❌ Es una app GTK: necesita sesión gráfica/D-Bus de usuario con interfaz, hecha para ajustar en vivo con ventana. En una PC headless 24/7 es peso muerto (dependencias de GTK4/libadwaita) para algo que, una vez afinado, no necesita más interfaz. |
| Viper4Linux | ❌ Pensado para audio de escritorio/multimedia (efectos tipo "surround virtual", convolución), no para una cadena de aire de FM. Más pesado y menos predecible que alojar los plugins LV2 directo en PipeWire. |

**`filter-chain`** es un módulo nativo de PipeWire que carga los plugins
LV2 (Calf, LSP) **dentro del propio proceso `pipewire`**, sin proceso
aparte, sin IPC extra, sin ventana. Es lo mismo que ya veías con
`cadenal fx` en el proyecto anterior, pero acá es *todo* lo que corre en
la máquina — no hay daemon de ruteo porque no hace falta (una sola
entrada, una sola salida, fijas).

Config: `pipewire.conf.d/`, sample rate fijo (no flotante) en 48000 Hz, y
un `quantum` ajustado a lo que este CPU banca sin xruns (ver más abajo).

### 3. Cadena de procesamiento

Con plugins Calf y LSP (los mismos que ya conocés), en este orden — el
limitador **siempre al final**, como última barrera contra picos:

```
Entrada USB → LSP Gain/Autogain → Calf Compressor → Calf Equalizer 5 Band
            → Calf Stereo Tools (realce estéreo) → Calf Limiter → Salida USB
```

- **Gain de entrada / Autogain (LSP)**: normaliza el nivel que entrega la
  consola antes de comprimir, para no depender de que el nivel de la
  Mix USB Silicon quede siempre perfecto.
- **Compresor (Calf Compressor)**: control de dinámica, el corazón del
  procesador de aire.
- **Ecualizador (Calf Equalizer 5 Band)**: realce de agudos/brillo,
  corrección tonal.
- **Stereo Tools (Calf)**: ensanchador estéreo (stereo width), cuidando
  no romper compatibilidad mono (importante para FM: nunca superar un
  ensanchamiento que genere problemas de fase al sumar L+R).
- **Limitador (Calf Limiter)**: brickwall final con look-ahead, para que
  nada llegue al codificador por encima de 0 dBFS.

Todos son plugins C nativos, livianos, sin convolución — la elección
correcta para este CPU (los mismos que ya veías funcionar bien en un
equipo de 2 núcleos con el `cadenal fx` anterior).

Ver `config/pipewire/filter-chain-fm.conf` — está armado como plantilla,
hay que completar los nombres reales de los puertos ALSA de la MVSilicon
(salen de `pw-cli ls Node` o `aplay -l` / `arecord -l`, ver instrucciones
adentro del archivo).

### 4. Arranque headless, sin intervención

Objetivo: que ante un corte de luz o un reinicio, la máquina vuelva a
procesar audio sola, sin que nadie tenga que loguearse.

0. **BIOS — arrancar solo al volver la luz (esto es lo primero, y es
   ajeno al sistema operativo)**: entrar al BIOS de la ASRock AM1B-M
   (Supr/Del al bootear) → **Advanced → Chipset Configuration** → buscar
   **"Restore on AC/Power Loss"** y ponerlo en **"Power On"** (no
   "Power Off" ni "Last State": con "Power On" arranca siempre que
   vuelve la corriente, sin importar en qué estado quedó antes del
   corte). Guardar y salir (F10). Sin este paso, todo lo demás de esta
   sección no sirve: la máquina se queda apagada hasta que alguien
   presione el botón físico.
1. **Sin entorno gráfico**: `systemctl set-default multi-user.target`
   (bootea a consola de texto, no a login gráfico).
2. **PipeWire como servicio de usuario con "linger"**: PipeWire corre
   como servicio `--user` (no del sistema), que es como Debian lo
   empaqueta y lo que garantiza que `wireplumber` administre bien los
   dispositivos. Para que arranque **sin que el usuario inicie sesión**,
   se habilita *linger*:

   ```bash
   sudo loginctl enable-linger radio
   systemctl --user enable pipewire pipewire.socket wireplumber.service
   ```

   (con `radio` reemplazado por el usuario real de la máquina). Con
   linger, `systemd` arranca los servicios de usuario en el boot aunque
   nadie haga login por consola o SSH.

3. **Autologin en la tty NO hace falta** — con linger alcanza. Se puede
   dejar la tty1 sin autologin para que solo el que tenga la contraseña
   pueda tocar la máquina físicamente.
4. **Governor de CPU en `performance`**, no `ondemand`/`powersave`: en
   un CPU de 800–1450 MHz, el escalado de frecuencia agrega latencia
   exactamente en el peor momento (justo cuando entra carga de audio) y
   es una causa común de xruns. Ver `config/systemd/cpu-performance.service`.
5. **Prioridad de tiempo real** para el proceso de PipeWire, vía
   `rtkit` (paquete `rtkit`, ya estándar en Debian con PipeWire) más los
   límites de `config/limits.d/audio.conf`.
6. **Apagar todo lo que no hace falta**: Bluetooth, CUPS, Avahi,
   NetworkManager-wait-online (si la red es fija), interfaz gráfica de
   PipeWire para escritorio (`pipewire-media-session` si estuviera —
   trixie ya usa `wireplumber` por defecto). Ver `install.sh`.

## Instalación

### Paso previo (una sola vez, con monitor y teclado)

El instalador de Debian necesita pantalla la primera vez. Instalar
**Debian 13 "trixie"** con el netinst, y en la pantalla de `tasksel`
tildar **solo "SSH server"** — desmarcar "Debian desktop environment" y
todo lo demás. Terminada la instalación, con red y SSH funcionando, ya
no hace falta monitor ni teclado nunca más: todo lo que sigue se hace
por SSH.

Si la máquina ya tiene Debian 13 instalado con escritorio (como el
enunciado del hardware sugiere), no hace falta reinstalar: alcanza con
`sudo systemctl set-default multi-user.target` y desinstalar/deshabilitar
el display manager (`sudo systemctl disable --now gdm3` o el que tenga).

### Instalador

```bash
sudo ./install.sh
```

Instala los paquetes necesarios (sin entorno gráfico, todo por línea de
comandos: `alsa-utils`, `pipewire`, `wireplumber`, plugins Calf/LSP),
copia las configuraciones de `config/` a su lugar, habilita los
servicios, fija el governor de CPU y deja logueado qué falta ajustar a
mano (nombres reales de dispositivo, que dependen de tu hardware).
Todo esto — igual que el resto de esta guía — se corre por SSH, sin
necesidad de ventana.

Después de correrlo:

1. Identificar los nombres exactos de entrada (Realtek Line-In) y
   salida (MVSilicon):

   ```bash
   wpctl status
   ```

2. Confirmar con `alsamixer` que el puerto activo de captura de la
   Realtek es **"Line"** y no "Mic" (el mic-in tiene una etapa de
   preamplificación pensada para milivoltios, no para nivel de línea —
   si el capture source queda en "Mic" vas a clipear seguro, aunque ya
   hayas resuelto el nivel del lado de la consola):

   ```bash
   alsamixer
   # F4 = vista de captura. Con las flechas elegir el dispositivo
   # Realtek (F6 para elegir tarjeta si hay mas de una). Confirmar que
   # la fuente de captura marcada con "*"/roja sea "Line", no "Mic".
   # Ajustar el nivel de captura (barra) sin que pegue en el tope.
   ```

   Guardar el estado del mixer para que sobreviva al reinicio (Debian
   ya lo restaura solo en el boot vía `alsa-state.service`, pero hay
   que grabarlo una vez después de ajustar):

   ```bash
   sudo alsactl store
   ```

3. Editar `/etc/pipewire/pipewire.conf.d/99-filter-chain-fm.conf` (ya
   copiado por `install.sh`) y completar `capture.props` (Realtek
   Line-In) / `playback.props` (MVSilicon) con los `node.target` reales
   del paso 1.

4. Fijar ambos dispositivos como default si no quedan solos:

   ```bash
   wpctl status                 # anotar los IDs
   wpctl set-default <ID>
   ```

5. Reiniciar PipeWire para aplicar la cadena:

   ```bash
   systemctl --user restart pipewire wireplumber
   ```

6. Verificar que no hay xruns bajo carga real (dejarlo un rato con
   audio sonando):

   ```bash
   pw-top
   ```

   Cualquier columna de xruns (`ERR`) subiendo de forma sostenida es
   señal de que el `quantum` (buffer) elegido es muy chico para este
   CPU — subirlo en `pipewire.conf.d` (ver comentarios en el archivo).

## Afinar niveles (compresión, EQ, ancho estéreo) — sin entorno gráfico

Todo se ajusta editando números en `99-filter-chain-fm.conf` por SSH
(`nano` alcanza) y reiniciando el servicio; no hace falta ninguna
ventana. El único paso es saber el nombre exacto (`symbol`) de cada
control, que puede variar levemente entre versiones de los plugins:

```bash
lv2info http://calf.sourceforge.net/plugins/Compressor
lv2info http://calf.sourceforge.net/plugins/Equalizer5Band
lv2info http://calf.sourceforge.net/plugins/StereoTools
lv2info http://calf.sourceforge.net/plugins/Limiter
lv2info http://lsp-plug.in/plugins/lv2/autogain_stereo
```

Cada uno lista sus "ports" de control con `symbol`, rango y valor por
defecto. Con esos nombres se completa el bloque `control = { ... }` de
cada nodo en `filter-chain-fm.conf`, por ejemplo:

```
control = {
    threshold = -18.0
    ratio     = 4.0
    attack    = 5.0
    release   = 80.0
    makeup    = 3.0
}
```

Después de cada cambio: `systemctl --user restart pipewire wireplumber`
y escuchar el resultado (en la salida real hacia el codificador, o con
un monitor conectado momentáneamente a algún sink de prueba). Si un
`symbol` no coincide exactamente con el que espera el plugin instalado,
PipeWire no levanta la cadena — revisar `journalctl --user -u pipewire`
para ver el error puntual.

**Importante para `Calf StereoTools`**: no subir el ensanchamiento
(`width` o el símbolo equivalente que muestre `lv2info`) a ciegas — un
valor alto genera problemas de fase al sumar L+R, crítico en FM. Subir
de a poco y verificar la suma mono.

## Monitoreo y diagnóstico

```bash
systemctl --user status pipewire wireplumber   # servicio arriba
wpctl status                                    # dispositivos y default
pw-top                                          # xruns y carga en vivo
journalctl --user -u pipewire -f                # log en vivo
```

Si el audio se corta o se degrada: lo primero es `pw-top` para
descartar xruns por CPU saturado, y después revisar que la MVSilicon
no se haya "reenumerado" con otro nombre de `node.name` tras un
desconecte/reconecte USB (pasa con algunas interfaces baratas) — en ese
caso hay que volver a fijarla con `wpctl set-default`.

## Estructura del repositorio

```
config/
  pipewire/filter-chain-fm.conf   # la cadena de plugins (plantilla)
  limits.d/audio.conf             # límites RT (rtprio, memlock) para PipeWire
  systemd/cpu-performance.service # fija el governor de CPU en "performance"
install.sh                        # instala paquetes, copia config, habilita todo
```
