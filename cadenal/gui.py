"""Ventana simple de configuracion de cadenaL (Tkinter, sin dependencias extra).

Solo hace tareas puntuales (escanear, crear el sink, arrancar/detener el
servicio, mostrar estado). El enrutamiento continuo lo hace siempre el
daemon (`cadenal start`), corriendo como servicio systemd --user, no la
GUI en si.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import audio, service
from .config import Config


class CadenalGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("cadenaL - Configuracion")
        self.geometry("560x620")
        self.minsize(520, 560)

        self.cfg = Config.load()

        self._build_widgets()
        self._refresh_service_status()
        self._on_scan()

    # ---- construccion de la interfaz -------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # --- Sink virtual ---
        frm_sink = ttk.LabelFrame(self, text="Salida virtual de destino")
        frm_sink.pack(fill="x", **pad)

        ttk.Label(frm_sink, text="Nombre interno:").grid(row=0, column=0, sticky="w", **pad)
        self.var_name = tk.StringVar(value=self.cfg.sink_name)
        ttk.Entry(frm_sink, textvariable=self.var_name).grid(
            row=0, column=1, sticky="ew", **pad
        )

        ttk.Label(frm_sink, text="Descripcion:").grid(row=1, column=0, sticky="w", **pad)
        self.var_desc = tk.StringVar(value=self.cfg.description)
        ttk.Entry(frm_sink, textvariable=self.var_desc).grid(
            row=1, column=1, sticky="ew", **pad
        )
        frm_sink.columnconfigure(1, weight=1)

        ttk.Button(frm_sink, text="Crear / Aplicar sink virtual", command=self._on_apply).grid(
            row=2, column=0, columnspan=2, sticky="ew", **pad
        )

        # --- Salidas fisicas detectadas ---
        frm_scan = ttk.LabelFrame(self, text="Salidas de audio fisicas detectadas")
        frm_scan.pack(fill="both", expand=False, **pad)

        self.list_physical = tk.Listbox(frm_scan, height=5)
        self.list_physical.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        ttk.Button(frm_scan, text="Volver a escanear", command=self._on_scan).pack(
            anchor="e", padx=8, pady=6
        )

        # --- Aplicaciones excluidas ---
        frm_excl = ttk.LabelFrame(self, text="Aplicaciones excluidas (no se enrutan)")
        frm_excl.pack(fill="x", **pad)

        self.list_exclude = tk.Listbox(frm_excl, height=4)
        self.list_exclude.pack(fill="x", padx=8, pady=(4, 0))
        for name in self.cfg.exclude_apps:
            self.list_exclude.insert("end", name)

        frm_excl_ctrl = ttk.Frame(frm_excl)
        frm_excl_ctrl.pack(fill="x", padx=8, pady=6)
        self.var_new_exclude = tk.StringVar()
        ttk.Entry(frm_excl_ctrl, textvariable=self.var_new_exclude).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(frm_excl_ctrl, text="Agregar", command=self._on_add_exclude).pack(
            side="left", padx=4
        )
        ttk.Button(frm_excl_ctrl, text="Quitar seleccionada", command=self._on_remove_exclude).pack(
            side="left"
        )

        # --- Servicio ---
        frm_service = ttk.LabelFrame(self, text="Servicio (systemd --user)")
        frm_service.pack(fill="x", **pad)

        self.var_status = tk.StringVar(value="Estado: desconocido")
        ttk.Label(frm_service, textvariable=self.var_status).pack(anchor="w", padx=8, pady=4)

        frm_service_btns = ttk.Frame(frm_service)
        frm_service_btns.pack(fill="x", padx=8, pady=6)
        ttk.Button(
            frm_service_btns, text="Habilitar e iniciar", command=self._on_enable
        ).pack(side="left", padx=2)
        ttk.Button(frm_service_btns, text="Detener", command=self._on_stop).pack(
            side="left", padx=2
        )
        ttk.Button(
            frm_service_btns, text="Actualizar estado", command=self._refresh_service_status
        ).pack(side="left", padx=2)

        # --- Estado de enrutamiento ---
        frm_route = ttk.LabelFrame(self, text="Streams enrutados ahora")
        frm_route.pack(fill="both", expand=True, **pad)

        self.txt_status = tk.Text(frm_route, height=8, wrap="word")
        self.txt_status.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        ttk.Button(frm_route, text="Actualizar", command=self._on_refresh_routing).pack(
            anchor="e", padx=8, pady=6
        )

    # ---- acciones ----------------------------------------------------
    def _on_scan(self) -> None:
        self.list_physical.delete(0, "end")
        if not audio.server_alive():
            messagebox.showerror("cadenaL", "No se pudo conectar al servidor de audio.")
            return
        sinks = audio.list_physical_sinks()

        if not sinks:
            self.list_physical.insert("end", "(no se detectaron salidas fisicas)")
        for s in sinks:
            self.list_physical.insert("end", f"[{s.index}] {s.name} - {s.description}")

        self.cfg.known_physical_sinks = [s.name for s in sinks]

    def _on_add_exclude(self) -> None:
        name = self.var_new_exclude.get().strip()
        if not name:
            return
        self.list_exclude.insert("end", name)
        self.var_new_exclude.set("")

    def _on_remove_exclude(self) -> None:
        sel = list(self.list_exclude.curselection())
        for i in reversed(sel):
            self.list_exclude.delete(i)

    def _collect_config(self) -> Config:
        self.cfg.sink_name = self.var_name.get().strip() or self.cfg.sink_name
        self.cfg.description = self.var_desc.get().strip() or self.cfg.description
        self.cfg.exclude_apps = list(self.list_exclude.get(0, "end"))
        return self.cfg

    def _on_apply(self) -> None:
        cfg = self._collect_config()
        try:
            index = audio.ensure_virtual_sink(cfg.sink_name, cfg.description)
        except RuntimeError as exc:
            messagebox.showerror("cadenaL", f"No se pudo crear el sink virtual:\n{exc}")
            return

        cfg.save()
        messagebox.showinfo(
            "cadenaL",
            f"Sink virtual '{cfg.sink_name}' listo (index {index}).\n\n"
            f"En Viper4Linux usa como entrada '{cfg.sink_name}.monitor'.\n\n"
            "Recorda habilitar el servicio para que el enrutamiento quede activo.",
        )
        self._on_refresh_routing()

    def _refresh_service_status(self) -> None:
        try:
            active = service.is_active()
            enabled = service.is_enabled()
        except (OSError, FileNotFoundError):
            self.var_status.set("Estado: systemctl no disponible (no es un entorno systemd)")
            return
        estado = "activo" if active else "detenido"
        arranque = "habilitado" if enabled else "no habilitado"
        self.var_status.set(f"Estado: {estado} - inicio automatico: {arranque}")

    def _on_enable(self) -> None:
        result = service.enable_now()
        if result.returncode != 0:
            messagebox.showerror(
                "cadenaL",
                "No se pudo habilitar/iniciar el servicio.\n\n"
                f"{result.stderr.strip()}\n\n"
                "Verifica que copiaste systemd/cadenal.service a "
                "~/.config/systemd/user/ y corriste 'systemctl --user daemon-reload'.",
            )
        self._refresh_service_status()

    def _on_stop(self) -> None:
        service.stop()
        self._refresh_service_status()

    def _on_refresh_routing(self) -> None:
        cfg = self._collect_config()
        self.txt_status.delete("1.0", "end")
        report = audio.status_report(cfg.sink_name)
        self.txt_status.insert("1.0", report)


def main() -> int:
    app = CadenalGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
