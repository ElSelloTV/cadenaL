"""Prueba de integracion contra un servidor PulseAudio REAL (sin mocks).

Existe por un bug de fondo que paso desapercibido durante meses porque
nunca se corrio nada de esto contra un servidor de audio real
disparando un evento real: una conexion pulsectl.Pulse() que esta
corriendo event_listen() no puede usarse para NINGUNA operacion
bloqueante (sink_input_move, sink_list, etc.), ni siquiera desde otro
hilo -pulsectl tiene un guard de reentrancia interno que lo prohibe y
tira PulseError siempre-. Una version anterior de audio.py reusaba esa
misma conexion desde el hilo del timeout, asi que _handle_event()
jamas podia mover un stream nuevo: solo funcionaba el barrido inicial
(_sweep_existing, que corre ANTES de escuchar eventos). Este test
reproduce exactamente ese escenario -stream que aparece mientras el
daemon ya esta escuchando eventos, no antes- para que no se pueda
regresar a el sin que la suite lo note.

Requiere los binarios 'pulseaudio' y 'pacat' (paquete pulseaudio-utils)
en el PATH; se salta automaticamente si no estan disponibles (por
ejemplo, en el entorno en el que se escribio este archivo, que no tiene
acceso a un entorno Linux). Corre un servidor PulseAudio aislado en un
XDG_RUNTIME_DIR temporal para no tocar ninguna sesion de audio real de
la maquina que ejecute la suite.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

import pulsectl

from cadenal import audio
from cadenal.config import Config
from cadenal.daemon import CadenalDaemon

_PULSEAUDIO = shutil.which("pulseaudio")
_PACAT = shutil.which("pacat")

TEST_MIX_SINK = "cadenal_test_mix"
TEST_SOURCE_SINK = "cadenal_test_source"


@unittest.skipUnless(
    _PULSEAUDIO and _PACAT,
    "requiere 'pulseaudio' y 'pacat' (paquete pulseaudio-utils) en el PATH",
)
class DaemonMovesLiveStreamTest(unittest.TestCase):
    """Levanta un PulseAudio real y aislado, arranca el daemon de
    cadenaL contra el, y confirma que un stream que aparece EN VIVO
    (mientras el daemon ya esta con event_listen corriendo) se mueve
    al sink virtual. Antes del fix esto fallaba siempre: el stream se
    quedaba pegado en el sink original."""

    @classmethod
    def setUpClass(cls):
        cls._old_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        cls.runtime_dir = tempfile.mkdtemp(prefix="cadenal-test-pulse-")
        os.environ["XDG_RUNTIME_DIR"] = cls.runtime_dir

        subprocess.run(
            ["pulseaudio", "--start", "--exit-idle-time=-1", "--log-target=stderr"],
            check=True,
            capture_output=True,
            text=True,
        )
        cls._wait_for_socket(Path(cls.runtime_dir) / "pulse" / "native")

    @staticmethod
    def _wait_for_socket(sock_path: Path, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if sock_path.exists():
                return
            time.sleep(0.2)
        raise RuntimeError(f"El PulseAudio de prueba no levanto a tiempo ({sock_path})")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["pulseaudio", "--kill"], capture_output=True, text=True)
        shutil.rmtree(cls.runtime_dir, ignore_errors=True)
        if cls._old_runtime_dir is not None:
            os.environ["XDG_RUNTIME_DIR"] = cls._old_runtime_dir
        else:
            os.environ.pop("XDG_RUNTIME_DIR", None)

    def setUp(self):
        # sink "fisico" de prueba: a donde va a parar el stream primero,
        # antes de que el daemon lo mueva al mix.
        with pulsectl.Pulse("cadenal-test-setup") as pulse:
            pulse.module_load("module-null-sink", f"sink_name={TEST_SOURCE_SINK}")

        self.cfg = Config(sink_name=TEST_MIX_SINK, description="cadenaL test")
        self.daemon = CadenalDaemon(self.cfg)
        self._daemon_thread = threading.Thread(target=self.daemon.run_once, daemon=True)
        self._daemon_thread.start()
        self._wait_until(lambda: audio.find_sink_by_name(TEST_MIX_SINK) is not None, timeout=10)

        self._pacat_proc: subprocess.Popen | None = None

    def tearDown(self):
        if self._pacat_proc is not None:
            self._pacat_proc.terminate()
            try:
                self._pacat_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._pacat_proc.kill()

    @staticmethod
    def _wait_until(condition, timeout: float = 5.0, interval: float = 0.2) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(interval)
        return False

    def test_stream_created_while_daemon_is_listening_gets_moved_to_mix(self):
        # Disparamos un stream de reproduccion real DESPUES de que el
        # daemon ya esta en su loop de event_listen (no antes, que es
        # lo que _sweep_existing ya cubria y por eso el bug pasaba
        # desapercibido). /dev/zero como fuente: no hace falta ningun
        # archivo de audio, solo que exista un sink-input real.
        self._pacat_proc = subprocess.Popen(
            [
                "pacat",
                "--rate=44100",
                "--channels=2",
                "--format=s16le",
                f"--device={TEST_SOURCE_SINK}",
                "--raw",
            ],
            stdin=subprocess.PIPE,
        )
        # alimentamos silencio digital de a poco para que el proceso no
        # termine por falta de datos durante el tiempo del test
        def _feed():
            chunk = b"\x00" * 4096
            try:
                for _ in range(200):  # varios segundos de sobra
                    self._pacat_proc.stdin.write(chunk)
            except (BrokenPipeError, ValueError):
                pass

        threading.Thread(target=_feed, daemon=True).start()

        def _stream_is_on_mix() -> bool:
            mix = audio.find_sink_by_name(TEST_MIX_SINK)
            if mix is None:
                return False
            for si in audio.sink_input_list_safe():
                if si.sink == mix.index:
                    return True
            return False

        moved = self._wait_until(_stream_is_on_mix, timeout=10)

        self.assertTrue(
            moved,
            "El stream nunca aparecio enrutado al sink virtual mientras el "
            "daemon escuchaba eventos en vivo (si esto falla, volvio el bug "
            "de reentrancia: _call() esta reusando la conexion de "
            "event_listen en vez de abrir una propia).",
        )


if __name__ == "__main__":
    unittest.main()
