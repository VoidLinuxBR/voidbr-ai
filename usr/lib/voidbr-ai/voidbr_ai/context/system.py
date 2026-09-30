# -*- coding: utf-8 -*-
#
#   voidbr_ai/context/system.py - contexto do sistema
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Contexto do sistema, coletado sob demanda.

Cada campo tem o seu coletor; o Agent pede só os campos de que o
diagnóstico precisa (BASE para qualquer um, os demais quando fizer sentido).
"""

import os
import platform

from ..util import read_file, run, which

BASE = ["distro", "kernel", "arch", "init", "package_manager", "desktop"]


def _os_release():
    dados = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        texto = read_file(path)
        if texto:
            for linha in texto.splitlines():
                if "=" in linha and not linha.startswith("#"):
                    k, v = linha.split("=", 1)
                    dados[k.strip()] = v.strip().strip('"')
            break
    return dados


def distro():
    osr = _os_release()
    return {
        "name": osr.get("PRETTY_NAME") or osr.get("NAME") or "desconhecida",
        "id": osr.get("ID", ""),
        "version": osr.get("VERSION_ID") or osr.get("VERSION") or osr.get("BUILD_ID") or "",
        "libc": "musl" if any(f.startswith("ld-musl") for f in _ls("/lib")) else "glibc",
    }


def _ls(d):
    try:
        return os.listdir(d)
    except OSError:
        return []


def kernel():
    return platform.release()


def arch():
    return platform.machine()


def init():
    pid1 = (read_file("/proc/1/comm") or "").strip()
    runit = os.path.isdir("/etc/runit") or os.path.isdir("/run/runit") or pid1 == "runit"
    return {
        "pid1": pid1 or "?",
        "service_manager": "runit" if runit else ("systemd" if pid1 == "systemd" else pid1),
        "service_dir": "/var/service" if os.path.isdir("/var/service") else "",
    }


def package_manager():
    return {
        "xbps": bool(which("xbps-install")),
        "vinstall": bool(which("vinstall")),
        "pkgmake": bool(which("pkgmake")),
    }


def desktop():
    return {
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session": os.environ.get("XDG_SESSION_TYPE", "")
                   or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else
                       "x11" if os.environ.get("DISPLAY") else "tty"),
    }


def cpu():
    for linha in (read_file("/proc/cpuinfo") or "").splitlines():
        if linha.startswith("model name"):
            return linha.split(":", 1)[1].strip()
    return platform.processor() or "?"


def memory():
    info = {}
    for linha in (read_file("/proc/meminfo") or "").splitlines():
        k, _, v = linha.partition(":")
        if k in ("MemTotal", "MemAvailable"):
            info[k] = int(v.split()[0]) // 1024  # MiB
    return {"total_mib": info.get("MemTotal"), "available_mib": info.get("MemAvailable")}


def gpu():
    r = run(["lspci"], timeout=5)
    if r["rc"] != 0:
        return []
    return [l.split(": ", 1)[-1] for l in r["out"].splitlines()
            if " VGA " in l or "3D controller" in l or "Display controller" in l]


COLLECTORS = {
    "distro": distro, "kernel": kernel, "arch": arch, "init": init,
    "package_manager": package_manager, "desktop": desktop,
    "cpu": cpu, "memory": memory, "gpu": gpu,
}


def collect(fields=None):
    """Coleta só os campos pedidos (padrão: BASE)."""
    ctx = {}
    for nome in fields or BASE:
        f = COLLECTORS.get(nome)
        if f:
            try:
                ctx[nome] = f()
            except Exception as e:  # um coletor quebrado não derruba o diagnóstico
                ctx[nome] = {"erro": str(e)}
    return ctx
