"""Helpers finos sobre 'systemctl --user' para controlar el daemon."""
from __future__ import annotations

import subprocess

UNIT = "cadenal.service"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def is_active() -> bool:
    return _run("is-active", UNIT).stdout.strip() == "active"


def is_enabled() -> bool:
    return _run("is-enabled", UNIT).stdout.strip() == "enabled"


def start() -> subprocess.CompletedProcess:
    return _run("start", UNIT)


def stop() -> subprocess.CompletedProcess:
    return _run("stop", UNIT)


def enable_now() -> subprocess.CompletedProcess:
    return _run("enable", "--now", UNIT)


def disable_now() -> subprocess.CompletedProcess:
    return _run("disable", "--now", UNIT)
