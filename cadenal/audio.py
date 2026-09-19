"""Envoltorio fino sobre pulsectl para las operaciones que necesita cadenaL.

Funciona tanto contra PulseAudio nativo como contra PipeWire con
pipewire-pulse (la capa de compatibilidad que trae Debian/Q4OS por
defecto), porque en ambos casos el socket que se habla es el protocolo
de PulseAudio.

Regla de oro, verificada contra un servidor real (no solo leida en la
documentacion): una conexion pulsectl.Pulse() que esta corriendo
event_listen() NO puede usarse para ninguna operacion bloqueante
(sink_input_move, sink_list, module_load, etc.), ni siquiera desde otro
hilo. pulsectl tiene un guard de reentrancia interno que tira PulseError
apenas se intenta: el propio docstring de event_listen() lo dice
("Do not run any pulse operations from these callbacks"). Un daemon que
ignora esto (como una version anterior de este archivo) nunca puede
mover un stream nuevo -que es su funcion principal- porque
_handle_event corre siempre dentro de un callback de event_listen.

Por eso cada operacion de este modulo abre su PROPIA conexion nueva
(via `_call`), corrida en un hilo aparte con un timeout duro (ver mas
abajo por que hace falta el timeout). La conexion que usa el daemon
para event_listen()/event_mask_set()/event_callback_set() nunca pasa
por aca; queda aislada en daemon.py exclusivamente para escuchar.

El timeout duro por operacion es una proteccion aparte: en produccion
(RadioLinuxMadariaga) se dio el caso de que PipeWire quedara
colgado/degradado -ni siquiera 'pactl' corrido a mano respondia, y eso
colgaba tambien la barra de tareas del escritorio-. pulsectl no expone
timeout por-llamada en su API publica, asi que se impone desde afuera:
si la operacion no vuelve a tiempo, se abandona el hilo (queda un hilo
daemon colgado, pero el proceso sigue respondiendo) y quien llamo
recibe un error tratable.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import List, Optional

import pulsectl

log = logging.getLogger("cadenal.audio")

# Drivers de PulseAudio/PipeWire que identifican un sink respaldado por
# hardware real (tarjeta de sonido fisica), a diferencia de sinks
# virtuales (module-null-sink, module-combine-sink, module-remap-sink,
# los que crea Viper4Linux, etc.)
_PHYSICAL_DRIVERS = {"module-alsa-card.c", "module-alsa-sink.c"}

# Timeout duro por llamada individual al servidor de audio. 2-3s es
# tiempo de sobra en un servidor sano (estas operaciones normalmente
# tardan milisegundos, incluyendo el handshake de una conexion nueva)
# y suficientemente corto como para que el daemon nunca quede
# visiblemente trabado.
DEFAULT_TIMEOUT = 3.0

_CLIENT_NAME = "cadenal-op"


class OperationTimedOut(Exception):
    """Una llamada a pulsectl no respondio dentro del tiempo limite."""


def _call(func_name: str, *args, timeout: float = DEFAULT_TIMEOUT, **kwargs):
    """Ejecuta pulse.<func_name>(*args, **kwargs) sobre una conexion
    pulsectl.Pulse() nueva y descartable, con un limite de tiempo duro.

    Se abre una conexion nueva en cada llamada (en vez de reusar una ya
    existente) para nunca correr el riesgo de invocar una operacion
    bloqueante sobre la conexion que el daemon tiene escuchando eventos
    -eso dispara el guard de reentrancia de pulsectl y falla siempre
    con PulseError-. El costo es un handshake extra (unos ms); para la
    frecuencia de estas llamadas es aceptable y el timeout de mas abajo
    pone un techo duro de todos modos.

    La conexion y la llamada real corren en un hilo aparte (daemon
    thread): si el servidor esta colgado y nunca responde, ese hilo
    queda abandonado ahi para siempre, pero el hilo que llamo a `_call`
    recupera el control apenas se cumple el timeout.
    """
    box: dict = {}

    def _target():
        try:
            with pulsectl.Pulse(_CLIENT_NAME) as p:
                box["value"] = getattr(p, func_name)(*args, **kwargs)
        except BaseException as exc:  # se re-lanza tal cual mas abajo
            box["error"] = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise OperationTimedOut(f"{func_name} no respondio en {timeout}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


@dataclass
class PhysicalSink:
    index: int
    name: str
    description: str
    driver: str


def list_physical_sinks() -> List[PhysicalSink]:
    """Devuelve los sinks respaldados por una salida de audio fisica real."""
    try:
        sinks = _call("sink_list")
    except (OperationTimedOut, pulsectl.PulseError) as exc:
        log.warning("No se pudo listar los sinks: %s", exc)
        return []

    result = []
    for s in sinks:
        if s.driver in _PHYSICAL_DRIVERS:
            result.append(
                PhysicalSink(
                    index=s.index,
                    name=s.name,
                    description=s.description,
                    driver=s.driver,
                )
            )
    return result


def server_alive() -> bool:
    """True si el servidor de audio responde a una operacion basica."""
    try:
        _call("sink_list")
        return True
    except (OperationTimedOut, pulsectl.PulseError):
        return False


def find_sink_by_name(name: str):
    try:
        sinks = _call("sink_list")
    except (OperationTimedOut, pulsectl.PulseError) as exc:
        log.warning("No se pudo listar los sinks: %s", exc)
        return None
    for s in sinks:
        if s.name == name:
            return s
    return None


def sink_name_by_index(index: int) -> Optional[str]:
    try:
        return _call("sink_info", index).name
    except (OperationTimedOut, pulsectl.PulseError):
        return None


def ensure_virtual_sink(name: str, description: str) -> int:
    """Crea (si no existe) el sink nulo virtual y devuelve su indice."""
    existing = find_sink_by_name(name)
    if existing is not None:
        return existing.index

    log.info("Creando sink virtual '%s'", name)
    props = f'sink_name={name} sink_properties=device.description="{description}"'
    try:
        _call("module_load", "module-null-sink", props)
    except (OperationTimedOut, pulsectl.PulseError) as exc:
        raise RuntimeError(f"No se pudo cargar module-null-sink para '{name}': {exc}") from exc

    created = find_sink_by_name(name)
    if created is None:
        raise RuntimeError(
            f"No se pudo crear/encontrar el sink virtual '{name}' tras cargar el modulo"
        )
    return created.index


def application_name(sink_input) -> str:
    try:
        return sink_input.proplist.get("application.name", "") or ""
    except AttributeError:
        return ""


def move_sink_input(sink_input_index: int, target_sink_index: int) -> bool:
    try:
        _call("sink_input_move", sink_input_index, target_sink_index)
        return True
    except OperationTimedOut as exc:
        log.warning("Timeout moviendo sink-input %s: %s", sink_input_index, exc)
        return False
    except pulsectl.PulseOperationFailed as exc:
        log.warning("No se pudo mover sink-input %s: %s", sink_input_index, exc)
        return False


def sink_input_info_safe(index: int):
    try:
        return _call("sink_input_info", index)
    except (OperationTimedOut, pulsectl.PulseIndexError, pulsectl.PulseError):
        return None


def sink_input_list_safe() -> List:
    try:
        return _call("sink_input_list")
    except (OperationTimedOut, pulsectl.PulseError) as exc:
        log.warning("No se pudo listar los sink-inputs: %s", exc)
        return []


def status_report(sink_name: str) -> str:
    """Genera el mismo texto de estado para CLI y GUI."""
    lines: List[str] = []
    sink = find_sink_by_name(sink_name)
    if sink is None:
        lines.append(f"El sink virtual '{sink_name}' no existe todavia.")
        lines.append("Corre 'cadenal setup' o inicia el servicio.")
        return "\n".join(lines)

    lines.append(f"Sink virtual: {sink.name} (index {sink.index})")
    lines.append(f"Descripcion : {sink.description}")

    all_inputs = sink_input_list_safe()
    streams = [si for si in all_inputs if si.sink == sink.index]
    lines.append(f"\nStreams actualmente enrutados ahi: {len(streams)}")
    for si in streams:
        app = application_name(si) or "(desconocido)"
        lines.append(f"  [{si.index}] {app}")

    others = [si for si in all_inputs if si.sink != sink.index]
    if others:
        lines.append(f"\nStreams NO enrutados (deberian moverse solos en breve): {len(others)}")
        for si in others:
            app = application_name(si) or "(desconocido)"
            lines.append(f"  [{si.index}] {app}")
    return "\n".join(lines)
