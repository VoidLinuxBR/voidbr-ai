# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/bluetooth.py - Bluetooth (bluez)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Bluetooth no VoidBR (Void Handbook): pacote bluez, serviços bluetoothd e
dbus habilitados, usuário no grupo bluetooth, controlador sem bloqueio rfkill.
Áudio Bluetooth com PipeWire precisa do libspa-bluetooth."""

import grp
import os
import re

from ..util import read_file, read_int, run, running_processes, which
from . import services as svc
from .privileged import run_helper, run_user
from .registry import Tool


def _rfkill():
    itens = []
    base = "/sys/class/rfkill"
    try:
        nomes = sorted(os.listdir(base))
    except OSError:
        return itens
    for n in nomes:
        if (read_file(f"{base}/{n}/type") or "").strip() == "bluetooth":
            itens.append({"name": (read_file(f"{base}/{n}/name") or "").strip(),
                          "soft": read_int(f"{base}/{n}/soft") == 1,
                          "hard": read_int(f"{base}/{n}/hard") == 1})
    return itens


def _no_grupo():
    try:
        g = grp.getgrnam("bluetooth")
    except KeyError:
        return None
    return g.gr_gid in os.getgroups()


def t_status():
    try:
        adaptadores = sorted(os.listdir("/sys/class/bluetooth"))
    except OSError:
        adaptadores = []
    procs = running_processes()
    d = {
        "adapters": [a for a in adaptadores if a.startswith("hci")],
        "rfkill": _rfkill(),
        "bluez_installed": bool(which("bluetoothctl")),
        "service": svc.status("bluetoothd", procs),
        "user_in_group": _no_grupo(),
        "powered": None,
        "paired": [],
    }
    if d["bluez_installed"] and d["service"]["running"]:
        r = run(["bluetoothctl", "show"], timeout=6)
        m = re.search(r"Powered:\s*(yes|no)", r["out"])
        if m:
            d["powered"] = m.group(1) == "yes"
        r = run(["bluetoothctl", "devices", "Paired"], timeout=6)
        d["paired"] = [l.split(" ", 2)[-1] for l in r["out"].splitlines() if l.startswith("Device")][:20]
    return d


def a_unblock(on_line=None):
    return run_helper("rfkill-unblock", "bluetooth", timeout=30, on_line=on_line)


def a_power_on(on_line=None):
    return run_user(["bluetoothctl", "power", "on"], timeout=15)


def _v_unblock():
    b = [r for r in _rfkill() if r["soft"]]
    return not b, "Bluetooth desbloqueado" if not b else "continua bloqueado"


def _v_power():
    p = t_status()["powered"]
    return bool(p), "controlador ligado" if p else "controlador continua desligado"


def c_status(state=None, cfg=None):
    s = t_status()
    if not s["adapters"]:
        s.update(summary="nenhum adaptador Bluetooth", status="info")
    elif not s["service"]["running"]:
        s.update(summary="bluetoothd não está rodando", status="warn")
    else:
        s.update(summary=f"{len(s['adapters'])} adaptador(es), "
                 + ("ligado" if s["powered"] else "desligado"),
                 status="ok" if s["powered"] else "warn")
    return s


STEPS = [("bluetooth.c_status", "Verificando o Bluetooth", "bluetooth")]
KEYWORDS = ["bluetooth", "bluez", "bluetoothctl", "pareamento", "parear", "fone bluetooth", "bt"]


def _achado(code, sev, title, detail="", sug=None):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": "bluetooth",
            "confirmed": True, "suggestions": sug or []}


def analyze(state, reg):
    achados, acoes = [], []

    def acao(tool, args, reason, fixes):
        try:
            acoes.append(reg.make_action(tool, args, reason=reason, fixes=fixes))
        except ValueError:
            pass

    s = state.get("bluetooth", {})
    if not s:
        return achados, acoes
    if not s["adapters"]:
        achados.append(_achado("bt_no_adapter", "info", "Nenhum adaptador Bluetooth encontrado",
                               "Sem controlador Bluetooth (ou sem driver/firmware para ele)."))
        return achados, acoes
    if not s["bluez_installed"]:
        achados.append(_achado("bt_no_bluez", "erro", "O bluez não está instalado"))
        acao("pkg.install", {"packages": ["bluez"]}, "pacote do Bluetooth", ["bt_no_bluez"])
    if any(r["hard"] for r in s["rfkill"]):
        achados.append(_achado("bt_rfkill_hard", "erro", "Bluetooth bloqueado por hardware",
                               "Chave física, tecla Fn ou opção na BIOS."))
    if any(r["soft"] for r in s["rfkill"]):
        achados.append(_achado("bt_rfkill_soft", "erro", "Bluetooth bloqueado por software (rfkill)"))
        acao("bluetooth.unblock", {}, "rádio Bluetooth bloqueado", ["bt_rfkill_soft"])
    sv = s["service"]
    if s["bluez_installed"] and not sv["enabled"]:
        achados.append(_achado("bt_service_off", "erro", "O serviço bluetoothd não está habilitado"))
        acao("service.enable", {"name": "bluetoothd"}, "serviço do Bluetooth", ["bt_service_off"])
    elif sv["enabled"] and sv["running"] is False:
        achados.append(_achado("bt_service_down", "erro", "O bluetoothd está habilitado mas parado"))
        acao("service.start", {"name": "bluetoothd"}, "serviço do Bluetooth", ["bt_service_down"])
    if s["user_in_group"] is False:
        achados.append(_achado("bt_group", "aviso", "Seu usuário não está no grupo bluetooth",
                               "O Void Handbook pede o usuário no grupo bluetooth (depois, reinicie "
                               "a sessão).", ["sudo usermod -aG bluetooth $USER"]))
    if s["powered"] is False:
        achados.append(_achado("bt_off", "aviso", "O controlador Bluetooth está desligado"))
        acao("bluetooth.power_on", {}, "controlador desligado", ["bt_off"])
    if not achados:
        achados.append(_achado("bt_ok", "ok", "O Bluetooth está funcionando",
                               f"Pareados: {', '.join(s['paired']) or 'nenhum'}"))
    return achados, acoes


def register(reg):
    reg.register(Tool("bluetooth.status", "Verificando o Bluetooth",
                      "Estado do Bluetooth: adaptadores, rfkill, bluez instalado, serviço bluetoothd, "
                      "usuário no grupo bluetooth, controlador ligado e dispositivos pareados.",
                      t_status, domain="bluetooth"))
    reg.register(Tool("bluetooth.unblock", "Desbloquear o Bluetooth",
                      "Tira o bloqueio de software (rfkill) do Bluetooth.", a_unblock,
                      kind="action", domain="bluetooth", title="Desbloquear o Bluetooth (rfkill)",
                      preview=lambda: "rfkill unblock bluetooth  (via /sys/class/rfkill)",
                      verify=_v_unblock))
    reg.register(Tool("bluetooth.power_on", "Ligar o Bluetooth",
                      "Liga o controlador Bluetooth (bluetoothctl power on).", a_power_on,
                      kind="action", domain="bluetooth", root=False,
                      title="Ligar o controlador Bluetooth",
                      preview=lambda: "bluetoothctl power on", verify=_v_power))


def register_checks(reg):
    reg.register(Tool("bluetooth.c_status", STEPS[0][1], STEPS[0][1], c_status,
                      domain="bluetooth", llm=False, internal=True))
