# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/system.py - sistema, hardware, logs e configuração
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Ferramentas gerais de leitura: informações do sistema, memória, processos,
hardware (PCI/USB com drivers), boot, logs do kernel e do socklog, leitura de
arquivos de configuração (lista branca, sem segredos) e onde está um comando."""

import glob
import os
import re

import grp
import pwd

from .. import context
from ..util import read_file, run, which
from .privileged import run_helper
from .registry import P, Tool

# grupos que o helper aceita (a mesma lista fechada do voidbr-ai-helper)
GRUPOS = ["audio", "video", "render", "input", "bluetooth", "socklog", "_seatd", "network", "plugdev"]


def a_add_group(group, on_line=None):
    return run_helper("groups-add", group, timeout=60, on_line=on_line)


def _v_group(group):
    usuario = pwd.getpwuid(os.getuid()).pw_name
    try:
        ok = usuario in grp.getgrnam(group).gr_mem
    except KeyError:
        return False, f"o grupo {group} não existe"
    return ok, (f"{usuario} está no grupo {group} (vale a partir do próximo login)" if ok
                else f"{usuario} não entrou no grupo {group}")


def _c_group(args):
    try:
        grp.getgrnam(args["group"])
    except KeyError:
        return f"o grupo {args['group']} não existe neste sistema"
    return None

# arquivos de configuração que o LLM pode ler
PERMITIDOS = ("/etc/", "/proc/cmdline", "/boot/grub/grub.cfg", "/boot/efi/limine/",
              "/boot/limine/", "/usr/share/examples/")
# ...exceto estes (segredos)
NEGADOS = re.compile(
    r"(shadow|gshadow|sudoers|/ssh/.*key|\.key$|\.pem$|\.psk$|crypttab|/ppp/.*secrets|"
    r"system-connections|wpa_supplicant.*\.conf$|/iwd/|/ssl/private|/polkit-1/rules\.d|"
    r"/voidbr-ai/.*\.key|openai)", re.I)
REDIGIR = re.compile(r"^(\s*(psk|password|passwd|secret|token|api[_-]?key|key)\s*[=:]\s*).*$",
                     re.I | re.M)


def t_info():
    ctx = context.collect(["distro", "kernel", "arch", "init", "package_manager", "desktop",
                           "cpu", "memory", "gpu"])
    up = read_file("/proc/uptime")
    if up:
        s = int(float(up.split()[0]))
        ctx["uptime"] = f"{s // 86400}d {s % 86400 // 3600}h {s % 3600 // 60}min"
    ctx["firmware"] = "UEFI" if os.path.isdir("/sys/firmware/efi") else "BIOS"
    ctx["user"] = os.environ.get("USER", "")
    return ctx


def meminfo():
    d = {}
    for linha in (read_file("/proc/meminfo") or "").splitlines():
        k, _, v = linha.partition(":")
        try:
            d[k] = int(v.split()[0]) // 1024
        except (ValueError, IndexError):
            pass
    total = d.get("MemTotal", 0)
    return {"total_mib": total, "available_mib": d.get("MemAvailable", 0),
            "available_percent": round(100 * d.get("MemAvailable", 0) / total) if total else None,
            "swap_total_mib": d.get("SwapTotal", 0), "swap_free_mib": d.get("SwapFree", 0),
            "zram": bool(glob.glob("/sys/block/zram*"))}


def t_memory():
    return meminfo()


def t_processes(sort="cpu", limit=12):
    chave = "-%cpu" if sort == "cpu" else "-%mem"
    r = run(["ps", "-eo", "pid,user,comm,%cpu,%mem,rss", f"--sort={chave}"], timeout=10)
    itens = []
    for linha in r["out"].splitlines()[1:limit + 1]:
        p = linha.split(None, 5)
        if len(p) == 6:
            itens.append({"pid": int(p[0]), "user": p[1], "command": p[2], "cpu": float(p[3]),
                          "mem": float(p[4]), "rss_mib": int(p[5]) // 1024})
    carga = (read_file("/proc/loadavg") or "").split()[:3]
    return {"sort": sort, "processes": itens, "load": carga, "cpus": os.cpu_count()}


def t_pci(filter=""):
    r = run(["lspci", "-k"], timeout=10)
    if r["missing"]:
        return {"error": "lspci não encontrado (pacote pciutils)"}
    devs, atual = [], None
    for linha in r["out"].splitlines():
        if linha and not linha[0].isspace():
            atual = {"device": linha.split(" ", 1)[1] if " " in linha else linha}
            devs.append(atual)
        elif atual is not None and ":" in linha:
            k, v = linha.strip().split(":", 1)
            if k in ("Kernel driver in use", "Kernel modules"):
                atual["driver" if k.startswith("Kernel driver") else "modules"] = v.strip()
    if filter:
        devs = [d for d in devs if filter.lower() in d["device"].lower()]
    return {"devices": devs[:60]}


def t_usb():
    r = run(["lsusb"], timeout=10)
    if r["missing"]:
        return {"error": "lsusb não encontrado (pacote usbutils)"}
    return {"devices": [l.split(": ", 1)[-1] for l in r["out"].splitlines()][:60]}


def t_dmesg(filter="", lines=40, level="warn"):
    args = ["dmesg", "--time-format=reltime", "--nopager"]
    if level in ("err", "warn"):
        args += ["--level", "emerg,alert,crit,err" + (",warn" if level == "warn" else "")]
    r = run(args, timeout=10)
    if r["rc"] != 0:
        return {"error": "sem permissão para ler o dmesg (kernel.dmesg_restrict=1); "
                         "rode como root ou no grupo adequado",
                "detail": r["err"].strip()[:200]}
    ls = r["out"].splitlines()
    if filter:
        ls = [l for l in ls if filter.lower() in l.lower()]
    return {"lines": ls[-lines:], "total": len(ls)}


def t_log(filter, lines=40):
    ls, erros = [], []
    for f in sorted(glob.glob("/var/log/socklog/*/current")):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                ls += [f"{os.path.basename(os.path.dirname(f))}: {l.rstrip()}"
                       for l in fh.readlines()[-3000:] if filter.lower() in l.lower()]
        except PermissionError:
            erros.append(f)
    res = {"filter": filter, "lines": ls[-lines:]}
    if not ls:
        res["note"] = ("sem permissão para " + ", ".join(erros) + " (grupo socklog)") if erros else \
            ("nada encontrado" if os.path.isdir("/var/log/socklog") else
             "socklog não instalado/habilitado (pacote socklog-void, serviços socklog-unix e nanoklogd)")
    return res


def t_read_config(path):
    real = os.path.realpath(os.path.expanduser(path))
    casa = os.path.realpath(os.path.expanduser("~/.config")) + "/"
    if not (real.startswith(PERMITIDOS) or real.startswith(casa)) or NEGADOS.search(real):
        return {"error": f"leitura de {path} não permitida"}
    if os.path.isdir(real):
        try:
            return {"path": real, "entries": sorted(os.listdir(real))[:100]}
        except OSError as e:
            return {"error": str(e)}
    texto = read_file(real)
    if texto is None:
        return {"error": f"não foi possível ler {real} (não existe ou sem permissão)"}
    texto = REDIGIR.sub(r"\1<oculto>", texto)
    return {"path": real, "content": texto[:12000], "truncated": len(texto) > 12000}


def t_boot():
    d = {"firmware": "UEFI" if os.path.isdir("/sys/firmware/efi") else "BIOS",
         "cmdline": (read_file("/proc/cmdline") or "").strip(),
         "running_kernel": os.uname().release}
    d["bootloaders"] = [n for n, c in (("grub", "/boot/grub/grub.cfg"),
                                       ("limine", "/boot/efi/limine/limine.conf"),
                                       ("limine", "/boot/limine/limine.conf"))
                        if os.path.exists(c)]
    d["bootloaders"] = sorted(set(d["bootloaders"]))
    try:
        d["installed_kernels"] = sorted(os.listdir("/usr/lib/modules"))
    except OSError:
        d["installed_kernels"] = []
    return d


def t_command(name):
    caminho = which(name)
    d = {"command": name, "path": caminho or ""}
    if caminho:
        r = run(["xbps-query", "-o", caminho], timeout=15)
        d["package"] = r["out"].split(":", 1)[0].strip() if r["out"] else ""
    else:
        d["note"] = "não está instalado; use pkg.search para achar o pacote"
    return d


# ---------------------------------------------------------------------------
# check-up
# ---------------------------------------------------------------------------

def c_memory(state=None, cfg=None):
    m = meminfo()
    pct = m["available_percent"] or 0
    m.update(summary=f"{m['available_mib']} MiB livres de {m['total_mib']} MiB ({pct}%)",
             status="warn" if pct < 10 else "ok")
    return m


def c_processes(state=None, cfg=None):
    p = t_processes("cpu", 5)
    top = p["processes"][0] if p["processes"] else None
    p.update(summary=f"carga {' '.join(p['load'])}" + (f", maior uso: {top['command']} {top['cpu']}%"
                                                       if top else ""), status="info")
    return p


STEPS = [
    ("system.c_memory", "Verificando a memória", "memory"),
    ("system.c_processes", "Verificando processos e carga", "processes"),
]
KEYWORDS = ["lento", "lentidao", "travando", "trava", "memoria", "ram", "swap", "cpu",
            "processo", "processos", "esquentando", "congela", "congelando", "pesado"]


def analyze(state, reg):
    achados = []
    m = state.get("memory", {})
    if m:
        pct = m.get("available_percent") or 0
        if pct < 10:
            achados.append({"code": "low_memory", "severity": "aviso",
                            "title": f"Pouca memória livre ({pct}%)",
                            "detail": f"{m['available_mib']} MiB disponíveis de {m['total_mib']} MiB"
                                      + ("; sem swap/zram" if not m["swap_total_mib"] and not m["zram"]
                                         else ""),
                            "step": "memory", "confirmed": True, "suggestions": []})
        elif not m["swap_total_mib"] and not m["zram"] and m["total_mib"] < 8192:
            achados.append({"code": "no_swap", "severity": "info", "title": "Sem swap nem zram",
                            "detail": "Com menos de 8 GB de RAM, o sistema pode travar quando a "
                                      "memória acaba.", "step": "memory", "confirmed": True,
                            "suggestions": []})
    if m and not achados:
        achados.append({"code": "memory_ok", "severity": "ok",
                        "title": f"Memória OK ({m.get('available_percent')}% livre)", "detail": "",
                        "step": "memory", "confirmed": True, "suggestions": []})
    p = state.get("processes", {})
    carga = float((p.get("load") or ["0"])[0])
    if p and p.get("cpus") and carga > p["cpus"] * 1.5:
        top = ", ".join(f"{x['command']} ({x['cpu']}%)" for x in p["processes"][:3])
        achados.append({"code": "high_load", "severity": "aviso",
                        "title": f"Carga alta no processador ({carga})",
                        "detail": f"{p['cpus']} CPUs. Mais pesados: {top}", "step": "processes",
                        "confirmed": True, "suggestions": []})
    return achados, []


def register(reg):
    reg.register(Tool("user.add_group", "Adicionar você a um grupo",
                      "Adiciona o usuário atual a um grupo do sistema (audio, video, render, input, "
                      "bluetooth, socklog, _seatd, network, plugdev). Vale no próximo login.",
                      a_add_group, kind="action", domain="system",
                      params={"group": P("string", "grupo", enum=GRUPOS)}, required=["group"],
                      check=_c_group, title="Adicionar você ao grupo {group}",
                      preview=lambda group: f"gpasswd -a $USER {group}", verify=_v_group,
                      risk="Vale a partir do próximo login (saia e entre de novo na sessão)."))
    reg.register(Tool("system.info", "Coletando informações do sistema",
                      "Distro, kernel, arquitetura, CPU, GPU, memória, desktop/sessão, init, "
                      "gerenciador de pacotes, firmware (UEFI/BIOS) e uptime.", t_info))
    reg.register(Tool("system.memory", "Verificando a memória", "RAM, swap e zram.", t_memory))
    reg.register(Tool("system.processes", "Listando processos",
                      "Processos que mais usam CPU ou memória, e a carga do sistema.", t_processes,
                      params={"sort": P("string", "cpu ou mem", enum=["cpu", "mem"]),
                              "limit": P("integer", "quantos", minimum=3, maximum=30)}))
    reg.register(Tool("hardware.pci", "Listando hardware PCI",
                      "Dispositivos PCI com o driver do kernel em uso (placa de vídeo, rede, som...).",
                      t_pci, domain="hardware",
                      params={"filter": P("string", "filtrar (ex: VGA, Network, Audio)", maxLength=40)}))
    reg.register(Tool("hardware.usb", "Listando dispositivos USB", "Dispositivos USB (lsusb).",
                      t_usb, domain="hardware"))
    reg.register(Tool("system.dmesg", "Lendo o log do kernel",
                      "Mensagens do kernel (dmesg), por padrão só erros e avisos.", t_dmesg,
                      params={"filter": P("string", "filtrar por texto", maxLength=60),
                              "lines": P("integer", "quantas linhas", minimum=5, maximum=200),
                              "level": P("string", "err, warn ou all", enum=["err", "warn", "all"])}))
    reg.register(Tool("system.log", "Procurando no log do sistema",
                      "Procura um texto nos logs do socklog (/var/log/socklog).", t_log,
                      params={"filter": P("string", "texto a procurar", maxLength=60),
                              "lines": P("integer", "quantas linhas", minimum=5, maximum=200)},
                      required=["filter"]))
    reg.register(Tool("system.read_config", "Lendo arquivo de configuração",
                      "Lê um arquivo de configuração em /etc, ~/.config, /proc/cmdline ou do "
                      "bootloader (arquivos com senhas/chaves são bloqueados). Em diretório, lista.",
                      t_read_config, params={"path": P("string", "caminho do arquivo",
                                                       pattern=r"[~/][^\0]{0,255}")},
                      required=["path"]))
    reg.register(Tool("system.boot", "Verificando o boot",
                      "Firmware (UEFI/BIOS), bootloader (GRUB/Limine), linha de comando do kernel, "
                      "kernel em uso e instalados.", t_boot, domain="boot"))
    reg.register(Tool("system.command", "Procurando o comando",
                      "Se um comando está instalado, onde, e qual pacote o fornece.", t_command,
                      params={"name": P("string", "nome do comando", pattern=r"[A-Za-z0-9._+-]{1,64}")},
                      required=["name"]))


def register_checks(reg):
    for nome, rot, _k in STEPS:
        reg.register(Tool(nome, rot, rot, globals()[nome.split(".", 1)[1]], llm=False, internal=True))
