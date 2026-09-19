from __future__ import annotations

import argparse
import logging
import sys

import pulsectl

from . import audio
from .config import CONFIG_PATH, Config
from .daemon import CadenalDaemon


def _cmd_scan(args: argparse.Namespace) -> int:
    with pulsectl.Pulse("cadenal-scan") as pulse:
        sinks = audio.list_physical_sinks(pulse)
    if not sinks:
        print("No se detectaron salidas de audio fisicas.")
        return 1

    print("Salidas de audio fisicas detectadas:\n")
    for s in sinks:
        print(f"  [{s.index}] {s.name}")
        print(f"        {s.description}  (driver: {s.driver})")

    cfg = Config.load()
    cfg.known_physical_sinks = [s.name for s in sinks]
    cfg.save()
    print(f"\nGuardado en la configuracion ({len(sinks)} salida(s)).")
    return 0


def _cmd_setup(args: argparse.Namespace) -> int:
    cfg = Config.load()
    if args.name:
        cfg.sink_name = args.name
    if args.description:
        cfg.description = args.description
    if args.exclude:
        cfg.exclude_apps = args.exclude

    with pulsectl.Pulse("cadenal-setup") as pulse:
        index = audio.ensure_virtual_sink(pulse, cfg.sink_name, cfg.description)
        print(f"Sink virtual '{cfg.sink_name}' listo (index {index}).")

    cfg.save()
    print(f"Configuracion guardada en {CONFIG_PATH}.")
    print("\nSiguiente paso: habilita el servicio para que quede corriendo:")
    print("  systemctl --user enable --now cadenal.service")
    print(
        f"\nEn Viper4Linux (u otro procesador) usa como entrada el monitor "
        f"de '{cfg.sink_name}' (aparece como '{cfg.sink_name}.monitor')."
    )
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = Config.load()
    print(audio.status_report(cfg.sink_name))
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = Config.load()
    daemon = CadenalDaemon(cfg)
    try:
        daemon.run_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cadenal",
        description=(
            "cadenaL: enruta automaticamente todo el audio de la maquina "
            "(cualquier app, instancias de VLC que se abren y cierran, "
            "motores de audio, sinks virtuales) hacia una unica salida "
            "virtual de audio."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp_scan = sub.add_parser("scan", help="Escanea las salidas de audio fisicas actuales")
    sp_scan.set_defaults(func=_cmd_scan)

    sp_setup = sub.add_parser("setup", help="Crea/configura el sink virtual de destino")
    sp_setup.add_argument("--name", help="Nombre interno del sink virtual (sin espacios)")
    sp_setup.add_argument("--description", help="Descripcion visible del sink virtual")
    sp_setup.add_argument(
        "--exclude",
        nargs="*",
        help="Nombres de aplicaciones (application.name) a NO enrutar",
    )
    sp_setup.set_defaults(func=_cmd_setup)

    sp_status = sub.add_parser("status", help="Muestra el estado actual del enrutamiento")
    sp_status.set_defaults(func=_cmd_status)

    sp_start = sub.add_parser("start", help="Inicia el daemon en primer plano")
    sp_start.set_defaults(func=_cmd_start)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
