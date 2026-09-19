"""Envoltorio fino sobre pulsectl para las operaciones que necesita cadenaL.

Funciona tanto contra PulseAudio nativo como contra PipeWire con
pipewire-pulse (la capa de compatibilidad que trae Debian/Q4OS por
defecto), porque en ambos casos el socket que se habla es el protocolo
de PulseAudio.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import pulsectl

log = logging.getLogger("cadenal.audio")

# Drivers de PulseAudio/PipeWire que identifican un sink respaldado por
# hardware real (tarjeta de sonido fisica), a diferencia de sinks
# virtuales (module-null-sink, module-combine-sink, module-remap-sink,
# los que crea Viper4Linux, etc.)
_PHYSICAL_DRIVERS = {"module-alsa-card.c", "module-alsa-sink.c"}


@dataclass
class PhysicalSink:
    index: int
    name: str
    description: str
    driver: str


def list_physical_sinks(pulse: pulsectl.Pulse) -> List[PhysicalSink]:
    """Devuelve los sinks respaldados por una salida de audio fisica real."""
    result = []
    for s in pulse.sink_list():
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
    for s in pulse.sink_list():
        if s.name == name:
            return s
    return None


def ensure_virtual_sink(pulse: pulsectl.Pulse, name: str, description: str) -> int:
    """Crea (si no existe) el sink nulo virtual y devuelve su indice."""
    existing = find_sink_by_name(pulse, name)
    if existing is not None:
        return existing.index

    log.info("Creando sink virtual '%s'", name)
    props = f'sink_name={name} sink_properties=device.description="{description}"'
    pulse.module_load("module-null-sink", props)

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
        pulse.sink_input_move(sink_input_index, target_sink_index)
        return True
    except pulsectl.PulseOperationFailed as exc:
        log.warning("No se pudo mover sink-input %s: %s", sink_input_index, exc)
        return False


def sink_input_info_safe(pulse: pulsectl.Pulse, index: int):
    try:
        return pulse.sink_input_info(index)
    except pulsectl.PulseIndexError:
        return None


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

        streams = [si for si in pulse.sink_input_list() if si.sink == sink.index]
        lines.append(f"\nStreams actualmente enrutados ahi: {len(streams)}")
        for si in streams:
            app = application_name(si) or "(desconocido)"
            lines.append(f"  [{si.index}] {app}")

        others = [si for si in pulse.sink_input_list() if si.sink != sink.index]
        if others:
            lines.append(f"\nStreams NO enrutados (deberian moverse solos en breve): {len(others)}")
            for si in others:
                app = application_name(si) or "(desconocido)"
                lines.append(f"  [{si.index}] {app}")
    return "\n".join(lines)
