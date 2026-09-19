"""Envoltorio fino sobre pulsectl para las operaciones que necesita cadenaL.

Funciona tanto contra PulseAudio nativo como contra PipeWire con
pipewire-pulse (la capa de compatibilidad que trae Debian/Q4OS por
defecto), porque en ambos casos el socket que se habla es el protocolo
de PulseAudio.

Todas las llamadas que van al servidor de audio pasan por `_call`, que
les impone un timeout duro. En produccion (RadioLinuxMadariaga) se dio
el caso de que PipeWire quedara colgado/degradado -ni siquiera 'pactl'
corrido a mano respondia, y eso colgaba tambien la barra de tareas del
escritorio-. Sin este limite, cualquiera de estas llamadas puede
bloquear el daemon entero para siempre sin ningun error visible.
pulsectl no expone un timeout por-llamada en su API publica, asi que
se impone desde afuera corriendo cada llamada en un hilo aparte: si no
vuelve a tiempo, se la abandona (queda un hilo daemon colgado, pero el
proceso sigue respondiendo) y quien llamo recibe un error tratable.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

import pulsectl

log = logging.getLogger("cadenal.audio")

# Drivers de PulseAudio/PipeWire que identifican un sink respaldado por
# hardware real (tarjeta de sonido fisica), a diferencia de sinks
# virtuales (module-null-sink, module-combine-sink, module-remap-sink,
# los que crea Viper4Linux, etc.)
_PHYSICAL_DRIVERS = {"module-alsa-card.c", "module-alsa-sink.c"}

# Timeout duro por llamada individual al servidor de audio. 2-3s es
# tiempo de sobra en un servidor sano (estas operaciones normalmente
# tardan milisegundos) y suficientemente corto como para que el daemon
# nunca quede visiblemente trabado.
DEFAULT_TIMEOUT = 3.0


class OperationTimedOut(Exception):
    """Una llamada a pulsectl no respondio dentro del tiempo limite."""


def _call(func: Callable, *args, timeout: float = DEFAULT_TIMEOUT, **kwargs):
    """Ejecuta func(*args, **kwargs) con un limite de tiempo duro.

    La llamada real corre en un hilo aparte (daemon thread): si el
    servidor de audio esta colgado y nunca responde, ese hilo queda
    abandonado ahi para siempre, pero el hilo que llamo a `_call`
    recupera el control de todos modos apenas se cumple el timeout.
    """
    box: dict = {}

    def _target():
        try:
            box["value"] = func(*args, **kwargs)
        except BaseException as exc:  # se re-lanza tal cual mas abajo
            box["error"] = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        name = getattr(func, "__name__", repr(func))
        raise OperationTimedOut(f"{name} no respondio en {timeout}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


@dataclass
class PhysicalSink:
    index: int
    name: str
    description: str
    driver: str


def list_physical_sinks(pulse: pulsectl.Pulse) -> List[PhysicalSink]:
    """Devuelve los sinks respaldados por una salida de audio fisica real."""
    try:
        sinks = _call(pulse.sink_list)
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


def find_sink_by_name(pulse: pulsectl.Pulse, name: str):
    try:
        sinks = _call(pulse.sink_list)
    except (OperationTimedOut, pulsectl.PulseError) as exc:
        log.warning("No se pudo listar los sinks: %s", exc)
        return None
    for s in sinks:
        if s.name == name:
            return s
    return None


def sink_name_by_index(pulse: pulsectl.Pulse, index: int) -> Optional[str]:
    try:
        return _call(pulse.sink_info, index).name
    except (OperationTimedOut, pulsectl.PulseError):
        return None


def ensure_virtual_sink(pulse: pulsectl.Pulse, name: str, description: str) -> int:
    """Crea (si no existe) el sink nulo virtual y devuelve su indice."""
    existing = find_sink_by_name(pulse, name)
    if existing is not None:
        return existing.index

    log.info("Creando sink virtual '%s'", name)
    props = f'sink_name={name} sink_properties=device.description="{description}"'
    try:
        _call(pulse.module_load, "module-null-sink", props)
    except (OperationTimedOut, pulsectl.PulseError) as exc:
        raise RuntimeError(f"No se pudo cargar module-null-sink para '{name}': {exc}") from exc

    created = find_sink_by_name(pulse, name)
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


def move_sink_input(pulse: pulsectl.Pulse, sink_input_index: int, target_sink_index: int) -> bool:
    try:
        _call(pulse.sink_input_move, sink_input_index, target_sink_index)
        return True
    except OperationTimedOut as exc:
        log.warning("Timeout moviendo sink-input %s: %s", sink_input_index, exc)
        return False
    except pulsectl.PulseOperationFailed as exc:
        log.warning("No se pudo mover sink-input %s: %s", sink_input_index, exc)
        return False


def sink_input_info_safe(pulse: pulsectl.Pulse, index: int):
    try:
        return _call(pulse.sink_input_info, index)
    except (OperationTimedOut, pulsectl.PulseIndexError, pulsectl.PulseError):
        return None


def sink_input_list_safe(pulse: pulsectl.Pulse) -> List:
    try:
        return _call(pulse.sink_input_list)
    except (OperationTimedOut, pulsectl.PulseError) as exc:
        log.warning("No se pudo listar los sink-inputs: %s", exc)
        return []


def status_report(sink_name: str) -> str:
    """Genera el mismo texto de estado para CLI y GUI."""
    lines: List[str] = []
    with pulsectl.Pulse("cadenal-status") as pulse:
        sink = find_sink_by_name(pulse, sink_name)
        if sink is None:
            lines.append(f"El sink virtual '{sink_name}' no existe todavia.")
            lines.append("Corre 'cadenal setup' o inicia el servicio.")
            return "\n".join(lines)

        lines.append(f"Sink virtual: {sink.name} (index {sink.index})")
        lines.append(f"Descripcion : {sink.description}")

        all_inputs = sink_input_list_safe(pulse)
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
