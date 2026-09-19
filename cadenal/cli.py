from __future__ import annotations

import argparse
import logging
import sys

import pulsectl

from . import audio, fx
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


def _cmd_fx_check(args: argparse.Namespace) -> int:
    ok = True
    print("Verificando requisitos del procesador de audio (fx)...\n")

    if fx.pipewire_installed():
        print("[OK] PipeWire esta instalado.")
    else:
        print("[FALTA] No se encontro el binario 'pipewire'. El procesador fx requiere PipeWire.")
        ok = False

    if not fx.lv2ls_installed():
        print(
            "[AVISO] No se encontro 'lv2ls' (paquete lv2-utils o lilv-utils); "
            "no se puede verificar que plugins LV2 estan instalados."
        )
    report = fx.check_plugins()
    print()
    for role in fx.ROLE_ORDER:
        info = report[role]
        if info["found"] is True:
            estado = "[OK]"
        elif info["found"] is False:
            estado = "[FALTA]"
            ok = False
        else:
            estado = "[?]"
        print(f"  {estado} {info['label']}")
        print(f"        uri: {info['uri']}  (paquete: {info['package']})")

    missing = fx.missing_apt_packages(report)
    if missing:
        print(f"\nInstalalos con:\n  sudo apt install {' '.join(missing)}")

    if fx.is_snippet_installed():
        print(f"\nLa cadena fx ya esta instalada en: {fx.snippet_path()}")
    else:
        print("\nLa cadena fx todavia no esta instalada (corre 'cadenal fx setup').")

    return 0 if ok else 1


def _cmd_fx_setup(args: argparse.Namespace) -> int:
    cfg = Config.load()
    target = args.target
    if target:
        cfg.fx_target_sink = target
        cfg.save()

    path = fx.install_snippet(source_sink=cfg.sink_name, target_sink=target)
    print(f"Snippet de PipeWire escrito en: {path}")
    print(f"Entrada: monitor de '{cfg.sink_name}'  ->  salida: sink '{fx.FX_SINK_NAME}'")
    if target:
        print(f"La salida procesada se enviara directo a: {target}")
    else:
        print(
            f"No se indico salida fisica: elegi '{fx.FX_SINK_NAME}' a mano en "
            "pavucontrol/qpwgraph, o corre de nuevo con --target <nombre_sink>."
        )

    print(
        "\nPara que tome efecto hay que reiniciar PipeWire (esto corta el audio "
        "un instante en toda la maquina):\n"
        "  systemctl --user restart pipewire pipewire-pulse wireplumber\n"
    )
    print("Los parametros de cada plugin quedan en sus valores por defecto.")
    print(
        "Para afinarlos (compresion, ganancia, agudos, etc.) usa una herramienta "
        "con interfaz grafica para plugins LV2 como 'carla' o 'qpwgraph', "
        "apuntando al nodo 'CadenaL FX'."
    )
    return 0


def _cmd_fx_status(args: argparse.Namespace) -> int:
    if not fx.is_snippet_installed():
        print("La cadena fx no esta instalada. Corre 'cadenal fx setup'.")
        return 1
    print(f"Snippet instalado en: {fx.snippet_path()}\n")
    print(audio.status_report(fx.FX_SINK_NAME))
    return 0


def _cmd_fx_remove(args: argparse.Namespace) -> int:
    removed = fx.remove_snippet()
    if removed:
        print("Snippet de fx eliminado.")
        print(
            "Para que tome efecto: "
            "systemctl --user restart pipewire pipewire-pulse wireplumber"
        )
    else:
        print("No habia ninguna cadena fx instalada.")
    return 0


def _cmd_fx(args: argparse.Namespace) -> int:
    return args.fx_func(args)


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

    sp_fx = sub.add_parser(
        "fx", help="Procesador de audio ultra-liviano (autoganancia/compresor/brillo/limitador)"
    )
    sp_fx.set_defaults(func=_cmd_fx)
    fx_sub = sp_fx.add_subparsers(dest="fx_command", required=True)

    fx_check = fx_sub.add_parser("check", help="Verifica PipeWire y los plugins LV2 necesarios")
    fx_check.set_defaults(fx_func=_cmd_fx_check)

    fx_setup = fx_sub.add_parser("setup", help="Instala la cadena de procesamiento")
    fx_setup.add_argument(
        "--target",
        help="Nombre del sink fisico donde enviar la salida ya procesada (opcional)",
    )
    fx_setup.set_defaults(fx_func=_cmd_fx_setup)

    fx_status = fx_sub.add_parser("status", help="Muestra el estado de la cadena de procesamiento")
    fx_status.set_defaults(fx_func=_cmd_fx_status)

    fx_remove = fx_sub.add_parser("remove", help="Quita la cadena de procesamiento")
    fx_remove.set_defaults(fx_func=_cmd_fx_remove)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
