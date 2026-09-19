"""Icono de bandeja del sistema para cadenaL (al lado del reloj).

Muestra de un vistazo si el daemon esta activo y da acceso rapido a la
ventana de configuracion y al estado de enrutamiento, sin depender de
una terminal. El icono en si no hace el enrutamiento -eso lo sigue
haciendo el servicio systemd --user- solo lo monitorea y da controles
rapidos.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    print(
        "Faltan dependencias para el icono de bandeja: pystray y Pillow.\n"
        "Instalalas con: pip install --user pystray pillow\n"
        f"(detalle: {exc})",
        file=sys.stderr,
    )
    raise SystemExit(1)

from . import audio, service
from .config import Config

_POLL_SECONDS = 5

_COLOR_ACTIVE = (127, 211, 255, 255)     # celeste, mismo estilo del icono de la app
_COLOR_INACTIVE = (150, 150, 150, 255)   # gris: servicio detenido
_COLOR_BG = (22, 31, 46, 255)
_COLOR_DOT = (255, 209, 102, 255)
_COLOR_SPEAKER = (244, 247, 251, 255)


def _build_icon_image(active: bool) -> "Image.Image":
    color = _COLOR_ACTIVE if active else _COLOR_INACTIVE
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 2, size - 2], radius=12, fill=_COLOR_BG)

    # tres fuentes de audio convergiendo en una sola salida
    d.line([(10, 16), (30, 30)], fill=color, width=3)
    d.line([(10, 32), (30, 32)], fill=color, width=3)
    d.line([(10, 48), (30, 34)], fill=color, width=3)
    for y in (16, 32, 48):
        d.ellipse([7, y - 3, 13, y + 3], fill=_COLOR_DOT)

    d.line([(30, 32), (46, 32)], fill=color, width=4)
    d.rectangle([46, 22, 54, 42], fill=_COLOR_SPEAKER)
    d.polygon([(46, 32), (38, 26), (38, 38)], fill=_COLOR_SPEAKER)
    return img


class CadenalTray:
    def __init__(self):
        self.cfg = Config.load()
        self._active = False
        self.icon = pystray.Icon(
            "cadenal",
            icon=_build_icon_image(False),
            title=self._tooltip(),
            menu=self._build_menu(),
        )

    def _tooltip(self) -> str:
        estado = "activo" if self._active else "detenido"
        return f"cadenaL - {self.cfg.sink_name} ({estado})"

    def _build_menu(self) -> "pystray.Menu":
        return pystray.Menu(
            pystray.MenuItem(lambda item: self._tooltip(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir configuracion", self._on_open_config),
            pystray.MenuItem("Ver estado detallado", self._on_show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Iniciar servicio",
                self._on_start,
                visible=lambda item: not self._active,
            ),
            pystray.MenuItem(
                "Detener servicio",
                self._on_stop,
                visible=lambda item: self._active,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir del icono (no detiene el daemon)", self._on_quit),
        )

    def _on_open_config(self, icon, item) -> None:
        subprocess.Popen(["cadenal-gui"])

    def _on_show_status(self, icon, item) -> None:
        self.cfg = Config.load()
        try:
            report = audio.status_report(self.cfg.sink_name)
        except Exception as exc:
            report = f"No se pudo obtener el estado:\n{exc}"
        self._notify("cadenaL - estado de enrutamiento", report)

    def _notify(self, title: str, body: str) -> None:
        try:
            subprocess.run(["notify-send", title, body], timeout=3)
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

    def _on_start(self, icon, item) -> None:
        service.enable_now()
        self._refresh(force=True)

    def _on_stop(self, icon, item) -> None:
        service.stop()
        self._refresh(force=True)

    def _on_quit(self, icon, item) -> None:
        icon.stop()

    def _refresh(self, force: bool = False) -> None:
        try:
            active = service.is_active()
        except (OSError, FileNotFoundError):
            active = False
        if force or active != self._active:
            self._active = active
            self.icon.icon = _build_icon_image(active)
            self.icon.title = self._tooltip()
            self.icon.update_menu()

    def _poll_loop(self) -> None:
        while True:
            self._refresh()
            time.sleep(_POLL_SECONDS)

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.icon.run()


def main() -> int:
    CadenalTray().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
