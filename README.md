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
                                 ▼
                    Entrada de esta PC (interfaz USB MVSilicon)
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
| Audio integrado | Realtek ALC662 (analógico, **sin usar**) |
| Audio real | USB MV-SILICON MVSilicon (entrada y salida) |
| SO actual | Debian 13 "trixie", PipeWire 1.4.2 |

Es una CPU floja (Jaguar de bajo clock, sin SMT). El diseño de abajo está
pensado explícitamente para no pedirle más de lo que puede dar de forma
sostenida, 24/7, sin nadie mirando.

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

```bash
sudo ./install.sh
```

Instala los paquetes necesarios, copia las configuraciones de
`config/` a su lugar, habilita los servicios, fija el governor de CPU y
deja logueado qué falta ajustar a mano (nombres reales de dispositivo
ALSA, que dependen de tu MVSilicon).

Después de correrlo:

1. Identificar el nombre exacto de la interfaz USB:

   ```bash
   pw-cli ls Node | grep -i -A5 -i mvsilicon
   # o, más simple:
   wpctl status
   ```

2. Editar `/etc/pipewire/pipewire.conf.d/99-filter-chain-fm.conf` (ya
   copiado por `install.sh`) y completar `capture.props` / `playback.props`
   con el `node.name` real que aparece en `wpctl status` para la
   MVSilicon (entrada y salida).

3. Fijar esa interfaz como dispositivo por defecto (si no queda solo):

   ```bash
   wpctl status                 # anotar el ID del sink/source MVSilicon
   wpctl set-default <ID>
   ```

4. Reiniciar PipeWire para aplicar la cadena:

   ```bash
   systemctl --user restart pipewire wireplumber
   ```

5. Verificar que no hay xruns bajo carga real (dejarlo un rato con
   audio sonando):

   ```bash
   pw-top
   ```

   Cualquier columna de xruns (`ERR`) subiendo de forma sostenida es
   señal de que el `quantum` (buffer) elegido es muy chico para este
   CPU — subirlo en `pipewire.conf.d` (ver comentarios en el archivo).

## Afinar niveles (compresión, EQ, ancho estéreo)

Igual que antes: conectar una vez con un host de plugins gráfico —

```bash
sudo apt install carla
```

y mover los controles del nodo "CadenaL FM" escuchando el resultado.
Una vez conforme, guardar los valores en el propio archivo de config
(`filter-chain-fm.conf`, sección `Filter-chain -> filters -> control`)
para que sobrevivan al próximo reinicio — no dependas de un ajuste en
vivo que se pierde al reiniciar el proceso de PipeWire.

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
