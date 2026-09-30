# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/network.py - diagnóstico de rede
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Diagnóstico de rede do VoidBR.

Coleta (ferramentas de leitura, rodam como o usuário):
    network.interfaces      ip -j link  + /sys/class/net
    network.addresses       ip -j addr
    network.routes          ip -j route / ip -j -6 route
    network.wifi            /sys/class/rfkill, iw dev, iw dev <if> link
    network.services        runit: NetworkManager, iwd, wpa_supplicant, dhcpcd, connmand, dbus
    network.networkmanager  nmcli (só se o NetworkManager estiver rodando)
    network.connectivity    ping no gateway e em IPs públicos (+ TCP, se o ICMP for bloqueado)
    network.dns             /etc/resolv.conf + resolução de nomes

Análise (analyze): regras fixas que transformam o estado em ACHADOS
(confirmados, porque vêm de dados reais) e AÇÕES propostas (da lista branca).
Funciona sem LLM. O LLM, se houver, só interpreta e escolhe entre essas ações.

Não assume NetworkManager: detecta o que está instalado, habilitado e rodando.
"""

import json
import os
import re
import socket
import threading

from ..util import read_file, read_int, run, running_processes, which
from . import services as svc
from .privileged import run_helper
from .registry import P, Tool

NET_SERVICES = ["NetworkManager", "connmand", "iwd", "wpa_supplicant", "dhcpcd", "dbus"]
MANAGERS = ["NetworkManager", "connmand", "dhcpcd", "iwd"]   # quem configura IP
_RE_IFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


# ---------------------------------------------------------------------------
# coleta
# ---------------------------------------------------------------------------

def _ip_json(args):
    r = run(["ip", "-j", *args], timeout=5)
    if r["rc"] != 0:
        return None, r
    try:
        return json.loads(r["out"] or "[]"), r
    except ValueError:
        return None, r


def _tipo(nome, link_type):
    if link_type == "loopback" or nome == "lo":
        return "loopback"
    base = f"/sys/class/net/{nome}"
    if os.path.isdir(f"{base}/wireless") or os.path.exists(f"{base}/phy80211"):
        return "wifi"
    if os.path.exists(f"/sys/devices/virtual/net/{nome}"):
        return "virtual"
    if link_type == "ether":
        return "ethernet"
    return link_type or "outro"


def _driver(nome):
    try:
        return os.path.basename(os.path.realpath(f"/sys/class/net/{nome}/device/driver"))
    except OSError:
        return ""


def interfaces(state=None, cfg=None):
    links, r = _ip_json(["link"])
    itens = []
    if links is None:
        # sem iproute2: /sys/class/net
        try:
            nomes = sorted(os.listdir("/sys/class/net"))
        except OSError:
            nomes = []
        for nome in nomes:
            try:
                flags = int((read_file(f"/sys/class/net/{nome}/flags") or "0").strip(), 16)
            except ValueError:
                flags = 0
            arphrd = read_int(f"/sys/class/net/{nome}/type", 0)   # 1 = ether, 772 = loopback
            lt = {1: "ether", 772: "loopback"}.get(arphrd, "")
            itens.append({"name": nome, "type": _tipo(nome, lt), "up": bool(flags & 0x1),
                          "carrier": read_int(f"/sys/class/net/{nome}/carrier") == 1,
                          "operstate": (read_file(f"/sys/class/net/{nome}/operstate") or "").strip(),
                          "mac": (read_file(f"/sys/class/net/{nome}/address") or "").strip(),
                          "driver": _driver(nome)})
        fonte = "sysfs"
    else:
        for l in links:
            nome = l.get("ifname", "?")
            flags = l.get("flags", [])
            itens.append({"name": nome, "type": _tipo(nome, l.get("link_type", "")),
                          "up": "UP" in flags, "carrier": "LOWER_UP" in flags,
                          "operstate": l.get("operstate", ""), "mac": l.get("address", ""),
                          "driver": _driver(nome)})
        fonte = "ip"
    fisicas = [i for i in itens if i["type"] in ("ethernet", "wifi")]
    partes = [f"{i['name']} {'UP' if i['up'] else 'DOWN'}" for i in fisicas]
    return {
        "source": fonte,
        "interfaces": itens,
        "summary": ", ".join(partes) if partes else "nenhuma interface física",
        "status": "ok" if any(i["up"] for i in fisicas) else "fail",
    }


def addresses(state=None, cfg=None):
    dados, r = _ip_json(["addr"])
    por_if = {}
    for l in dados or []:
        lista = []
        for a in l.get("addr_info", []):
            lista.append({"family": "ipv4" if a.get("family") == "inet" else "ipv6",
                          "address": a.get("local", ""), "prefix": a.get("prefixlen"),
                          "scope": a.get("scope", ""), "dynamic": bool(a.get("dynamic"))})
        por_if[l.get("ifname", "?")] = lista
    v4 = [f"{n} {a['address']}/{a['prefix']}" for n, ls in por_if.items() if n != "lo"
          for a in ls if a["family"] == "ipv4" and a["scope"] == "global"]
    if dados is None:
        return {"addresses": {}, "error": r["err"].strip() or "comando ip indisponível",
                "summary": "não foi possível ler (iproute2 ausente?)", "status": "info"}
    return {
        "addresses": por_if,
        "error": None,
        "summary": ", ".join(v4) if v4 else "nenhum IPv4",
        "status": "ok" if v4 else "fail",
    }


def _proc_route():
    """Rotas IPv4 lidas de /proc/net/route (quando o ip não está disponível)."""
    rotas = []
    for linha in (read_file("/proc/net/route") or "").splitlines()[1:]:
        c = linha.split()
        if len(c) < 8:
            continue
        def ip(h):
            return socket.inet_ntoa(int(h, 16).to_bytes(4, "little"))
        r = {"dst": "default" if c[1] == "00000000" else ip(c[1]), "dev": c[0],
             "metric": int(c[6])}
        if c[2] != "00000000":
            r["gateway"] = ip(c[2])
        rotas.append(r)
    return rotas


def routes(state=None, cfg=None):
    v4, _ = _ip_json(["route"])
    if v4 is None:
        v4 = _proc_route()
    v6, _ = _ip_json(["-6", "route", "show", "default"])
    padrao = [{"gateway": r.get("gateway", ""), "dev": r.get("dev", ""),
               "metric": r.get("metric", 0), "protocol": r.get("protocol", "")}
              for r in (v4 or []) if r.get("dst") == "default"]
    padrao.sort(key=lambda r: r["metric"] or 0)
    padrao6 = [{"gateway": r.get("gateway", ""), "dev": r.get("dev", "")} for r in (v6 or [])]
    gw = padrao[0]["gateway"] if padrao else ""
    return {
        "routes": v4 or [],
        "default": padrao,
        "default6": padrao6,
        "gateway": gw,
        "gateway_dev": padrao[0]["dev"] if padrao else "",
        "summary": f"rota padrão via {gw} ({padrao[0]['dev']})" if padrao else "sem rota padrão",
        "status": "ok" if padrao else "fail",
    }


def _rfkill():
    itens = []
    base = "/sys/class/rfkill"
    try:
        nomes = sorted(os.listdir(base))
    except OSError:
        return itens
    for n in nomes:
        itens.append({"id": n, "type": (read_file(f"{base}/{n}/type") or "").strip(),
                      "name": (read_file(f"{base}/{n}/name") or "").strip(),
                      "soft": read_int(f"{base}/{n}/soft") == 1,
                      "hard": read_int(f"{base}/{n}/hard") == 1})
    return itens


def _iw_link(nome):
    r = run(["iw", "dev", nome, "link"], timeout=5)
    info = {"connected": False}
    if r["rc"] != 0:
        info["error"] = (r["err"] or r["out"]).strip()
        return info
    for linha in r["out"].splitlines():
        s = linha.strip()
        if s.startswith("Connected to"):
            info["connected"] = True
            info["bssid"] = s.split()[2]
        elif ":" in s:
            k, v = s.split(":", 1)
            k = k.strip().lower()
            if k in ("ssid", "freq", "signal", "tx bitrate", "rx bitrate"):
                info[k.replace(" ", "_")] = v.strip()
    return info


def wifi(state=None, cfg=None):
    ifs = [i["name"] for i in (state or {}).get("interfaces", {}).get("interfaces", [])
           if i["type"] == "wifi"]
    rf = _rfkill()
    dados = {"iw": bool(which("iw")), "rfkill": rf, "devices": {}}
    for nome in ifs:
        dados["devices"][nome] = _iw_link(nome) if dados["iw"] else {"connected": None}
    wl = [r for r in rf if r["type"] == "wlan"]
    if not ifs:
        dados.update(summary="nenhuma interface Wi-Fi", status="info")
    elif any(r["hard"] for r in wl):
        dados.update(summary="Wi-Fi bloqueado por hardware (chave/tecla)", status="fail")
    elif any(r["soft"] for r in wl):
        dados.update(summary="Wi-Fi bloqueado por software (rfkill)", status="fail")
    else:
        conectados = [f"{n} → {d.get('ssid', '?')} ({d.get('signal', '?')})"
                      for n, d in dados["devices"].items() if d.get("connected")]
        dados.update(summary=", ".join(conectados) if conectados else "Wi-Fi não conectado",
                     status="ok" if conectados else "warn")
    return dados


def services(state=None, cfg=None):
    procs = running_processes()
    nomes = list(NET_SERVICES)
    nomes += [s for s in svc.list_enabled() if s.startswith("dhcpcd-")]
    sts = {n: svc.status(n, procs) for n in nomes}
    rodando = [n for n, s in sts.items() if s["running"] and n != "dbus"]
    gerente = any(n in MANAGERS or n.startswith("dhcpcd-") for n in rodando)
    return {
        "services": sts,
        "running": rodando,
        "summary": ("rodando: " + ", ".join(rodando)) if rodando
                   else "nenhum serviço de rede rodando",
        "status": "ok" if gerente else "fail",
    }


def _nm_terse(texto):
    linhas = []
    for linha in texto.splitlines():
        if linha:
            campos = re.split(r"(?<!\\):", linha)
            linhas.append([c.replace("\\:", ":").replace("\\\\", "\\") for c in campos])
    return linhas


def networkmanager(state=None, cfg=None):
    sts = (state or {}).get("services", {}).get("services", {})
    nm = sts.get("NetworkManager", {})
    if not nm.get("running"):
        return {"active": False, "summary": "NetworkManager não está rodando", "status": "info"}
    if not which("nmcli"):
        return {"active": True, "nmcli": False, "summary": "nmcli não encontrado", "status": "info"}
    dados = {"active": True, "nmcli": True}
    r = run(["nmcli", "-t", "-f", "STATE,CONNECTIVITY,NETWORKING,WIFI-HW,WIFI", "general"])
    g = _nm_terse(r["out"])
    if g and len(g[0]) >= 5:
        dados["general"] = dict(zip(["state", "connectivity", "networking", "wifi_hw", "wifi"], g[0]))
    r = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    dados["devices"] = [dict(zip(["device", "type", "state", "connection"], l))
                        for l in _nm_terse(r["out"])]
    r = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE", "connection", "show"])
    dados["connections"] = [dict(zip(["name", "type", "device", "active"], l))
                            for l in _nm_terse(r["out"])]
    g = dados.get("general", {})
    dados["summary"] = f"estado {g.get('state', '?')}, conectividade {g.get('connectivity', '?')}"
    dados["status"] = "ok" if g.get("state", "").startswith("connected") else "warn"
    return dados


def _ping(host, timeout):
    r = run(["ping", "-n", "-c", "2", "-W", str(timeout), host], timeout=timeout * 2 + 3)
    res = {"host": host, "ok": r["rc"] == 0, "method": "icmp", "missing": r["missing"]}
    m = re.search(r"= [\d.]+/([\d.]+)/", r["out"])
    if m:
        res["rtt_ms"] = float(m.group(1))
    return res


def _tcp(host, port, timeout):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def connectivity(state=None, cfg=None):
    cfg = cfg or {}
    t = int(cfg.get("ping_timeout", 2))
    alvos = list(cfg.get("ping_targets", ["1.1.1.1", "8.8.8.8"]))
    gw = (state or {}).get("routes", {}).get("gateway", "")
    resultados = {}

    def testar(chave, host):
        resultados[chave] = _ping(host, t)

    threads = [threading.Thread(target=testar, args=(h, h)) for h in alvos]
    if gw:
        threads.append(threading.Thread(target=testar, args=("gateway", gw)))
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    internet = any(resultados[h]["ok"] for h in alvos)
    tcp = None
    if not internet:
        # ICMP pode estar bloqueado (ou ping ausente): tenta TCP 443
        tcp = any(_tcp(h, 443, t + 1) for h in alvos)
        internet = tcp
    gw_res = resultados.get("gateway")
    dados = {
        "gateway": gw_res,
        "targets": [resultados[h] for h in alvos],
        "tcp_fallback": tcp,
        "internet": internet,
    }
    if not gw and not internet:
        dados.update(summary="sem gateway para testar", status="fail")
    elif internet:
        rtt = [r.get("rtt_ms") for r in dados["targets"] if r.get("rtt_ms")]
        dados.update(summary="internet OK" + (f" ({min(rtt):.0f} ms)" if rtt else " (via TCP)"),
                     status="ok")
    elif gw_res and gw_res["ok"]:
        dados.update(summary=f"gateway {gw} responde, mas a internet não", status="fail")
    else:
        dados.update(summary=f"gateway {gw} não responde", status="fail")
    return dados


def _resolve(host, timeout):
    res = {"host": host, "ok": False, "addresses": [], "error": ""}

    def trabalho():
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            res["addresses"] = sorted({i[4][0] for i in infos})
            res["ok"] = True
        except OSError as e:
            res["error"] = str(e)

    th = threading.Thread(target=trabalho, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        res["error"] = "tempo esgotado"
    return res


def dns(state=None, cfg=None):
    cfg = cfg or {}
    texto = read_file("/etc/resolv.conf", "") or ""
    servidores, busca, gerador = [], [], ""
    for linha in texto.splitlines():
        s = linha.strip()
        if s.startswith("#"):
            low = s.lower()
            for nome in ("networkmanager", "resolvconf", "dhcpcd", "connman", "systemd-resolved"):
                if nome in low and not gerador:
                    gerador = nome
        elif s.startswith("nameserver"):
            partes = s.split()
            if len(partes) > 1:
                servidores.append(partes[1])
        elif s.startswith(("search", "domain")):
            busca += s.split()[1:]
    link = os.path.realpath("/etc/resolv.conf") if os.path.islink("/etc/resolv.conf") else ""
    testes = [_resolve(h, int(cfg.get("dns_timeout", 5)))
              for h in cfg.get("dns_test_hosts", ["voidbr.org", "voidlinux.org"])]
    ok = any(t["ok"] for t in testes)
    dados = {
        "resolv_conf": {"nameservers": servidores, "search": busca, "generated_by": gerador,
                        "symlink": link, "exists": bool(texto)},
        "resolution": testes,
        "ok": ok,
        "summary": (("resolução OK" if ok else "resolução de nomes falhando")
                    + (f" (servidores: {', '.join(servidores)})" if servidores
                       else " (nenhum servidor DNS configurado)")),
        "status": "ok" if ok else "fail",
    }
    return dados


# ordem do diagnóstico: (ferramenta, rótulo mostrado ao usuário, chave no estado)
STEPS = [
    ("network.interfaces", "Verificando interfaces", "interfaces"),
    ("network.addresses", "Verificando endereços IP", "addresses"),
    ("network.routes", "Verificando rota padrão e gateway", "routes"),
    ("network.wifi", "Verificando Wi-Fi", "wifi"),
    ("network.services", "Verificando serviços de rede (runit)", "services"),
    ("network.networkmanager", "Consultando o NetworkManager", "networkmanager"),
    ("network.connectivity", "Testando conectividade", "connectivity"),
    ("network.dns", "Verificando DNS", "dns"),
]

KEYWORDS = ["rede", "internet", "wifi", "wi-fi", "wireless", "wlan", "conexao", "conectar",
            "conecta", "dns", "ethernet", "cabo", "networkmanager", "nmcli", "iwd", "dhcp",
            "ping", "gateway", "roteador", "modem", "site", "sites", "navegador", "ip",
            "offline", "online", "network", "rede sem fio"]


# ---------------------------------------------------------------------------
# análise (sem LLM)
# ---------------------------------------------------------------------------

def _achado(codigo, sev, titulo, detalhe="", passo="", sugestoes=None):
    return {"code": codigo, "severity": sev, "title": titulo, "detail": detalhe,
            "step": passo, "confirmed": True, "suggestions": sugestoes or []}


def manager_service(state):
    """Serviço que (provavelmente) configura a rede nesta máquina."""
    sts = state.get("services", {}).get("services", {})
    for nome in MANAGERS:
        if sts.get(nome, {}).get("running"):
            return nome
    dhcp_if = [n for n, s in sts.items() if n.startswith("dhcpcd-") and s["running"]]
    if dhcp_if:
        return dhcp_if[0]
    for nome in MANAGERS:
        if sts.get(nome, {}).get("enabled"):
            return nome
    return ""


def analyze(state, reg):
    """Devolve (achados, ações) a partir do estado coletado."""
    achados, acoes = [], []

    def acao(tool, args, titulo, motivo, fixes):
        try:
            a = reg.make_action(tool, args, titulo, motivo, fixes)
        except ValueError:      # argumento inválido nesta máquina (ex: serviço ausente)
            return
        if a.id not in {x.id for x in acoes}:
            acoes.append(a)

    ifs = state.get("interfaces", {}).get("interfaces", [])
    fisicas = [i for i in ifs if i["type"] in ("ethernet", "wifi")]
    addrs = state.get("addresses", {}).get("addresses", {})
    rotas = state.get("routes", {})
    wf = state.get("wifi", {})
    sts = state.get("services", {}).get("services", {})
    nm = state.get("networkmanager", {})
    con = state.get("connectivity", {})
    dn = state.get("dns", {})

    def ipv4(nome):
        return [a for a in addrs.get(nome, []) if a["family"] == "ipv4" and a["scope"] == "global"]

    nm_off = nm.get("general", {}).get("networking") == "disabled"
    tem_rota = bool(rotas.get("default"))
    internet = bool(con.get("internet"))
    dns_ok = bool(dn.get("ok"))
    gerente = manager_service(state)

    # --- tudo certo ------------------------------------------------------
    if internet and dns_ok:
        via = rotas.get("gateway_dev", "")
        det = "Internet e DNS respondendo"
        det += f", saída por {via}" if via else ""
        det += f", rede gerenciada por {gerente}." if gerente else "."
        achados.append(_achado("ok", "ok", "A rede está funcionando", det, "connectivity"))

    # --- interfaces -------------------------------------------------------
    if not fisicas:
        achados.append(_achado(
            "no_interfaces", "info" if internet else "erro", "Nenhuma interface de rede física encontrada",
            "O kernel não expôs nenhuma placa Ethernet ou Wi-Fi. Pode faltar o driver/firmware "
            "da placa (ex: pacotes linux-firmware-network, broadcom-wl-dkms).", "interfaces",
            ["Verifique a placa com: lspci -k | grep -A3 -i net",
             "Procure mensagens de firmware: dmesg | grep -i firmware"]))

    for i in fisicas:
        n = i["name"]
        if not i["up"]:
            # uma interface desligada só é problema se não houver outra funcionando
            sev = "aviso" if internet else "erro"
            achados.append(_achado(f"iface_down:{n}", sev, f"A interface {n} está desligada (DOWN)",
                                   f"{n} ({i['type']}) está administrativamente desligada.",
                                   "interfaces"))
            if not internet:
                acao("network.link_up", {"iface": n}, f"Ligar a interface {n}",
                     f"{n} está DOWN", [f"iface_down:{n}"])
        elif i["type"] == "ethernet" and not i["carrier"] and not internet:
            achados.append(_achado(f"no_carrier:{n}", "aviso", f"Sem cabo/sinal em {n}",
                                   "A interface está ligada mas não detecta link: cabo desconectado, "
                                   "cabo ruim ou porta do roteador desligada.", "interfaces"))
        elif i["up"] and i["carrier"] and not ipv4(n) and not internet:
            # carrier (LOWER_UP) no Wi-Fi = associado a um ponto de acesso
            achados.append(_achado(f"no_ipv4:{n}", "erro", f"{n} não recebeu endereço IPv4",
                                   "Há link na interface, mas nenhum IP foi atribuído — o DHCP "
                                   "não respondeu ou o serviço que configura a rede não está atuando.",
                                   "addresses"))
            if gerente and not nm_off:   # com a rede desligada no NM a causa já é conhecida
                acao("service.restart", {"name": gerente}, f"Reiniciar o {gerente}",
                     f"{n} tem link mas não tem IP", [f"no_ipv4:{n}"])

    # --- Wi-Fi --------------------------------------------------------------
    wlan = [r for r in wf.get("rfkill", []) if r["type"] == "wlan"]
    if any(r["hard"] for r in wlan):
        achados.append(_achado("rfkill_hard", "aviso" if internet else "erro",
                               "Wi-Fi bloqueado por hardware",
                               "Existe uma chave física, tecla de função (Fn) ou opção na BIOS "
                               "desligando o rádio. Isso não pode ser desfeito por software.", "wifi"))
    if any(r["soft"] for r in wlan):
        achados.append(_achado("rfkill_soft", "aviso" if internet else "erro",
                               "Wi-Fi bloqueado por software (rfkill)",
                               "O rádio Wi-Fi está desligado pelo sistema.", "wifi"))
        acao("network.rfkill_unblock", {}, "Desbloquear o Wi-Fi (rfkill)",
             "rádio Wi-Fi bloqueado por software", ["rfkill_soft"])
    for n, d in wf.get("devices", {}).items():
        up = next((i["up"] for i in fisicas if i["name"] == n), False)
        if d.get("connected") is False and up and not internet and not any(r["soft"] or r["hard"] for r in wlan):
            dica = []
            if gerente == "NetworkManager":
                dica = ["Listar redes: nmcli device wifi list",
                        "Conectar: nmcli device wifi connect \"NOME\" --ask"]
            elif sts.get("iwd", {}).get("running"):
                dica = [f"Conectar: iwctl station {n} connect \"NOME\""]
            achados.append(_achado(f"wifi_not_connected:{n}", "erro",
                                   f"{n} não está conectado a nenhuma rede Wi-Fi",
                                   "A placa está ligada, mas não associada a um ponto de acesso. "
                                   "Conectar exige escolher a rede e informar a senha.", "wifi", dica))
        elif d.get("connected"):
            achados.append(_achado(f"wifi_ok:{n}", "ok", f"{n} conectado a “{d.get('ssid', '?')}”",
                                   f"sinal {d.get('signal', '?')}, frequência {d.get('freq', '?')} MHz",
                                   "wifi"))

    # --- serviços (runit) ----------------------------------------------------
    habilitados = [n for n in MANAGERS if sts.get(n, {}).get("enabled")]
    habilitados += [n for n in sts if n.startswith("dhcpcd-") and sts[n]["enabled"]]
    parados = [n for n in habilitados if not sts[n]["running"]]

    for n in parados:
        achados.append(_achado(f"service_down:{n}", "aviso" if internet else "erro",
                               f"O serviço {n} está habilitado mas não está rodando",
                               sts[n].get("state", ""), "services"))
        acao("service.start", {"name": n}, f"Iniciar o {n}", f"{n} habilitado e parado",
             [f"service_down:{n}", "no_manager"])

    if not habilitados:
        disp = [n for n in ("NetworkManager", "connmand", "dhcpcd") if sts.get(n, {}).get("available")]
        det = ("Nenhum serviço que configura a rede (NetworkManager, connman, dhcpcd, iwd) "
               "está habilitado em /var/service.")
        achados.append(_achado("no_manager", "aviso" if internet else "erro",
                               "Nenhum gerenciador de rede habilitado", det, "services",
                               [] if disp else ["Instale um: vinstall NetworkManager"]))
        if disp and not internet:
            acao("service.enable", {"name": disp[0]}, f"Habilitar e iniciar o {disp[0]}",
                 "nenhum gerenciador de rede habilitado", ["no_manager"])

    usa_nm = sts.get("NetworkManager", {}).get("enabled")
    if usa_nm and not sts.get("dbus", {}).get("running"):
        achados.append(_achado("dbus_down", "erro", "O dbus não está rodando",
                               "O NetworkManager depende do dbus.", "services"))
        verbo = "service.start" if sts.get("dbus", {}).get("enabled") else "service.enable"
        acao(verbo, {"name": "dbus"}, "Iniciar o dbus", "NetworkManager precisa do dbus",
             ["dbus_down"])

    # conflitos clássicos no Void: NetworkManager + dhcpcd/wpa_supplicant/connman como serviços
    if sts.get("NetworkManager", {}).get("running"):
        for outro in ["dhcpcd", "wpa_supplicant", "connmand"] + \
                     [n for n in sts if n.startswith("dhcpcd-")]:
            if sts.get(outro, {}).get("enabled"):
                achados.append(_achado(
                    f"conflict:{outro}", "aviso",
                    f"Possível conflito: NetworkManager e {outro} habilitados juntos",
                    f"O NetworkManager já gerencia DHCP e Wi-Fi sozinho. O serviço {outro} "
                    "rodando em paralelo pode disputar as interfaces (IP que some, Wi-Fi que "
                    "cai). Hipótese: só é o problema se a conexão estiver instável.", "services"))
                achados[-1]["confirmed"] = False
                acao("service.disable", {"name": outro}, f"Desabilitar o serviço {outro}",
                     "conflito com o NetworkManager", [f"conflict:{outro}"])

    # --- NetworkManager -------------------------------------------------------
    g = nm.get("general", {})
    if g.get("networking") == "disabled":
        achados.append(_achado("nm_networking_off", "erro", "A rede está desativada no NetworkManager",
                               "O NetworkManager está rodando, mas com a rede desligada "
                               "(nmcli networking off / modo avião).", "networkmanager"))
        acao("network.nm_networking_on", {}, "Ativar a rede no NetworkManager",
             "networking desativado", ["nm_networking_off"])
    if g.get("wifi") == "disabled" and g.get("wifi_hw") == "enabled" and \
            any(i["type"] == "wifi" for i in fisicas):
        achados.append(_achado("nm_wifi_off", "aviso" if internet else "erro",
                               "O Wi-Fi está desligado no NetworkManager",
                               "O rádio existe, mas o NetworkManager está com o Wi-Fi desativado.",
                               "networkmanager"))
        acao("network.nm_wifi_on", {}, "Ligar o Wi-Fi no NetworkManager", "Wi-Fi desativado",
             ["nm_wifi_off"])

    # --- rota, gateway, internet ---------------------------------------------
    tem_ip = any(ipv4(i["name"]) for i in fisicas)
    if tem_ip and not tem_rota:
        achados.append(_achado("no_default_route", "erro", "Não existe rota padrão (gateway)",
                               "A máquina tem IP, mas não sabe para onde mandar o tráfego da "
                               "internet.", "routes"))
        if gerente:
            acao("service.restart", {"name": gerente}, f"Reiniciar o {gerente}",
                 "sem rota padrão", ["no_default_route"])
    gw = con.get("gateway") or {}
    if tem_rota and not internet:
        if gw and not gw.get("ok") and not gw.get("missing"):
            achados.append(_achado("gateway_unreachable", "erro",
                                   f"O gateway {gw.get('host')} não responde",
                                   "A rede local não está funcionando: roteador desligado, Wi-Fi "
                                   "fraco, cabo com problema ou IP em rede errada.", "connectivity"))
            if gerente:
                acao("service.restart", {"name": gerente}, f"Reiniciar o {gerente}",
                     "gateway inacessível", ["gateway_unreachable"])
        else:
            achados.append(_achado("no_internet", "erro",
                                   "O roteador responde, mas não há acesso à internet",
                                   "A rede local está OK; o problema está depois do roteador "
                                   "(modem, provedor ou login do provedor).", "connectivity",
                                   ["Reinicie o modem/roteador", "Verifique outro aparelho na mesma rede"]))
    elif internet and gw and not gw.get("ok") and not gw.get("missing"):
        achados.append(_achado("gateway_noping", "info", "O gateway não responde a ping",
                               "Normal em alguns roteadores (bloqueiam ICMP); a internet funciona.",
                               "connectivity"))

    # --- DNS -----------------------------------------------------------------
    rc = dn.get("resolv_conf", {})
    if internet and not dns_ok:
        if not rc.get("nameservers"):
            achados.append(_achado("no_nameservers", "erro", "Nenhum servidor DNS configurado",
                                   "/etc/resolv.conf não tem nenhuma linha nameserver; a internet "
                                   "funciona por IP, mas nomes (sites) não resolvem.", "dns"))
            fix = ["no_nameservers"]
        else:
            achados.append(_achado("dns_fail", "erro", "A resolução de nomes (DNS) está falhando",
                                   f"A internet responde por IP, mas os servidores DNS "
                                   f"({', '.join(rc['nameservers'])}) não resolvem nomes.", "dns",
                                   ["Teste outro DNS: nslookup voidbr.org 1.1.1.1"]))
            fix = ["dns_fail"]
        if gerente:
            acao("service.restart", {"name": gerente}, f"Reiniciar o {gerente}",
                 "regenera o /etc/resolv.conf", fix)

    ordem = {"erro": 0, "aviso": 1, "info": 2, "ok": 3}
    achados.sort(key=lambda a: ordem.get(a["severity"], 9))
    # correções específicas primeiro; reinícios genéricos depois; desabilitar por último
    prioridade = {"network.rfkill_unblock": 0, "network.nm_networking_on": 1,
                  "network.nm_wifi_on": 2, "network.link_up": 3, "service.enable": 4,
                  "service.start": 5, "service.restart": 6, "service.disable": 9}
    acoes.sort(key=lambda a: (prioridade.get(a.tool, 7), a.args.get("name") != "dbus"))
    return achados, acoes


def network_status(state):
    """Resumo no formato do manifesto (para --json e para o LLM)."""
    return {
        "interfaces": state.get("interfaces", {}).get("interfaces", []),
        "addresses": state.get("addresses", {}).get("addresses", {}),
        "routes": state.get("routes", {}).get("default", []),
        "gateway": state.get("routes", {}).get("gateway", ""),
        "dns": state.get("dns", {}),
        "connectivity": state.get("connectivity", {}),
        "services": state.get("services", {}).get("services", {}),
        "wifi": state.get("wifi", {}),
        "networkmanager": state.get("networkmanager", {}),
    }


# ---------------------------------------------------------------------------
# ações (via helper root, só com confirmação)
# ---------------------------------------------------------------------------

def link_up(iface, on_line=None):
    return run_helper("link-up", iface, timeout=30, on_line=on_line)


def rfkill_unblock(on_line=None):
    return run_helper("rfkill-unblock", "wlan", timeout=30, on_line=on_line)


def nm_networking_on(on_line=None):
    return run_helper("nm-networking-on", timeout=30, on_line=on_line)


def nm_wifi_on(on_line=None):
    return run_helper("nm-wifi-on", timeout=30, on_line=on_line)


def _iface_existe(args):
    if not os.path.exists(f"/sys/class/net/{args['iface']}"):
        return f"a interface {args['iface']} não existe"
    return None


def _v_link(iface):
    ok = any(i["name"] == iface and i["up"] for i in interfaces()["interfaces"])
    return ok, f"{iface} " + ("está UP" if ok else "continua DOWN")


def _v_rfkill():
    bloq = [r for r in _rfkill() if r["type"] == "wlan" and r["soft"]]
    return not bloq, "Wi-Fi desbloqueado" if not bloq else "o Wi-Fi continua bloqueado"


def _v_nm(campo):
    def f():
        r = run(["nmcli", "-t", "-f", campo.upper(), "general"])
        v = r["out"].strip()
        return v == "enabled", f"{campo}: {v or '?'}"
    return f


# ---------------------------------------------------------------------------
# ferramenta para o LLM: o diagnóstico completo de uma vez
# ---------------------------------------------------------------------------

def t_diagnose():
    """Chamada pelo LLM: roda todas as etapas e devolve estado + achados das regras."""
    from . import build_registry
    reg = build_registry()
    estado = {}
    for nome, _rot, chave in STEPS:
        estado[chave] = reg.call(nome, state=estado, cfg={})
    achados, acoes = analyze(estado, reg)
    st = network_status(estado)
    return {
        "achados": [{k: f[k] for k in ("code", "severity", "title", "detail")} for f in achados],
        "acoes_sugeridas": [{"acao": a.tool, "argumentos": a.args, "motivo": a.reason}
                            for a in acoes],
        "interfaces": [{k: i[k] for k in ("name", "type", "up", "carrier")}
                       for i in st["interfaces"] if i["type"] != "loopback"],
        "ipv4": {n: [a["address"] for a in ls if a["family"] == "ipv4"]
                 for n, ls in st["addresses"].items() if n != "lo"},
        "gateway": st["gateway"],
        "dns": st["dns"].get("resolv_conf", {}).get("nameservers", []),
        "internet": st["connectivity"].get("internet"),
        "servicos_rodando": estado.get("services", {}).get("running", []),
    }


def register(reg):
    for nome, rotulo, _chave in STEPS:
        func = globals()[nome.split(".", 1)[1]]
        reg.register(Tool(nome, rotulo, rotulo, func, domain="network", llm=False, internal=True))
    reg.register(Tool("network.diagnose", "Diagnosticando a rede",
                      "Diagnóstico completo de rede: interfaces, Wi-Fi/rfkill, IP, rotas, gateway, "
                      "DNS, internet e serviços (NetworkManager, iwd, wpa_supplicant, dhcpcd, "
                      "connman). Devolve achados e ações sugeridas.", t_diagnose, domain="network"))
    iface = {"iface": P("string", "nome da interface (ex: wlan0, enp3s0)", pattern=r"[A-Za-z0-9_.:-]{1,15}")}
    reg.register(Tool("network.link_up", "Ligar interface", "Liga uma interface de rede (ip link set <if> up)",
                      link_up, kind="action", domain="network", params=iface, required=["iface"],
                      check=_iface_existe, preview=lambda iface: f"ip link set {iface} up",
                      title="Ligar a interface {iface}", verify=_v_link))
    reg.register(Tool("network.rfkill_unblock", "Desbloquear o Wi-Fi (rfkill)",
                      "Tira o bloqueio de software do rádio Wi-Fi", rfkill_unblock,
                      kind="action", domain="network", verify=_v_rfkill,
                      preview=lambda: "rfkill unblock wifi  (via /sys/class/rfkill)"))
    reg.register(Tool("network.nm_networking_on", "Ativar a rede no NetworkManager",
                      "nmcli networking on", nm_networking_on, kind="action", domain="network",
                      preview=lambda: "nmcli networking on", verify=_v_nm("networking")))
    reg.register(Tool("network.nm_wifi_on", "Ligar o Wi-Fi no NetworkManager",
                      "nmcli radio wifi on", nm_wifi_on, kind="action", domain="network",
                      preview=lambda: "nmcli radio wifi on", verify=_v_nm("wifi")))
