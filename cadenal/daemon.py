"""Daemon principal de cadenaL.

Estrategia: en vez de perseguir sinks fisicos o intentar adivinar por
donde va a salir cada motor de audio, cadenaL intercepta a nivel de
"sink-input" (cada stream de reproduccion individual: cada instancia de
VLC, cada voz que dispara el software de radio, cualquier motor). Cada
vez que aparece un stream nuevo, o cambia de sink, se lo mueve al sink
virtual de destino si todavia no esta ahi. Es el enfoque mas liviano
posible: no hay polling, todo se resuelve por eventos del propio
servidor de audio, y es agnostico a cuantas salidas fisicas o virtuales
existan o se agreguen despues.
"""
from __future__ import annotations

import logging
import time

import pulsectl

from . import audio
from .config import Config

log = logging.getLogger("cadenal.daemon")

_RECONNECT_BACKOFF = (1, 2, 5, 10, 30)


class CadenalDaemon:
    def __init__(self, config: Config):
        self.config = config
        self.target_index: int | None = None

    def _should_ignore(self, pulse: pulsectl.Pulse, sink_input) -> bool:
        name = audio.application_name(sink_input)
        if name in self.config.exclude_apps:
            return True
        if self.config.exclude_sink_targets:
            current_sink_name = audio.sink_name_by_index(pulse, sink_input.sink)
            if current_sink_name in self.config.exclude_sink_targets:
                return True
        return False

    def _sweep_existing(self, pulse: pulsectl.Pulse) -> None:
        """Al arrancar (o reconectar), mueve todo lo que ya esta sonando."""
        for si in pulse.sink_input_list():
            if si.sink == self.target_index:
                continue
            if self._should_ignore(pulse, si):
                continue
            audio.move_sink_input(pulse, si.index, self.target_index)

    def _handle_event(self, pulse: pulsectl.Pulse, ev) -> None:
        if ev.facility == "sink" and ev.t == "remove" and ev.index == self.target_index:
            log.warning("El sink virtual desaparecio (index %s); se recreara", ev.index)
            self.target_index = audio.ensure_virtual_sink(
                pulse, self.config.sink_name, self.config.description
            )
            self._sweep_existing(pulse)
            return

        if ev.facility != "sink_input":
            return
        if ev.t not in ("new", "change"):
            return

        si = audio.sink_input_info_safe(pulse, ev.index)
        if si is None:
            return
        if si.sink == self.target_index:
            return
        if self._should_ignore(pulse, si):
            return

        audio.move_sink_input(pulse, si.index, self.target_index)

    def run_once(self) -> None:
        """Una sesion de conexion; se sale si se cae la conexion con el servidor de audio."""
        with pulsectl.Pulse("cadenal-daemon") as pulse:
            self.target_index = audio.ensure_virtual_sink(
                pulse, self.config.sink_name, self.config.description
            )
            log.info(
                "Sink virtual '%s' listo (index %s). Escuchando streams...",
                self.config.sink_name,
                self.target_index,
            )
            self._sweep_existing(pulse)

            pulse.event_mask_set("sink_input", "sink")

            def _cb(ev):
                try:
                    self._handle_event(pulse, ev)
                except pulsectl.PulseOperationFailed as exc:
                    log.warning("Error manejando evento %s: %s", ev, exc)
                raise pulsectl.PulseLoopStop

            pulse.event_callback_set(_cb)

            while True:
                pulse.event_listen(timeout=30)

    def run_forever(self) -> None:
        attempt = 0
        while True:
            try:
                self.run_once()
            except (pulsectl.PulseError, OSError) as exc:
                delay = _RECONNECT_BACKOFF[min(attempt, len(_RECONNECT_BACKOFF) - 1)]
                log.error(
                    "Se perdio la conexion con el servidor de audio (%s). "
                    "Reintentando en %ss...",
                    exc,
                    delay,
                )
                time.sleep(delay)
                attempt += 1
            else:
                attempt = 0
