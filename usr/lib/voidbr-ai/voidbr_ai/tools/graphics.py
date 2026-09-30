# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/graphics.py - vídeo e sessão gráfica (Wayland)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Vídeo e sessão Wayland no VoidBR, segundo o Void Handbook:

- GPU com driver do kernel carregado e o firmware do fabricante
  (linux-firmware-amd / -intel); OpenGL/GBM pelo mesa-dri; Vulkan pelo
  vulkan-loader + mesa-vulkan-radeon / mesa-vulkan-intel.
- NVIDIA proprietário no Wayland: nvidia-drm com modeset ligado.
- Compositor Wayland precisa de um gerenciador de seat (elogind ou seatd, com
  o usuário no grupo _seatd), do D-Bus de sistema e do XDG_RUNTIME_DIR.
- Portais: xdg-desktop-portal + um backend (gtk, wlr, hyprland…).

Os nomes de pacotes só viram ação se existirem nos repositórios (xbps-query -R).
"""

import grp
import os
import pwd
import re

from ..util import read_file, run, running_processes
from . import packages as pkgs
from .registry import Tool

FABRICANTE = {"10de": "nvidia", "1002": "amd", "1022": "amd", "8086": "intel",
              "1af4": "virtio", "1234": "qemu", "15ad": "vmware", "80ee": "virtualbox"}
FIRMWARE = {"amd": "linux-firmware-amd", "intel": "linux-firmware-intel"}
VULKAN = {"amd": "mesa-vulkan-radeon", "intel": "mesa-vulkan-intel"}
PACOTES = ["mesa-dri", "vulkan-loader", "mesa-vulkan-radeon", "mesa-vulkan-intel",
           "linux-firmware-amd", "linux-firmware-intel", "elogind", "seatd", "dbus",
           "xdg-desktop-portal", "xdg-desktop-portal-gtk", "xdg-desktop-portal-wlr",
           "xdg-desktop-portal-hyprland", "turnstile"]


def _gpus():
    r = run(["lspci", "-nnk", "-d", "::03xx"], timeout=10)
    if r["rc"] != 0 or not r["out"].strip():
        r = run(["lspci", "-nnk"], timeout=10)
    gpus, atual = [], None
    for linha in r["out"].splitlines():
        if linha and not linha[0].isspace():
            atual = None
            if re.search(r"\[03[0-9a-f]{2}\]", linha) or re.search(r"VGA|3D|Display", linha):
                m = re.search(r"\[([0-9a-f]{4}):([0-9a-f]{4})\]", linha)
                nome = linha.split(": ", 1)[-1]
                atual = {"slot": linha.split()[0], "name": re.sub(r"\s*\[[0-9a-f:]+\]", "", nome)[:90],
                         "vendor": FABRICANTE.get(m.group(1), m.group(1)) if m else "?",
                         "driver": "", "modules": []}
                gpus.append(atual)
        elif atual is not None:
            l = linha.strip()
            if l.startswith("Kernel driver in use:"):
                atual["driver"] = l.split(":", 1)[1].strip()
            elif l.startswith("Kernel modules:"):
                atual["modules"] = [x.strip() for x in l.split(":", 1)[1].split(",")]
    return gpus


def _instalados():
    r = run(["xbps-query", "-l"], timeout=20)
    nomes = set()
    for linha in r["out"].splitlines():
        p = linha.split()
        if len(p) >= 2:
            nomes.add(pkgs._nome(p[1]))
    return nomes


def _runtime_dir():
    d = os.environ.get("XDG_RUNTIME_DIR", "")
    info = {"path": d, "exists": False, "owner_ok": None, "mode": ""}
    if d and os.path.isdir(d):
        st = os.stat(d)
        info.update(exists=True, owner_ok=st.st_uid == os.getuid(), mode=oct(st.st_mode & 0o777))
    return info


def _no_grupo(grupo):
    try:
        g = grp.getgrnam(grupo)
    except KeyError:
        return None
    usuario = pwd.getpwuid(os.getuid()).pw_name
    return usuario in g.gr_mem or os.getgid() == g.gr_gid or g.gr_gid in os.getgroups()


def t_status():
    procs = running_processes()
    inst = _instalados()
    d = {"gpus": _gpus(),
         "packages": {p: p in inst for p in PACOTES},
         "nvidia_packages": sorted(p for p in inst if re.fullmatch(r"nvidia\d*", p)),
         "nvidia_modeset": (read_file("/sys/module/nvidia_drm/parameters/modeset") or "").strip() or None,
         "session": {k: os.environ.get(k, "") for k in (
             "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XDG_CURRENT_DESKTOP",
             "DESKTOP_SESSION", "DBUS_SESSION_BUS_ADDRESS")},
         "runtime_dir": _runtime_dir(),
         "seat": {"elogind": "elogind-daemon" in procs, "seatd": "seatd" in procs,
                  "turnstiled": "turnstiled" in procs},
         "dbus_system": "dbus-daemon" in procs and os.path.exists("/run/dbus/system_bus_socket"),
         "portal_running": any(p.startswith("xdg-desktop-por") for p in procs),
         "in_seatd_group": _no_grupo("_seatd"),
         "compositor": sorted(p for p in procs if p in (
             "Hyprland", "sway", "river", "labwc", "wayfire", "niri", "mango", "dwl", "hyprland",
             "kwin_wayland", "gnome-shell", "weston", "Xorg", "X", "Xwayland"))}
    d["graphical"] = bool(d["session"]["WAYLAND_DISPLAY"] or d["session"]["DISPLAY"])
    return d


def c_status(state=None, cfg=None):
    s = t_status()
    g = s["gpus"]
    sem = [x["name"] for x in g if not x["driver"]]
    s["summary"] = (", ".join(f"{x['vendor']}: {x['driver'] or 'sem driver'}" for x in g)
                    or "nenhuma GPU encontrada pelo lspci")
    s["status"] = "fail" if sem else "ok"
    return s


STEPS = [("graphics.c_status", "Verificando vídeo e sessão gráfica", "graphics")]
KEYWORDS = ["video", "placa de video", "gpu", "driver de video", "nvidia", "radeon", "amdgpu",
            "mesa", "vulkan", "wayland", "hyprland", "compositor", "tela preta", "tela piscando",
            "portal", "compartilhar tela", "screenshare", "xwayland", "opengl", "vaapi",
            "aceleracao", "seatd", "elogind", "xdg_runtime_dir", "sddm", "sessao grafica"]


def _achado(code, sev, title, detail="", sug=None):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": "graphics",
            "confirmed": True, "suggestions": sug or []}


def analyze(state, reg):
    achados, acoes = [], []
    s = state.get("graphics", {})
    if not s:
        return achados, acoes
    pk = s["packages"]
    faltam = []            # pacotes que resolveriam algo (só entram se existirem no repositório)

    def acao(tool, args, reason, fixes):
        try:
            a = reg.make_action(tool, args, reason=reason, fixes=fixes)
            if a.id not in {x.id for x in acoes}:
                acoes.append(a)
        except ValueError:
            pass

    vendors = {x["vendor"] for x in s["gpus"]}
    for x in s["gpus"]:
        if not x["driver"]:
            achados.append(_achado(f"gpu_no_driver:{x['slot']}", "erro",
                                   f"A placa de vídeo está sem driver: {x['name']}",
                                   "Nenhum driver do kernel assumiu a GPU "
                                   f"(módulos possíveis: {', '.join(x['modules']) or '?'}).",
                                   ["lspci -k -d ::03xx", "dmesg | grep -iE 'drm|amdgpu|i915|nouveau|nvidia'"]))
    for v in ("amd", "intel"):
        if v in vendors:
            if not pk.get(FIRMWARE[v]):
                achados.append(_achado(f"fw_{v}", "aviso", f"Falta o firmware da GPU ({FIRMWARE[v]})",
                                       "O Void Handbook pede o firmware do fabricante para o driver da GPU."))
                faltam.append((FIRMWARE[v], f"fw_{v}"))
            if not pk.get(VULKAN[v]) or not pk.get("vulkan-loader"):
                achados.append(_achado(f"vulkan_{v}", "info", "Vulkan não está completo",
                                       f"Para Vulkan: vulkan-loader + {VULKAN[v]}."))
                for p in ("vulkan-loader", VULKAN[v]):
                    if not pk.get(p):
                        faltam.append((p, f"vulkan_{v}"))
    precisa_mesa = vendors & {"amd", "intel", "virtio", "qemu", "vmware"} or \
        any(x["driver"] == "nouveau" for x in s["gpus"])
    if precisa_mesa and not pk.get("mesa-dri"):
        achados.append(_achado("no_mesa", "erro", "O mesa-dri não está instalado",
                               "Compositores Wayland precisam do GBM do mesa-dri (Void Handbook)."))
        faltam.append(("mesa-dri", "no_mesa"))
    if any(x["driver"] == "nvidia" for x in s["gpus"]) and s["nvidia_modeset"] not in ("Y", "1"):
        achados.append(_achado("nvidia_modeset", "aviso", "NVIDIA sem modeset (Wayland precisa)",
                               "O módulo nvidia-drm está com modeset desligado.",
                               ["Adicione nvidia-drm.modeset=1 à linha do kernel (GRUB: "
                                "GRUB_CMDLINE_LINUX_DEFAULT em /etc/default/grub; depois update-grub)"]))

    if not s["dbus_system"]:
        achados.append(_achado("no_dbus", "erro", "O D-Bus de sistema não está rodando",
                               "Sessão gráfica, elogind, portais e Bluetooth dependem dele."))
        acao("service.enable", {"name": "dbus"}, "D-Bus de sistema", ["no_dbus"])
    seat = s["seat"]
    if not (seat["elogind"] or seat["seatd"]):
        sev = "erro" if s["graphical"] or s["compositor"] else "aviso"
        achados.append(_achado("no_seat", sev, "Nenhum gerenciador de seat rodando (elogind ou seatd)",
                               "Compositores Wayland exigem elogind ou seatd (Void Handbook)."))
        if pk.get("seatd"):
            acao("service.enable", {"name": "seatd"}, "gerenciador de seat", ["no_seat"])
        elif pk.get("elogind"):
            acao("service.enable", {"name": "elogind"}, "gerenciador de sessão", ["no_seat"])
        else:
            faltam.append(("elogind", "no_seat"))
    if seat["seatd"] and not seat["elogind"] and s["in_seatd_group"] is False:
        achados.append(_achado("seatd_group", "aviso", "Seu usuário não está no grupo _seatd",
                               "Com o seatd, usuários comuns precisam do grupo _seatd."))
        acao("user.add_group", {"group": "_seatd"}, "permissão para o seatd", ["seatd_group"])

    if s["graphical"]:
        rd = s["runtime_dir"]
        if not rd["path"] or not rd["exists"]:
            achados.append(_achado("no_runtime_dir", "erro", "XDG_RUNTIME_DIR ausente",
                                   "Sem ele o Wayland não cria o socket; elogind ou turnstile o criam."))
        elif rd["owner_ok"] is False:
            achados.append(_achado("runtime_dir_owner", "erro",
                                   f"{rd['path']} não pertence ao seu usuário"))
        if not s["session"]["DBUS_SESSION_BUS_ADDRESS"]:
            achados.append(_achado("no_session_bus", "aviso", "Sessão sem D-Bus de usuário",
                                   "Portais, notificações e vários apps precisam do D-Bus da sessão.",
                                   ["Inicie o compositor com dbus-run-session (ou por um display manager)"]))
        if not pk.get("xdg-desktop-portal"):
            achados.append(_achado("no_portal", "info", "Portais XDG não instalados",
                                   "Sem eles: seletor de arquivos de apps Flatpak, compartilhar tela e "
                                   "capturas podem falhar."))
            faltam.append(("xdg-desktop-portal", "no_portal"))
            desk = (s["session"]["XDG_CURRENT_DESKTOP"] or "").lower()
            back = ["xdg-desktop-portal-hyprland"] if "hyprland" in desk else ["xdg-desktop-portal-wlr"]
            faltam += [(b, "no_portal") for b in back + ["xdg-desktop-portal-gtk"]]
    else:
        achados.append(_achado("not_graphical", "info", "Fora da sessão gráfica",
                               "Rodando fora da sessão (TTY/SSH): as checagens da sessão Wayland "
                               "foram puladas."))

    # instala só o que existe nos repositórios configurados
    por_fix, vistos = {}, set()
    for p, fix in faltam:
        if p in vistos:
            continue
        vistos.add(p)
        if pkgs.in_repo(p):
            por_fix.setdefault(fix, []).append(p)
    for fix, nomes in por_fix.items():
        acao("pkg.install", {"packages": nomes}, "instala o que falta (" + fix + ")", [fix])

    if not any(a["severity"] in ("erro", "aviso") for a in achados):
        g = ", ".join(f"{x['vendor']} ({x['driver']})" for x in s["gpus"]) or "?"
        achados.insert(0, _achado("graphics_ok", "ok", "Vídeo e sessão sem problemas",
                                  f"GPU: {g}. Sessão: {s['session']['XDG_SESSION_TYPE'] or '?'} "
                                  f"{' '.join(s['compositor'])}".strip()))
    return achados, acoes


def register(reg):
    reg.register(Tool("graphics.status", "Verificando vídeo e sessão gráfica",
                      "Vídeo e sessão Wayland: GPUs e driver em uso (lspci -k), pacotes mesa/vulkan/"
                      "firmware/nvidia, modeset da NVIDIA, variáveis da sessão (XDG_*, WAYLAND_DISPLAY, "
                      "D-Bus), XDG_RUNTIME_DIR, elogind/seatd, portais, compositor rodando.",
                      t_status, domain="graphics"))


def register_checks(reg):
    reg.register(Tool("graphics.c_status", STEPS[0][1], STEPS[0][1], c_status,
                      domain="graphics", llm=False, internal=True))
