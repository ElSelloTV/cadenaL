from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from typing import List

from . import audio, fx, service
from .config import CONFIG_PATH, Config
from .daemon import CadenalDaemon


def _cmd_scan(args: argparse.Namespace) -> int:
    sinks = audio.list_physical_sinks()
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
    if args.exclude_sink:
        cfg.exclude_sink_targets = args.exclude_sink

    index = audio.ensure_virtual_sink(cfg.sink_name, cfg.description)
    print(f"Sink virtual '{cfg.sink_name}' listo (index {index}).")

    cfg.save()
    print(f"Configuracion guardada en {CONFIG_PATH}.")
    print("\nSiguiente paso: habilita el servicio para que quede corriendo:")
    print("  systemctl --user enable --now cadenal.service")
    print(
        f"\nEn Viper4Linux (u otro procesador) usa como entrada el monitor "
        f"de '{cfg.sink_name}' (aparece como '{cfg.sink_name}.monitor')."
    )
    if cfg.exclude_sink_targets:
        print(f"\nSinks protegidos (no se tocan): {', '.join(cfg.exclude_sink_targets)}")
    else:
        print(
            "\nSi tenes una salida aparte para preview/cue (ej. auriculares del "
            "panel) que NO queres que se mezcle con el master, agregala con:\n"
            "  cadenal setup --exclude-sink <nombre_del_sink>"
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
    # si no se paso --target, reusamos el que ya estaba guardado (asi
    # 'cadenal fx setup' sin argumentos sirve para re-generar/recargar
    # el snippet, por ejemplo despues de un 'cadenal fx save').
    target = args.target or cfg.fx_target_sink
    if args.target:
        cfg.fx_target_sink = args.target
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
    if fx.controls_path().exists():
        print(
            "Se aplicaron los valores guardados con 'cadenal fx save' "
            f"({fx.controls_path()})."
        )
    else:
        print("Los parametros de cada plugin quedan en sus valores por defecto.")
    print(
        "Para afinarlos (compresion, ganancia, agudos, etc.) usa una herramienta "
        "con interfaz grafica para plugins LV2 como 'carla' o 'qpwgraph', "
        "apuntando al nodo 'CadenaL FX'. Despues de ajustar, corre "
        "'cadenal fx save' y volve a correr 'cadenal fx setup' para que el "
        "ajuste quede guardado y sobreviva al proximo reinicio."
    )
    return 0


def _cmd_fx_save(args: argparse.Namespace) -> int:
    try:
        controls = fx.save_controls()
    except RuntimeError as exc:
        print(f"No se pudieron guardar los valores: {exc}")
        return 1

    found = [role for role in fx.ROLE_ORDER if controls.get(role)]
    missing = [role for role in fx.ROLE_ORDER if role not in found]

    print(f"Valores guardados en: {fx.controls_path()}")
    if found:
        print(f"Se encontraron controles para: {', '.join(found)}")
    if missing:
        print(f"No se encontraron controles para: {', '.join(missing)}")
        print(
            "(puede que la cadena fx no este corriendo en este momento, o que "
            "esta version de PipeWire exponga los nombres de otra forma). "
            f"Se guardo un volcado de diagnostico en {fx.debug_dump_path()} "
            "por si hace falta ajustar la deteccion."
        )

    print(
        "\nPara que estos valores queden aplicados de forma persistente "
        "(incluso despues de reiniciar la PC), corre:\n"
        "  cadenal fx setup\n"
        "  systemctl --user restart pipewire pipewire-pulse wireplumber"
    )
    return 0 if found else 1


def _cmd_fx_status(args: argparse.Namespace) -> int:
    if not fx.is_snippet_installed():
        print("La cadena fx no esta instalada. Corre 'cadenal fx setup'.")
        return 1
    print(f"Snippet instalado en: {fx.snippet_path()}")
    if fx.controls_path().exists():
        print(f"Valores guardados en uso: {fx.controls_path()}")
    else:
        print("Sin valores guardados: la cadena usa los valores de fabrica de cada plugin.")
    print()
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


def _recent_conflict_warnings() -> List[str]:
    """Busca en el log reciente del servicio avisos de posible enrutado
    en conflicto con otro programa (ver daemon.py)."""
    if shutil.which("journalctl") is None:
        return []
    try:
        out = subprocess.run(
            [
                "journalctl", "--user", "-u", "cadenal.service",
                "--since", "-1 hour", "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.SubprocessError:
        return []
    return [line for line in out.stdout.splitlines() if "OTRO programa" in line]


def _cmd_doctor(args: argparse.Namespace) -> int:
    cfg = Config.load()
    ok = True
    print("=== cadenaL doctor ===\n")

    try:
        active = service.is_active()
    except (OSError, FileNotFoundError):
        active = None
    if active is True:
        print("[OK] cadenal.service esta activo.")
    elif active is False:
        print("[AVISO] cadenal.service no esta activo (systemctl --user start cadenal.service).")
        ok = False
    else:
        print("[?] No se pudo consultar systemctl --user en este sistema.")

    if audio.server_alive():
        print("[OK] El servidor de audio (PulseAudio/PipeWire) responde.")
        server_ok = True
    else:
        print("[FALTA] No se pudo conectar al servidor de audio (o no respondio a tiempo).")
        server_ok = False
        ok = False

    if server_ok:
        sink = audio.find_sink_by_name(cfg.sink_name)
        all_inputs = audio.sink_input_list_safe()

        if sink is not None:
            print(f"[OK] Sink virtual '{cfg.sink_name}' existe (index {sink.index}).")
        else:
            print(f"[AVISO] El sink virtual '{cfg.sink_name}' todavia no existe.")
            ok = False

        if sink is not None and all_inputs:
            unrouted = [
                si
                for si in all_inputs
                if si.sink != sink.index
                and audio.application_name(si) not in cfg.exclude_apps
                and audio.sink_name_by_index(si.sink) not in cfg.exclude_sink_targets
            ]
            if unrouted:
                print(
                    f"[AVISO] Hay {len(unrouted)} stream(s) sin enrutar al mix "
                    "(corre 'cadenal status' para el detalle)."
                )
                ok = False
            else:
                print("[OK] Todos los streams relevantes estan enrutados al mix.")

    fx_report = fx.check_plugins()
    fx_missing = [role for role, info in fx_report.items() if info["found"] is False]
    if fx.is_snippet_installed():
        if fx_missing:
            print(f"[AVISO] Cadena fx instalada pero faltan plugins: {', '.join(fx_missing)}")
            ok = False
        else:
            print("[OK] Cadena fx instalada y plugins presentes.")
    else:
        print("[INFO] Cadena fx no instalada (opcional, 'cadenal fx setup' para instalarla).")

    conflicts = _recent_conflict_warnings()
    if conflicts:
        print(f"\n[AVISO] Posible conflicto de enrutado detectado en la ultima hora:")
        for line in conflicts[-5:]:
            print(f"    {line}")
        print(
            "\n  Esto pasa cuando otro programa (por ejemplo un enrutador propio "
            "del software de radio) tambien mueve el mismo stream. Ese programa "
            "debe dejar su salida en 'predeterminado del sistema' y nunca "
            "apuntar a un sink especifico por nombre, para que sea siempre "
            "cadenaL quien decida el enrutamiento (ver seccion 'Uso compuesto' "
            "del README)."
        )
        ok = False

    print()
    print("Todo OK." if ok else "Hay puntos para revisar (ver arriba).")
    return 0 if ok else 1


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
    sp_setup.add_argument(
        "--exclude-sink",
        nargs="*",
        help=(
            "Nombres de sinks fisicos 'protegidos': un stream que ya este "
            "sonando ahi no se mueve (ej. la salida de auriculares del "
            "panel usada para el previo/cue)"
        ),
    )
    sp_setup.set_defaults(func=_cmd_setup)

    sp_status = sub.add_parser("status", help="Muestra el estado actual del enrutamiento")
    sp_status.set_defaults(func=_cmd_status)

    sp_start = sub.add_parser("start", help="Inicia el daemon en primer plano")
    sp_start.set_defaults(func=_cmd_start)

    sp_doctor = sub.add_parser(
        "doctor", help="Chequeo de salud: servicio, servidor de audio, fx, posibles conflictos"
    )
    sp_doctor.set_defaults(func=_cmd_doctor)

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

    fx_save = fx_sub.add_parser(
        "save",
        help="Guarda los valores actuales de cada plugin (para que sobrevivan al reinicio)",
    )
    fx_save.set_defaults(fx_func=_cmd_fx_save)

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
