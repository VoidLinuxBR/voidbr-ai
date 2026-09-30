# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/logs.py - erros recentes nos logs (dmesg e socklog)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Lê o log do kernel (dmesg) e o syslog do socklog (/var/log/socklog/*/current)
e resume os erros recentes, agrupando mensagens repetidas.

No Void o syslog vem do socklog-void (serviços socklog-unix e nanoklogd) e só o
root e o grupo socklog leem os logs (Void Handbook). O dmesg pode estar
restrito (kernel.dmesg_restrict=1): nesse caso o achado explica como liberar.
"""

import glob
import os
import re

from ..util import run
from . import packages as pkgs
from . import services as svc
from .registry import P, Tool

# o que é problema, com o peso (aviso = sério; info = vale olhar)
SERIOS = re.compile(r"segfault|general protection|i/o error|buffer i/o|oom-kill|out of memory|"
                    r"call trace|kernel bug|blocked for more than|hardware error|mce:|"
                    r"corrupt|read-only file system|ext4-fs error|btrfs.*(error|corrupt)|"
                    r"nvme.*(timeout|reset)|ata\d+.*(failed|error)|link is not ready.*fail", re.I)
ERROS = re.compile(r"\b(error|err|fail(ed|ure)?|fatal|critical|crit|panic|denied|unable to|"
                   r"cannot|can't|timed? ?out|firmware: failed)\b", re.I)
IGNORAR = re.compile(r"acpi (error|bios error).*(ae_not_found|ae_already_exists)|"
                     r"bluetooth: hci0: (unexpected|failed to read codec)|"
                     r"platform regulatory\.0: direct firmware load for regulatory|"
                     r"usb .*: device descriptor read/64, error -71", re.I)


def _normalizar(msg):
    """Tira o que varia (datas, números, endereços) para agrupar repetidas."""
    m = re.sub(r"^\S*\d{4}-\d{2}-\d{2}T[\d:.]+\S*\s+", "", msg)       # data do socklog
    m = re.sub(r"^\[[^\]]*\]\s*", "", m)                               # [tempo] do dmesg
    m = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{8,}\b", "#", m, flags=re.I)
    m = re.sub(r"\d+", "#", m)
    return m.strip()[:160]


def _dmesg():
    r = run(["dmesg", "--time-format=reltime", "--nopager", "--level", "emerg,alert,crit,err,warn"],
            timeout=10)
    if r["rc"] != 0:
        return None, "sem permissão para o dmesg (kernel.dmesg_restrict=1)"
    return r["out"].splitlines()[-600:], ""


def _socklog():
    linhas, sem_perm = [], []
    arquivos = sorted(glob.glob("/var/log/socklog/*/current"))
    for f in arquivos:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                origem = os.path.basename(os.path.dirname(f))
                linhas += [f"{origem}: {l.rstrip()}" for l in fh.readlines()[-800:]]
        except PermissionError:
            sem_perm.append(f)
    return linhas, sem_perm, bool(arquivos) or os.path.isdir("/var/log/socklog")


def _agrupar(linhas, fonte):
    grupos = {}
    for l in linhas:
        if IGNORAR.search(l):
            continue
        serio = bool(SERIOS.search(l))
        if not serio and not ERROS.search(l):
            continue
        chave = _normalizar(l.split(": ", 1)[-1] if fonte == "socklog" else l)
        g = grupos.setdefault(chave, {"message": l.strip()[:220], "count": 0, "serious": serio,
                                      "source": fonte})
        g["count"] += 1
        g["message"] = l.strip()[:220]         # guarda a ocorrência mais recente
    return list(grupos.values())


def t_summary(limit=12):
    d = {"dmesg_restricted": False, "socklog_installed": False, "socklog_readable": True,
         "socklog_services": {}, "problems": []}
    dm, erro = _dmesg()
    if dm is None:
        d["dmesg_restricted"] = True
        d["dmesg_note"] = erro
    else:
        d["problems"] += _agrupar(dm, "dmesg")
    sl, sem_perm, existe = _socklog()
    d["socklog_installed"] = existe or pkgs.installed("socklog-void")
    d["socklog_services"] = {n: svc.status(n)["enabled"] for n in ("socklog-unix", "nanoklogd")}
    if sem_perm:
        d["socklog_readable"] = False
        d["socklog_note"] = f"sem permissão para {len(sem_perm)} log(s): grupo socklog"
    d["problems"] += _agrupar(sl, "socklog")
    d["problems"].sort(key=lambda g: (not g["serious"], -g["count"]))
    d["problems"] = d["problems"][:int(limit)]
    return d


def c_summary(state=None, cfg=None):
    d = t_summary()
    serios = [g for g in d["problems"] if g["serious"]]
    d["summary"] = (f"{len(serios)} erro(s) sério(s), {len(d['problems']) - len(serios)} outro(s)"
                    if d["problems"] else "nenhum erro recente encontrado")
    d["status"] = "warn" if serios else "ok"
    return d


STEPS = [("logs.c_summary", "Procurando erros nos logs (dmesg e socklog)", "logs")]
KEYWORDS = ["log", "logs", "dmesg", "socklog", "syslog", "segfault", "crash", "travamento",
            "travamentos", "kernel panic", "erros do sistema", "mensagens de erro"]


def _achado(code, sev, title, detail="", sug=None):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": "logs",
            "confirmed": True, "suggestions": sug or []}


def analyze(state, reg):
    achados, acoes = [], []
    d = state.get("logs", {})
    if not d:
        return achados, acoes

    def acao(tool, args, reason, fixes):
        try:
            acoes.append(reg.make_action(tool, args, reason=reason, fixes=fixes))
        except ValueError:
            pass

    for i, g in enumerate(d["problems"]):
        vezes = f" ({g['count']}x)" if g["count"] > 1 else ""
        achados.append(_achado(f"log:{i}:{_normalizar(g['message'])[:60]}",
                               "aviso" if g["serious"] else "info",
                               f"[{g['source']}]{vezes} {g['message'][:140]}"))
    if d["dmesg_restricted"]:
        achados.append(_achado("dmesg_restricted", "info", "O dmesg está restrito para usuários",
                               "Com kernel.dmesg_restrict=1 só o root lê o log do kernel.",
                               ["sudo dmesg --level=err,warn | tail -50"]))
    if not d["socklog_installed"]:
        achados.append(_achado("no_socklog", "info", "Sem syslog (socklog não instalado)",
                               "O Void não traz syslog por padrão; o recomendado é o socklog-void "
                               "(serviços socklog-unix e nanoklogd)."))
        acao("pkg.install", {"packages": ["socklog-void"]}, "logs do sistema", ["no_socklog"])
    else:
        for n, hab in d["socklog_services"].items():
            if not hab:
                achados.append(_achado(f"socklog_off:{n}", "info", f"O serviço {n} não está habilitado",
                                       "Sem ele o socklog não grava os logs."))
                acao("service.enable", {"name": n}, "logs do sistema", [f"socklog_off:{n}"])
        if not d["socklog_readable"]:
            achados.append(_achado("socklog_perm", "info", "Sem permissão para ler os logs do socklog",
                                   "Só o root e o grupo socklog leem /var/log/socklog."))
            acao("user.add_group", {"group": "socklog"}, "ler os logs sem sudo", ["socklog_perm"])
    if not any(a["code"].startswith("log:") for a in achados):
        achados.insert(0, _achado("logs_ok", "ok", "Nenhum erro recente nos logs",
                                  "dmesg e socklog sem erros nas últimas linhas."
                                  if not d["dmesg_restricted"] else "socklog sem erros recentes."))
    return achados, acoes


def register(reg):
    reg.register(Tool("logs.summary", "Procurando erros nos logs",
                      "Resumo dos erros recentes do kernel (dmesg) e do syslog (socklog), com as "
                      "mensagens repetidas agrupadas e contadas.", t_summary, domain="logs",
                      params={"limit": P("integer", "quantos grupos", minimum=3, maximum=30)}))


def register_checks(reg):
    reg.register(Tool("logs.c_summary", STEPS[0][1], STEPS[0][1], c_summary,
                      domain="logs", llm=False, internal=True))
