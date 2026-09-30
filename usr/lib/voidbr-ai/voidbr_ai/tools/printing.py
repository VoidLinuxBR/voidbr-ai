# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/printing.py - impressoras (CUPS)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Impressão no VoidBR, segundo o Void Handbook (config/print):

- pacote cups + serviço cupsd habilitado; cups-filters (necessário até na
  impressão sem driver); usuário no grupo lpadmin para administrar;
- impressoras de rede modernas imprimem sem driver (IPP Everywhere); achar na
  rede: avahi + nss-mdns + serviço avahi-daemon;
- drivers: hplip (HP), brother-brlaser + foomatic-db(-nonfree) (Brother),
  epson-inkjet-printer-escpr (Epson), cnijfilter2 (Canon, repositório
  nonfree), gutenprint (vários);
- configurar: http://localhost:631, lpadmin, system-config-printer, hp-setup -i.

Detecção sem root: impressoras USB pelo /sys (classe de interface 07; o
protocolo 04 é IPP-USB, que imprime sem driver com o ipp-usb) e de rede pelo
driverless/ippfind (DNS-SD do avahi).
"""

import glob
import grp
import os
import pwd
import re

from ..util import read_file, run, which
from . import packages as pkgs
from . import services as svc
from .privileged import run_helper, run_user
from .registry import P, Tool

RE_NOME = r"[A-Za-z0-9_-]{1,64}"
RE_URI = r"ipps?://[][A-Za-z0-9._~:/?#@%+=,-]{1,200}"

# fabricante (USB idVendor ou nome) -> pacotes de driver (nomes conferidos no Void)
DRIVERS = {
    "hp": ["hplip"],
    "brother": ["brother-brlaser", "foomatic-db", "foomatic-db-nonfree"],
    "epson": ["epson-inkjet-printer-escpr"],
    "canon": ["cnijfilter2"],
    "samsung": ["splix"],
    "outro": ["gutenprint"],
}
VENDOR_USB = {"03f0": "hp", "04f9": "brother", "04b8": "epson", "04a9": "canon",
              "04e8": "samsung", "0924": "xerox", "043d": "lexmark", "0482": "kyocera",
              "04da": "panasonic", "04c5": "fujitsu", "0550": "xerox", "05ca": "ricoh"}


def _fabricante(texto):
    t = (texto or "").lower()
    for k in ("hp", "hewlett", "brother", "epson", "canon", "samsung", "xerox", "lexmark",
              "kyocera", "ricoh"):
        if re.search(rf"\b{k}", t):
            return "hp" if k == "hewlett" else k
    return "outro"


def _usb():
    """Impressoras USB conectadas (interface USB de classe 07 = impressora)."""
    achadas = {}
    for intf in glob.glob("/sys/bus/usb/devices/*:*"):
        if (read_file(os.path.join(intf, "bInterfaceClass")) or "").strip() != "07":
            continue
        dev = os.path.dirname(os.path.realpath(intf))
        proto = (read_file(os.path.join(intf, "bInterfaceProtocol")) or "").strip()
        d = achadas.setdefault(dev, {
            "vendor_id": (read_file(os.path.join(dev, "idVendor")) or "").strip(),
            "product_id": (read_file(os.path.join(dev, "idProduct")) or "").strip(),
            "manufacturer": (read_file(os.path.join(dev, "manufacturer")) or "").strip(),
            "product": (read_file(os.path.join(dev, "product")) or "").strip(),
            "ipp_usb": False})
        if proto == "04":
            d["ipp_usb"] = True
    res = []
    for d in achadas.values():
        d["vendor"] = VENDOR_USB.get(d["vendor_id"]) or _fabricante(d["manufacturer"])
        d["name"] = " ".join(x for x in (d["manufacturer"], d["product"]) if x) or \
            f"USB {d['vendor_id']}:{d['product_id']}"
        res.append(d)
    return res


def _rede(timeout=5):
    """Impressoras IPP na rede (sem driver), pelo DNS-SD do avahi."""
    uris = []
    if which("driverless"):
        r = run(["driverless"], timeout=timeout + 5)
        uris += [l.strip() for l in r["out"].splitlines() if re.match(r"ipps?://", l.strip())]
    if not uris and which("ippfind"):
        r = run(["ippfind", "-T", str(timeout)], timeout=timeout + 5)
        uris += [l.strip() for l in r["out"].splitlines() if re.match(r"ipps?://", l.strip())]
    vistos, res = set(), []
    for u in uris:
        if u in vistos:
            continue
        vistos.add(u)
        host = re.sub(r"^ipps?://([^/:]+).*", r"\1", u)
        nome = re.sub(r"\.local\.?$", "", host)
        res.append({"uri": u, "host": host, "name": nome, "vendor": _fabricante(nome)})
    return res


def _lpstat():
    """Impressoras configuradas no CUPS: nome, URI, estado, padrão e fila."""
    d = {"printers": [], "default": "", "jobs": [], "cups_reachable": False}
    if not which("lpstat"):
        return d
    r = run(["lpstat", "-v"], timeout=10)
    if r["rc"] == 0 or "no destinations" in (r["out"] + r["err"]).lower():
        d["cups_reachable"] = True
    uris = {}
    for l in r["out"].splitlines():
        m = re.match(r"device for (\S+):\s*(\S+)", l)
        if m:
            uris[m.group(1)] = m.group(2)
    r = run(["lpstat", "-p"], timeout=10)
    estado = {}
    for l in r["out"].splitlines():
        m = re.match(r"printer (\S+) (?:is )?(idle|now printing|disabled)", l)
        if m:
            estado[m.group(1)] = m.group(2)
    for nome, uri in uris.items():
        d["printers"].append({"name": nome, "uri": uri, "state": estado.get(nome, "?"),
                              "enabled": estado.get(nome) != "disabled"})
    m = re.search(r"system default destination:\s*(\S+)", run(["lpstat", "-d"], timeout=10)["out"])
    d["default"] = m.group(1) if m else ""
    r = run(["lpstat", "-o"], timeout=10)
    d["jobs"] = [l.split()[0] for l in r["out"].splitlines() if l.strip()][:50]
    return d


def _no_lpadmin():
    try:
        g = grp.getgrnam("lpadmin")
    except KeyError:
        return None
    usuario = pwd.getpwuid(os.getuid()).pw_name
    return usuario in g.gr_mem or g.gr_gid in os.getgroups()


def _nsswitch_mdns():
    t = read_file("/etc/nsswitch.conf") or ""
    linha = next((l for l in t.splitlines() if l.strip().startswith("hosts:")), "")
    return "mdns" in linha


def t_status(discover=True):
    inst = {p: pkgs.installed(p) for p in ("cups", "cups-filters", "avahi", "nss-mdns", "ipp-usb",
                                            "hplip", "gutenprint", "brother-brlaser", "foomatic-db",
                                            "epson-inkjet-printer-escpr", "cnijfilter2", "splix")}
    procs_svc = {n: svc.status(n) for n in ("cupsd", "avahi-daemon", "ipp-usb")}
    d = {"packages": inst,
         "services": {n: {"enabled": s["enabled"], "running": s["running"], "available": s["available"]}
                      for n, s in procs_svc.items()},
         "in_lpadmin": _no_lpadmin(),
         "nsswitch_mdns": _nsswitch_mdns(),
         "usb": _usb()}
    d.update(_lpstat())
    d["network"] = _rede() if discover and procs_svc["avahi-daemon"]["running"] else []
    return d


def t_discover():
    return {"usb": _usb(), "network": _rede(timeout=8)}


def c_status(state=None, cfg=None):
    d = t_status()
    n = len(d["printers"])
    achadas = len(d["usb"]) + len(d["network"])
    d["summary"] = (f"{n} configurada(s)" + (f", {achadas} encontrada(s)" if achadas else "")
                    if d["packages"]["cups"] else "CUPS não instalado")
    d["status"] = "ok" if d["packages"]["cups"] and d["services"]["cupsd"]["running"] else \
        ("warn" if d["packages"]["cups"] or achadas else "info")
    return d


# ---------------------------------------------------------------------------
# ações
# ---------------------------------------------------------------------------

def _nome_fila(texto):
    n = re.sub(r"[^A-Za-z0-9_-]+", "_", texto or "Impressora").strip("_")[:40]
    return n or "Impressora"


def a_add(name, uri, on_line=None):
    return run_helper("printer-add", name, uri, timeout=120, on_line=on_line)


def a_enable(name, on_line=None):
    return run_helper("printer-enable", name, timeout=60, on_line=on_line)


def a_cancel_jobs(name, on_line=None):
    return run_helper("printer-cancel-jobs", name, timeout=60, on_line=on_line)


def a_default(name, on_line=None):
    return run_user(["lpoptions", "-d", name], timeout=20)


def a_test(name, on_line=None):
    pagina = "/usr/share/cups/data/testprint"
    return run_user(["lp", "-d", name, "-t", "Página de teste do VoidBR AI", pagina], timeout=30)


def _existe_fila(args):
    if args["name"] not in {p["name"] for p in _lpstat()["printers"]}:
        return f"a impressora {args['name']} não está configurada no CUPS"
    return None


def _nova_fila(args):
    if args["name"] in {p["name"] for p in _lpstat()["printers"]}:
        return f"já existe uma impressora chamada {args['name']}"
    return None


def _v_add(name, uri):
    p = next((x for x in _lpstat()["printers"] if x["name"] == name), None)
    return bool(p), (f"{name} configurada ({p['state']})" if p else f"{name} não aparece no CUPS")


def _v_enable(name):
    p = next((x for x in _lpstat()["printers"] if x["name"] == name), None)
    ok = bool(p and p["enabled"])
    return ok, f"{name} ativa" if ok else f"{name} continua desativada"


def _v_jobs(name):
    j = [x for x in _lpstat()["jobs"] if x.startswith(name + "-")]
    return not j, "fila vazia" if not j else f"{len(j)} trabalho(s) ainda na fila"


def _v_default(name):
    r = run(["lpstat", "-d"], timeout=10)
    ok = name in r["out"]
    if not ok:     # o lpoptions -d grava o padrão do usuário (~/.cups/lpoptions)
        ok = name in (read_file(os.path.expanduser("~/.cups/lpoptions")) or "")
    return ok, f"{name} é a padrão" if ok else "a padrão não mudou"


def _v_test(name):
    return None, "página enviada: confira se saiu na impressora"


# ---------------------------------------------------------------------------
# regras
# ---------------------------------------------------------------------------

STEPS = [("printing.c_status", "Verificando impressoras (CUPS)", "printing")]
KEYWORDS = ["impressora", "impressoras", "imprimir", "impressao", "imprime", "cups", "toner",
            "fila de impressao", "nao imprime", "printer", "scanner multifuncional"]


def _achado(code, sev, title, detail="", sug=None):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": "printing",
            "confirmed": True, "suggestions": sug or []}


def analyze(state, reg):
    achados, acoes = [], []
    d = state.get("printing", {})
    if not d:
        return achados, acoes

    def acao(tool, args, reason, fixes):
        try:
            a = reg.make_action(tool, args, reason=reason, fixes=fixes)
            if a.id not in {x.id for x in acoes}:
                acoes.append(a)
        except ValueError:
            pass

    pk, sv = d["packages"], d["services"]
    configuradas = {p["uri"] for p in d["printers"]}
    usb, rede = d["usb"], d["network"]

    # CUPS -------------------------------------------------------------------
    if not pk["cups"]:
        sev = "erro" if usb or rede else "info"
        achados.append(_achado("no_cups", sev, "O CUPS (sistema de impressão) não está instalado",
                               "Sem ele não dá para imprimir. O Void Handbook pede cups e cups-filters."))
        acao("pkg.install", {"packages": ["cups", "cups-filters"]}, "sistema de impressão", ["no_cups"])
    else:
        if not pk["cups-filters"]:
            achados.append(_achado("no_cups_filters", "aviso", "Falta o cups-filters",
                                   "Necessário até para imprimir sem driver (Void Handbook)."))
            acao("pkg.install", {"packages": ["cups-filters"]}, "filtros do CUPS", ["no_cups_filters"])
        c = sv["cupsd"]
        if not c["enabled"]:
            achados.append(_achado("cupsd_off", "erro", "O serviço cupsd não está habilitado"))
            acao("service.enable", {"name": "cupsd"}, "serviço de impressão", ["cupsd_off"])
        elif c["running"] is False:
            achados.append(_achado("cupsd_down", "erro", "O cupsd está habilitado mas parado"))
            acao("service.restart", {"name": "cupsd"}, "serviço de impressão", ["cupsd_down"])
        if d["in_lpadmin"] is False:
            achados.append(_achado("lpadmin", "aviso", "Seu usuário não está no grupo lpadmin",
                                   "Precisa dele para administrar impressoras (ex: em "
                                   "http://localhost:631)."))
            acao("user.add_group", {"group": "lpadmin"}, "administrar impressoras", ["lpadmin"])

    # rede (avahi) -----------------------------------------------------------
    if not pk["avahi"] or not pk["nss-mdns"]:
        achados.append(_achado("no_avahi", "info", "Busca de impressoras na rede desligada",
                               "Para achar impressoras de rede sozinho: avahi + nss-mdns e o serviço "
                               "avahi-daemon (Void Handbook)."))
        acao("pkg.install", {"packages": [p for p in ("avahi", "nss-mdns") if not pk[p]]},
             "achar impressoras na rede", ["no_avahi"])
    elif not sv["avahi-daemon"]["enabled"]:
        achados.append(_achado("avahi_off", "info", "O avahi-daemon não está habilitado",
                               "Sem ele as impressoras de rede não são encontradas sozinhas."))
        acao("service.enable", {"name": "avahi-daemon"}, "achar impressoras na rede", ["avahi_off"])
    elif not d["nsswitch_mdns"]:
        achados.append(_achado("nss_mdns", "info", "O /etc/nsswitch.conf não usa mdns",
                               "Nomes .local das impressoras não resolvem.",
                               ["Na linha hosts: do /etc/nsswitch.conf: hosts: files mdns dns"]))

    # impressoras encontradas ------------------------------------------------
    for u in usb:
        nome = _nome_fila(u["product"] or u["name"])
        if u["ipp_usb"]:
            uri_local = "ipp://localhost:60000/ipp/print"
            if uri_local in configuradas:
                continue
            achados.append(_achado(f"usb_new:{nome}", "aviso", f"Impressora USB encontrada: {u['name']}",
                                   "Ela aceita IPP-USB: imprime sem driver com o ipp-usb."))
            if not pk["ipp-usb"]:
                acao("pkg.install", {"packages": ["ipp-usb"]}, "imprimir sem driver pela USB",
                     [f"usb_new:{nome}"])
            elif not sv["ipp-usb"]["enabled"]:
                acao("service.enable", {"name": "ipp-usb"}, "imprimir sem driver pela USB",
                     [f"usb_new:{nome}"])
            elif pk["cups"] and sv["cupsd"]["running"]:
                acao("printer.add", {"name": nome, "uri": uri_local}, "adiciona sem driver (IPP-USB)",
                     [f"usb_new:{nome}"])
        else:
            if any("usb://" in x and (u["manufacturer"].split()[0:1] or ["?"])[0].lower() in x.lower()
                   for x in configuradas):
                continue
            drivers = DRIVERS.get(u["vendor"], DRIVERS["outro"])
            faltam = [p for p in drivers if not pk.get(p)]
            passos = ["Configure em http://localhost:631 (Administração → Adicionar impressora) "
                      "ou com system-config-printer"]
            if u["vendor"] == "hp":
                passos.insert(0, "HP: rode hp-setup -i (configuração guiada)")
            achados.append(_achado(f"usb_driver:{nome}", "aviso",
                                   f"Impressora USB encontrada: {u['name']}",
                                   "Ela precisa de driver" +
                                   (f": instale {', '.join(faltam)} e depois configure." if faltam
                                    else " (já instalado): falta configurar."), passos))
            if faltam and pk["cups"]:
                acao("pkg.install", {"packages": faltam}, f"driver {u['vendor'].upper()}",
                     [f"usb_driver:{nome}"])
    for r in rede:
        if r["uri"] in configuradas:
            continue
        nome = _nome_fila(r["name"])
        achados.append(_achado(f"net_new:{nome}", "aviso", f"Impressora de rede encontrada: {r['name']}",
                               f"Imprime sem driver (IPP Everywhere): {r['uri']}"))
        if pk["cups"] and sv["cupsd"]["running"]:
            acao("printer.add", {"name": nome, "uri": r["uri"]}, "adiciona sem driver",
                 [f"net_new:{nome}"])

    # impressoras configuradas ---------------------------------------------------
    for p in d["printers"]:
        if not p["enabled"]:
            achados.append(_achado(f"disabled:{p['name']}", "erro", f"A impressora {p['name']} está pausada",
                                   "O CUPS pausa a impressora quando um trabalho falha."))
            acao("printer.enable", {"name": p["name"]}, "reativa a impressora", [f"disabled:{p['name']}"])
        presos = [j for j in d["jobs"] if j.startswith(p["name"] + "-")]
        if len(presos) >= 3 or (presos and not p["enabled"]):
            achados.append(_achado(f"jobs:{p['name']}", "aviso",
                                   f"{len(presos)} trabalho(s) parado(s) na fila de {p['name']}"))
            acao("printer.cancel_jobs", {"name": p["name"]}, "limpa a fila", [f"jobs:{p['name']}"])
    if d["printers"] and not d["default"]:
        achados.append(_achado("no_default", "info", "Nenhuma impressora padrão definida"))
        acao("printer.set_default", {"name": d["printers"][0]["name"]}, "impressora padrão",
             ["no_default"])

    if not any(a["severity"] in ("erro", "aviso") for a in achados):
        if d["printers"]:
            nomes = ", ".join(f"{p['name']} ({p['state']})" for p in d["printers"])
            achados.insert(0, _achado("printing_ok", "ok", "Impressão configurada",
                                      f"Impressoras: {nomes}. Padrão: {d['default'] or '-'}."))
            for p in d["printers"][:3]:
                acao("printer.test", {"name": p["name"]}, "confere se imprime", [])
        elif pk["cups"]:
            achados.insert(0, _achado("no_printer", "info", "Nenhuma impressora configurada ou encontrada",
                                      "Ligue a impressora (USB ou na mesma rede) e rode o diagnóstico de novo."))
    return achados, acoes


def register(reg):
    reg.register(Tool("printer.status", "Verificando impressoras",
                      "Impressão: CUPS instalado e cupsd rodando, grupo lpadmin, avahi/nss-mdns, "
                      "impressoras configuradas (estado, URI, padrão), fila, impressoras USB "
                      "conectadas (e se aceitam IPP-USB) e de rede encontradas.",
                      t_status, domain="printing"))
    reg.register(Tool("printer.discover", "Procurando impressoras",
                      "Procura impressoras USB conectadas e impressoras IPP na rede (sem driver).",
                      t_discover, domain="printing"))
    nome = {"name": P("string", "nome da fila no CUPS", pattern=RE_NOME)}
    reg.register(Tool("printer.add", "Adicionar impressora",
                      "Adiciona uma impressora que imprime sem driver (IPP Everywhere / IPP-USB) "
                      "pelo URI ipp:// ou ipps:// encontrado.", a_add, kind="action", domain="printing",
                      params={**nome, "uri": P("string", "URI ipp:// ou ipps://", pattern=RE_URI)},
                      required=["name", "uri"], check=_nova_fila,
                      title="Adicionar a impressora {name}",
                      preview=lambda name, uri: f"lpadmin -p {name} -E -v {uri} -m everywhere",
                      verify=_v_add))
    reg.register(Tool("printer.enable", "Reativar impressora",
                      "Reativa uma impressora pausada e volta a aceitar trabalhos.", a_enable,
                      kind="action", domain="printing", params=nome, required=["name"],
                      check=_existe_fila, title="Reativar a impressora {name}",
                      preview=lambda name: f"cupsenable {name} && cupsaccept {name}", verify=_v_enable))
    reg.register(Tool("printer.cancel_jobs", "Limpar a fila",
                      "Cancela todos os trabalhos na fila de uma impressora.", a_cancel_jobs,
                      kind="action", domain="printing", params=nome, required=["name"],
                      check=_existe_fila, title="Limpar a fila de {name}",
                      preview=lambda name: f"cancel -a {name}", verify=_v_jobs,
                      risk="Os trabalhos na fila são descartados."))
    reg.register(Tool("printer.set_default", "Definir impressora padrão",
                      "Define a impressora padrão do seu usuário.", a_default, kind="action",
                      domain="printing", root=False, params=nome, required=["name"],
                      check=_existe_fila, title="Usar {name} como padrão",
                      preview=lambda name: f"lpoptions -d {name}", verify=_v_default))
    reg.register(Tool("printer.test", "Imprimir página de teste",
                      "Imprime a página de teste do CUPS.", a_test, kind="action",
                      domain="printing", root=False, params=nome, required=["name"],
                      check=_existe_fila, title="Imprimir página de teste em {name}",
                      preview=lambda name: f"lp -d {name} /usr/share/cups/data/testprint",
                      verify=_v_test))


def register_checks(reg):
    reg.register(Tool("printing.c_status", STEPS[0][1], STEPS[0][1], c_status,
                      domain="printing", llm=False, internal=True))
