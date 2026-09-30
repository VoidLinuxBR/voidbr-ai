# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/services.py - serviços runit
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Serviços runit (VoidBR não usa systemd).

    disponível   /etc/sv/<nome> existe (o pacote está instalado)
    habilitado   /var/service/<nome> existe (link para /etc/sv/<nome>)
    rodando      `sv status` diz run:  — ou, sem permissão, o processo existe

O `sv status` precisa ler /var/service/<nome>/supervise, que normalmente só
o root lê. Como usuário comum, o processo é procurado em /proc pelo nome do
programa que o /etc/sv/<nome>/run executa.
"""

import glob
import os
import re
import shlex
import time

from ..util import read_file, running_processes, run
from .privileged import run_helper
from .registry import P, Tool

SV_DIR = "/etc/sv"
SERVICE_DIR = "/var/service"
RE_NOME = r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}"

# nome do serviço -> nome do processo, quando o run não deixa óbvio
PROCESSO = {
    "NetworkManager": "NetworkManager", "iwd": "iwd", "wpa_supplicant": "wpa_supplicant",
    "dhcpcd": "dhcpcd", "connmand": "connmand", "dbus": "dbus-daemon", "udevd": "udevd",
    "bluetoothd": "bluetoothd", "elogind": "elogind-daemon", "sshd": "sshd",
    "cronie": "crond", "ollama": "ollama",
}

# serviços cujo parar/desabilitar/reiniciar derruba algo importante
RISCO = {
    "dbus": "Parar o dbus derruba a sessão gráfica e vários serviços.",
    "elogind": "Parar o elogind pode encerrar a sua sessão.",
    "seatd": "Parar o seatd derruba a sessão gráfica (Wayland).",
    "udevd": "Sem o udevd, dispositivos novos deixam de ser configurados.",
    "sddm": "Isso encerra a tela de login e a sessão gráfica atual.",
    "lightdm": "Isso encerra a tela de login e a sessão gráfica atual.",
    "gdm": "Isso encerra a tela de login e a sessão gráfica atual.",
    "greetd": "Isso encerra a tela de login e a sessão gráfica atual.",
    "sshd": "Conexões SSH remotas vão cair.",
    "NetworkManager": "A conexão de rede cai por alguns segundos.",
}

_PULAR = {"exec", "env", "nice", "ionice", "setsid", "2>&1", "1>&2", "--"}
_CHPST_ARG = {"-u", "-U", "-b", "-e", "-/", "-n", "-l", "-L", "-m", "-d", "-o", "-p",
              "-f", "-c", "-r", "-t"}


def programa(nome):
    """Nome do processo que o serviço executa (lido do /etc/sv/<nome>/run)."""
    if nome in PROCESSO:
        return PROCESSO[nome]
    if nome.startswith("dhcpcd-"):
        return "dhcpcd"
    if nome.startswith("agetty-"):
        return "agetty"
    texto = read_file(os.path.join(SV_DIR, nome, "run")) or ""
    linhas = [l.strip() for l in texto.splitlines() if l.strip().startswith("exec")]
    if not linhas:
        return ""
    try:
        tokens = shlex.split(linhas[-1], comments=True)
    except ValueError:
        return ""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _PULAR or "=" in t.split("/")[0] or t.startswith(("2>", ">")):
            i += 1
        elif os.path.basename(t) in ("chpst", "vlogger", "sudo"):
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in _CHPST_ARG else 1
        else:
            prog = os.path.basename(t)
            return "" if "$" in prog else prog[:15]
    return ""


def status(name, procs=None):
    st = {
        "name": name,
        "available": os.path.isdir(os.path.join(SV_DIR, name)),
        "enabled": os.path.exists(os.path.join(SERVICE_DIR, name)),
        "running": False,
        "state": "",
        "source": "",
    }
    if st["enabled"]:
        r = run(["sv", "status", os.path.join(SERVICE_DIR, name)], timeout=5)
        saida = (r["out"] or r["err"]).strip()
        if saida.startswith("run:"):
            st.update(running=True, state=saida, source="sv")
        elif saida.startswith(("down:", "finish:")):
            st.update(running=False, state=saida, source="sv")
    if not st["source"]:
        comm = programa(name)
        if comm:
            procs = procs if procs is not None else running_processes()
            st.update(running=comm in procs, source="proc",
                      state=f"processo {comm} " + ("em execução" if comm in procs else "não encontrado"))
        else:
            st.update(running=None, source="?", state="não foi possível saber (sem permissão para o sv)")
    return st


def list_enabled():
    try:
        return sorted(os.listdir(SERVICE_DIR))
    except OSError:
        return []


def list_available():
    try:
        return sorted(d for d in os.listdir(SV_DIR) if os.path.isdir(os.path.join(SV_DIR, d)))
    except OSError:
        return []


# ---------------------------------------------------------------------------
# ferramentas de leitura
# ---------------------------------------------------------------------------

def t_status(name):
    return status(name)


def t_list(only_enabled=False):
    procs = running_processes()
    hab = set(list_enabled())
    itens = []
    for n in list_available():
        if only_enabled and n not in hab:
            continue
        if n in hab:
            s = status(n, procs)
            itens.append({"name": n, "enabled": True, "running": s["running"]})
        else:
            itens.append({"name": n, "enabled": False})
    return {"services": itens, "enabled": len(hab), "available": len(itens)}


def _log_dir(nome):
    texto = read_file(os.path.join(SV_DIR, nome, "log", "run")) or ""
    m = re.search(r"svlogd\s+(?:-\S+\s+)*(\S+)", texto)
    return m.group(1) if m else ""


def t_log(name, lines=40):
    """Últimas linhas de log do serviço (svlogd próprio ou socklog)."""
    fontes = []
    d = _log_dir(name)
    if d:
        fontes.append(os.path.join(d, "current"))
    fontes += sorted(glob.glob("/var/log/socklog/*/current"))
    saida, erros = [], []
    for f in fontes:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                linhas = fh.readlines()[-4000:]
        except PermissionError:
            erros.append(f"{f}: sem permissão (o usuário precisa estar no grupo socklog)")
            continue
        except OSError:
            continue
        if f.startswith("/var/log/socklog"):
            linhas = [l for l in linhas if name.lower() in l.lower()]
        saida += [l.rstrip() for l in linhas[-lines:]]
        if saida:
            break
    r = {"name": name, "lines": saida[-lines:]}
    if not saida:
        r["note"] = "nenhuma linha encontrada" + (f"; {'; '.join(erros)}" if erros else "") + \
                    ("" if os.path.isdir("/var/log/socklog") else
                     "; o socklog não está instalado/habilitado (socklog-void)")
    return r


# ---------------------------------------------------------------------------
# ações (via helper root, só com confirmação)
# ---------------------------------------------------------------------------

def _existe(args):
    if not os.path.isdir(os.path.join(SV_DIR, args["name"])):
        return f"o serviço {args['name']} não existe em {SV_DIR}"
    return None


def _habilitado(args):
    return _existe(args) or (None if os.path.exists(os.path.join(SERVICE_DIR, args["name"]))
                             else f"{args['name']} não está habilitado em {SERVICE_DIR}")


def _acao(verbo):
    def f(name, on_line=None):
        return run_helper("service-" + verbo, name, timeout=60, on_line=on_line)
    return f


def _esperar(name, quer_rodando, segundos=8):
    st = status(name)
    for _ in range(int(segundos * 2)):
        if st["running"] is quer_rodando:
            break
        time.sleep(0.5)
        st = status(name)
    if st["running"] is None:
        # sem permissão e sem saber o processo: pergunta ao helper (o pkexec já autenticou)
        r = run_helper("service-status", name, timeout=15)
        rodando = r["out"].startswith("run:")
        return rodando == quer_rodando, r["out"] or "estado desconhecido"
    return st["running"] is quer_rodando, st["state"]


def _verif_rodando(name):
    ok, estado = _esperar(name, True)
    return ok, (f"{name} está rodando" if ok else f"{name} não está rodando ({estado})")


def _verif_parado(name):
    ok, estado = _esperar(name, False)
    return ok, (f"{name} está parado" if ok else f"{name} continua rodando ({estado})")


def _verif_desab(name):
    ok = not os.path.exists(os.path.join(SERVICE_DIR, name))
    return ok, (f"{name} desabilitado" if ok else f"{name} continua em {SERVICE_DIR}")


def _risco(verbo):
    def f(args):
        return RISCO.get(args.get("name", ""), "")
    return f


PREVIEW = {
    "start": lambda name: f"sv start {name}",
    "stop": lambda name: f"sv stop {name}",
    "restart": lambda name: f"sv restart {name}",
    "enable": lambda name: f"ln -s /etc/sv/{name} /var/service/  &&  sv start {name}",
    "disable": lambda name: f"sv stop {name}  &&  rm /var/service/{name}",
}

TITULO = {"start": "Iniciar o serviço {name}", "stop": "Parar o serviço {name}",
          "restart": "Reiniciar o serviço {name}", "enable": "Habilitar e iniciar o serviço {name}",
          "disable": "Desabilitar o serviço {name}"}


def register(reg):
    nome = {"name": P("string", "nome do serviço runit (diretório em /etc/sv)", pattern=RE_NOME)}
    reg.register(Tool("service.status", "Consultando serviço",
                      "Estado de um serviço runit: instalado (/etc/sv), habilitado (/var/service) "
                      "e rodando.", t_status, domain="services", params=nome, required=["name"]))
    reg.register(Tool("service.list", "Listando serviços",
                      "Lista os serviços runit instalados, quais estão habilitados e rodando.",
                      t_list, domain="services",
                      params={"only_enabled": P("boolean", "só os habilitados")}))
    reg.register(Tool("service.log", "Lendo o log do serviço",
                      "Últimas linhas de log de um serviço (svlogd do serviço ou socklog).",
                      t_log, domain="services", params={
                          **nome, "lines": P("integer", "quantas linhas", minimum=5, maximum=200)},
                      required=["name"]))
    desc = {"start": "Inicia um serviço runit habilitado",
            "stop": "Para um serviço runit (continua habilitado)",
            "restart": "Reinicia um serviço runit habilitado",
            "enable": "Habilita (link em /var/service) e inicia um serviço instalado",
            "disable": "Para e desabilita um serviço runit"}
    verif = {"start": _verif_rodando, "restart": _verif_rodando, "enable": _verif_rodando,
             "stop": _verif_parado, "disable": _verif_desab}
    for verbo, d in desc.items():
        reg.register(Tool(
            f"service.{verbo}", d, d, _acao(verbo), kind="action", domain="services",
            params=nome, required=["name"],
            check=_habilitado if verbo in ("start", "stop", "restart", "disable") else _existe,
            preview=PREVIEW[verbo], title=TITULO[verbo], verify=verif[verbo],
            risk_for=_risco(verbo) if verbo in ("stop", "disable", "restart") else None))


# ---------------------------------------------------------------------------
# check-up (sem LLM)
# ---------------------------------------------------------------------------

def c_enabled(state=None, cfg=None):
    procs = running_processes()
    sts = [status(n, procs) for n in list_enabled()]
    parados = [s["name"] for s in sts if s["running"] is False]
    if not sts:
        return {"services": [], "summary": "nenhum serviço habilitado em /var/service",
                "status": "info"}
    return {"services": sts,
            "summary": f"{len(sts)} habilitados" + (f", parados: {', '.join(parados)}" if parados else
                                                    ", todos rodando"),
            "status": "warn" if parados else "ok"}


STEPS = [("services.enabled", "Verificando serviços habilitados (runit)", "enabled")]
KEYWORDS = ["servico", "servicos", "service", "runit", "sv", "daemon", "inicializacao",
            "nao inicia", "nao sobe", "parado"]


def analyze(state, reg):
    achados, acoes = [], []
    for s in state.get("enabled", {}).get("services", []):
        if s["running"] is False:
            n = s["name"]
            confirmado = s["source"] == "sv"
            achados.append({
                "code": f"service_down:{n}", "severity": "aviso",
                "title": f"O serviço {n} está habilitado mas não está rodando",
                "detail": s["state"] + ("" if confirmado else
                                         " (detectado pela lista de processos; pode ser um serviço "
                                         "que roda e termina, como os de configuração)"),
                "step": "enabled", "confirmed": confirmado, "suggestions": [f"Log: voidbr-ai \"log do {n}\""]})
            try:
                acoes.append(reg.make_action("service.restart", {"name": n},
                                             reason=f"{n} habilitado e parado",
                                             fixes=[f"service_down:{n}"]))
            except ValueError:
                pass
    if not achados and state.get("enabled", {}).get("services"):
        achados.append({"code": "services_ok", "severity": "ok",
                        "title": "Todos os serviços habilitados estão rodando", "detail": "",
                        "step": "enabled", "confirmed": True, "suggestions": []})
    return achados, acoes


def register_checks(reg):
    reg.register(Tool("services.enabled", STEPS[0][1], "check-up dos serviços habilitados",
                      c_enabled, domain="services", llm=False, internal=True))
