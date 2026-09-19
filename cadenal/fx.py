"""Cadena de procesamiento de audio ultra-liviana de cadenaL.

En vez de escribir DSP propio (lento e inestable en tiempo real sobre
un CPU de 2 nucleos), se hospedan plugins LV2 ya optimizados en C
usando el modulo nativo de PipeWire 'filter-chain'
(libpipewire-module-filter-chain). No se levanta ningun proceso
adicional: el filtro corre dentro del propio proceso de PipeWire que
ya esta corriendo en la sesion.

Orden de la cadena, replicando un procesador de aire tipo Breakaway:

    AutoGanancia -> Compresor -> Brillo/cristalizador (EQ) -> Limitador

El limitador va siempre al final: es la ultima barrera de seguridad
contra picos, incluso los que puede introducir el realce de agudos del
bloque de brillo.

Plugins usados (estandar en cualquier distro, mucho mas livianos que
un convolver como el de Viper4Linux):

    - LSP Autogain      (paquete lsp-plugins-lv2)
    - Calf Compressor   (paquete calf-plugins)
    - Calf Equalizer 5 Band (paquete calf-plugins) -> bloque de "brillo"
    - Calf Limiter      (paquete calf-plugins)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .config import _config_dir

# URIs LV2: identificadores estables del plugin, no cambian entre
# versiones de distro ni de la libreria.
PLUGIN_AUTOGAIN = "http://lsp-plug.in/plugins/lv2/autogain_stereo"
PLUGIN_COMPRESSOR = "http://calf.sourceforge.net/plugins/Compressor"
PLUGIN_BRIGHTNESS = "http://calf.sourceforge.net/plugins/Equalizer5Band"
PLUGIN_LIMITER = "http://calf.sourceforge.net/plugins/Limiter"

# rol -> (uri, paquete apt que lo provee, etiqueta legible)
ROLES: Dict[str, tuple] = {
    "autogain": (PLUGIN_AUTOGAIN, "lsp-plugins-lv2", "Autoganancia (LSP Autogain)"),
    "compressor": (PLUGIN_COMPRESSOR, "calf-plugins", "Compresor (Calf Compressor)"),
    "brightness": (
        PLUGIN_BRIGHTNESS,
        "calf-plugins",
        "Brillo / cristalizador (Calf Equalizer 5 Band)",
    ),
    "limiter": (PLUGIN_LIMITER, "calf-plugins", "Limitador (Calf Limiter)"),
}
# orden real de la cadena de senal
ROLE_ORDER = ["autogain", "compressor", "brightness", "limiter"]

FX_SINK_NAME = "cadenal_fx"
FX_SNIPPET_FILENAME = "99-cadenal-fx.conf"
CONTROLS_FILENAME = "fx-controls.json"
CONTROLS_DEBUG_FILENAME = "fx-controls-debug.json"


def pipewire_conf_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pipewire" / "pipewire.conf.d"


def snippet_path() -> Path:
    return pipewire_conf_dir() / FX_SNIPPET_FILENAME


def pipewire_installed() -> bool:
    return shutil.which("pipewire") is not None


def lv2ls_installed() -> bool:
    return shutil.which("lv2ls") is not None


def list_installed_lv2_uris() -> Optional[List[str]]:
    """None si no se pudo determinar (falta lv2ls); lista de URIs si se pudo."""
    if not lv2ls_installed():
        return None
    try:
        out = subprocess.run(["lv2ls"], capture_output=True, text=True, timeout=15)
    except subprocess.SubprocessError:
        return None
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def check_plugins() -> Dict[str, dict]:
    """Por cada rol de la cadena: uri, paquete apt, etiqueta y si se
    encontro instalado (None si no se pudo verificar, por ejemplo por
    no tener 'lv2ls')."""
    installed = list_installed_lv2_uris()
    result = {}
    for role in ROLE_ORDER:
        uri, package, label = ROLES[role]
        found = None if installed is None else (uri in installed)
        result[role] = {"uri": uri, "package": package, "label": label, "found": found}
    return result


def missing_apt_packages(report: Dict[str, dict]) -> List[str]:
    packages = []
    for info in report.values():
        if info["found"] is False and info["package"] not in packages:
            packages.append(info["package"])
    return packages


def controls_path() -> Path:
    return _config_dir() / CONTROLS_FILENAME


def debug_dump_path() -> Path:
    return _config_dir() / CONTROLS_DEBUG_FILENAME


def _pw_dump() -> Optional[list]:
    if shutil.which("pw-dump") is None:
        return None
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=15)
    except subprocess.SubprocessError:
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def _looks_like_our_node(props: dict) -> bool:
    node_name = str(props.get("node.name", ""))
    media_name = str(props.get("media.name", ""))
    if media_name == "CadenaL FX":
        return True
    tail = node_name.rsplit("/", 1)[-1]
    return node_name in ROLE_ORDER or tail in ROLE_ORDER


def _role_for_node(props: dict) -> Optional[str]:
    node_name = str(props.get("node.name", ""))
    if node_name in ROLE_ORDER:
        return node_name
    tail = node_name.rsplit("/", 1)[-1]
    if tail in ROLE_ORDER:
        return tail
    return None


def _extract_role_controls(dump: list) -> Dict[str, Dict[str, float]]:
    """Busca en el volcado de PipeWire los nodos de la cadena fx y junta
    sus valores de control actuales, indexados por rol.

    Best-effort: la forma exacta en que PipeWire expone cada plugin LV2
    del filter-chain como nodo/props puede variar segun version. Si no
    encuentra nada devuelve un diccionario vacio; eso no rompe nada, la
    cadena sigue funcionando con los valores que ya tenga cargados
    (ver 'cadenal fx save' para el diagnostico si esto pasa).
    """
    result: Dict[str, Dict[str, float]] = {}
    for obj in dump:
        info = obj.get("info") or {}
        props = info.get("props") or {}
        role = _role_for_node(props)
        if role is None:
            continue

        params = info.get("params") or {}
        control_values: Dict[str, float] = {}
        for prop_set in params.get("Props", []):
            if not isinstance(prop_set, dict):
                continue
            for key, value in prop_set.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                control_values[key] = value
        if control_values:
            result[role] = control_values
    return result


def _collect_debug_candidates(dump: list) -> List[dict]:
    candidates = []
    for obj in dump:
        info = obj.get("info") or {}
        props = info.get("props") or {}
        if _looks_like_our_node(props):
            candidates.append(
                {
                    "id": obj.get("id"),
                    "type": obj.get("type"),
                    "props": props,
                    "params": info.get("params"),
                }
            )
    return candidates


def save_controls() -> Dict[str, Dict[str, float]]:
    """Lee los valores actuales de cada plugin de la cadena (via
    'pw-dump') y los guarda en disco, para poder reaplicarlos despues
    de un reinicio en vez de perder cualquier ajuste fino hecho a mano
    con Carla/qpwgraph."""
    dump = _pw_dump()
    if dump is None:
        raise RuntimeError(
            "No se pudo ejecutar 'pw-dump' (verifica que PipeWire este "
            "instalado, corriendo, y que la cadena fx este instalada)."
        )

    controls = _extract_role_controls(dump)

    controls_path().parent.mkdir(parents=True, exist_ok=True)
    controls_path().write_text(json.dumps(controls, indent=2, ensure_ascii=False), encoding="utf-8")

    debug_dump_path().parent.mkdir(parents=True, exist_ok=True)
    debug_dump_path().write_text(
        json.dumps(_collect_debug_candidates(dump), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return controls


def load_saved_controls() -> Dict[str, Dict[str, float]]:
    path = controls_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _build_graph_nodes(controls: Optional[Dict[str, Dict[str, float]]] = None) -> List[dict]:
    controls = controls or {}
    nodes = []
    for role in ROLE_ORDER:
        node = {"type": "lv2", "name": role, "plugin": ROLES[role][0]}
        role_controls = controls.get(role)
        if role_controls:
            node["control"] = role_controls
        nodes.append(node)
    return nodes


def generate_snippet(source_sink: str, target_sink: Optional[str] = None) -> str:
    """Genera el contenido del snippet de pipewire.conf.d para la cadena de FX.

    source_sink: nombre del sink cuyo monitor se toma como entrada
                 (normalmente el 'cadenal_mix' del enrutador principal).
    target_sink: si se indica, la salida procesada se envia directo a
                 ese sink fisico. Si se omite, se crea el sink
                 'cadenal_fx' sin destino fijo (elegilo a mano en
                 pavucontrol/qpwgraph).

    Si hay valores guardados con 'cadenal fx save', se embeben como
    'control' de cada nodo para que la cadena arranque con esos
    ajustes en vez de los valores de fabrica. Esto es lo que hace que
    un ajuste fino hecho a mano sobreviva al reinicio diario de la PC:
    el snippet queda escrito en disco con los valores ya adentro, y
    PipeWire lo vuelve a leer tal cual en cada arranque.
    """
    controls = load_saved_controls()
    playback_props = {
        "node.name": FX_SINK_NAME,
        "node.description": "CadenaL FX (procesador de aire)",
        "media.class": "Audio/Sink",
        "audio.channels": 2,
        "audio.position": ["FL", "FR"],
    }
    if target_sink:
        playback_props["target.object"] = target_sink

    config = {
        "context.modules": [
            {
                "name": "libpipewire-module-filter-chain",
                "args": {
                    "node.description": "CadenaL FX",
                    "media.name": "CadenaL FX",
                    "filter.graph": {"nodes": _build_graph_nodes(controls)},
                    "capture.props": {
                        "node.name": "cadenal_fx_in",
                        "target.object": source_sink,
                        "audio.channels": 2,
                        "audio.position": ["FL", "FR"],
                    },
                    "playback.props": playback_props,
                },
            }
        ]
    }
    # SPA-JSON (el formato de config de PipeWire) es un superconjunto
    # de JSON estricto, asi que un dump estandar es valido y evita
    # errores de sintaxis manuales.
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def install_snippet(source_sink: str, target_sink: Optional[str] = None) -> Path:
    path = snippet_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_snippet(source_sink, target_sink), encoding="utf-8")
    return path


def remove_snippet() -> bool:
    path = snippet_path()
    if path.exists():
        path.unlink()
        return True
    return False


def is_snippet_installed() -> bool:
    return snippet_path().exists()
