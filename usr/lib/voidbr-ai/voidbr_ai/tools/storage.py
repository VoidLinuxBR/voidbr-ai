# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/storage.py - discos e espaço
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Discos: uso de espaço (df), dispositivos (lsblk), maiores diretórios (du)
e o que dá para limpar no VoidBR (cache do xbps, kernels antigos, órfãos)."""

import json
import os

from ..util import run
from . import packages as pkgs
from .registry import P, Tool

IGNORAR_FS = {"tmpfs", "devtmpfs", "efivarfs", "overlay", "squashfs", "proc", "sysfs",
              "cgroup", "cgroup2", "devpts", "ramfs", "autofs", "fuse.portal", "nsfs"}


def _df(inodes=False):
    r = run(["df", "-PT"] + (["-i"] if inodes else ["-k"]), timeout=15)
    itens = []
    for linha in r["out"].splitlines()[1:]:
        p = linha.split()
        if len(p) < 7 or p[1] in IGNORAR_FS:
            continue
        try:
            total, usado, livre = int(p[2]), int(p[3]), int(p[4])
            pct = int(p[5].rstrip("%")) if p[5] != "-" else 0
        except ValueError:
            continue
        if total == 0:
            continue
        itens.append({"device": p[0], "fstype": p[1], "mount": " ".join(p[6:]),
                      "total": total, "used": usado, "free": livre, "percent": pct})
    return itens


def t_usage():
    blocos = _df()
    inodes = {i["mount"]: i["percent"] for i in _df(inodes=True)}
    vistos, itens = set(), []
    for b in blocos:
        chave = (b["device"], b["fstype"])
        if b["fstype"] == "btrfs" and chave in vistos:
            continue            # subvolumes do mesmo btrfs: mostra um só
        vistos.add(chave)
        itens.append({"mount": b["mount"], "device": b["device"], "fstype": b["fstype"],
                      "size_gb": round(b["total"] / 1048576, 1),
                      "free_gb": round(b["free"] / 1048576, 1), "used_percent": b["percent"],
                      "inodes_percent": inodes.get(b["mount"])})
    return {"filesystems": itens}


def t_devices():
    r = run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL,MODEL,RM,TRAN"],
            timeout=15)
    try:
        return json.loads(r["out"])
    except ValueError:
        return {"error": (r["err"] or "lsblk falhou").strip()}


def t_largest(path="/", limit=15):
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return {"error": f"{path} não é um diretório"}
    r = run(["du", "-x", "-k", "-d", "1", path], timeout=120)
    itens = []
    for linha in r["out"].splitlines():
        p = linha.split("\t", 1)
        if len(p) == 2 and p[1] != path:
            try:
                itens.append({"path": p[1], "size_mb": round(int(p[0]) / 1024)})
            except ValueError:
                pass
    itens.sort(key=lambda i: i["size_mb"], reverse=True)
    res = {"path": path, "largest": itens[:limit]}
    if r["timeout"]:
        res["note"] = "o du demorou demais; resultado parcial"
    elif r["err"]:
        res["note"] = "alguns diretórios não puderam ser lidos (sem permissão)"
    return res


# ---------------------------------------------------------------------------
# check-up
# ---------------------------------------------------------------------------

def c_usage(state=None, cfg=None):
    u = t_usage()
    cheios = [f"{f['mount']} {f['used_percent']}%" for f in u["filesystems"] if f["used_percent"] >= 85]
    raiz = next((f for f in u["filesystems"] if f["mount"] == "/"), None)
    u["summary"] = ("quase cheio: " + ", ".join(cheios)) if cheios else \
        (f"/ com {raiz['free_gb']} GB livres" if raiz else "ok")
    u["status"] = "fail" if any(f["used_percent"] >= 95 for f in u["filesystems"]) else \
        "warn" if cheios else "ok"
    return u


def c_cleanup(state=None, cfg=None):
    total, n = pkgs.cache_size()
    k = pkgs.kernels()
    d = {"cache_mb": round(total / 1048576), "cache_files": n, "kernels": k}
    partes = [f"cache do xbps {d['cache_mb']} MB"]
    if k["removable"]:
        partes.append(f"{len(k['removable'])} kernel(s) antigo(s)")
    d.update(summary=", ".join(partes), status="info")
    return d


STEPS = [
    ("storage.c_usage", "Verificando espaço em disco", "usage"),
    ("storage.c_cleanup", "Procurando o que dá para limpar", "cleanup"),
]
KEYWORDS = ["disco", "espaco", "cheio", "armazenamento", "hd", "ssd", "particao", "particoes",
            "storage", "df", "limpar", "limpeza", "lotado", "memoria cheia", "gb", "nvme"]


def _achado(code, sev, title, detail="", step="", sug=None):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": step,
            "confirmed": True, "suggestions": sug or []}


def analyze(state, reg):
    achados, acoes = [], []

    def acao(tool, reason, fixes):
        try:
            acoes.append(reg.make_action(tool, {}, reason=reason, fixes=fixes))
        except ValueError:
            pass

    fss = state.get("usage", {}).get("filesystems", [])
    cheio_raiz = False
    for f in fss:
        pct, m = f["used_percent"], f["mount"]
        if pct >= 85:
            sev = "erro" if pct >= 95 else "aviso"
            achados.append(_achado(f"disk_full:{m}", sev, f"{m} está {pct}% cheio",
                                   f"{f['free_gb']} GB livres de {f['size_gb']} GB ({f['fstype']}).",
                                   "usage", [f"Maiores diretórios: du -xh -d1 {m} | sort -h | tail"]))
            if m in ("/", "/var", "/usr"):
                cheio_raiz = True
        if (f.get("inodes_percent") or 0) >= 90:
            achados.append(_achado(f"inodes_full:{m}", "aviso", f"{m} está sem inodes livres",
                                   f"{f['inodes_percent']}% dos inodes em uso: muitos arquivos "
                                   "pequenos, mesmo com espaço sobrando.", "usage"))
    if fss and not achados:
        raiz = next((f for f in fss if f["mount"] == "/"), fss[0])
        achados.append(_achado("disk_ok", "ok", "Há espaço em disco",
                               f"{raiz['mount']}: {raiz['free_gb']} GB livres "
                               f"({100 - raiz['used_percent']}%).", "usage"))

    lim = state.get("cleanup", {})
    if lim.get("cache_mb", 0) >= 500:
        sev = "aviso" if cheio_raiz else "info"
        achados.append(_achado("xbps_cache", sev, f"Cache do xbps com {lim['cache_mb']} MB",
                               "Pacotes baixados em /var/cache/xbps; os de versões antigas podem sair.",
                               "cleanup"))
        acao("pkg.clean_cache", "libera espaço no /var/cache/xbps", ["xbps_cache"])
    antigos = lim.get("kernels", {}).get("removable", [])
    if antigos:
        sev = "aviso" if cheio_raiz else "info"
        achados.append(_achado("old_kernels", sev, f"{len(antigos)} kernel(s) antigo(s) instalado(s)",
                               f"Em uso: {lim['kernels']['running']}. Antigos: {', '.join(antigos)}.",
                               "cleanup"))
        acao("kernel.purge", "libera espaço em /boot e /usr/lib/modules", ["old_kernels"])
    return achados, acoes


def register(reg):
    reg.register(Tool("disk.usage", "Verificando espaço em disco",
                      "Uso de espaço e de inodes de cada sistema de arquivos montado.",
                      t_usage, domain="storage"))
    reg.register(Tool("disk.devices", "Listando discos",
                      "Discos e partições (lsblk): tamanho, tipo, sistema de arquivos, ponto de "
                      "montagem, modelo, removível.", t_devices, domain="storage"))
    reg.register(Tool("disk.largest", "Procurando os maiores diretórios",
                      "Os maiores subdiretórios de um diretório (du -x, um nível).", t_largest,
                      domain="storage", params={
                          "path": P("string", "diretório absoluto (ex: /, /var, /home/usuario)",
                                    pattern=r"/[^\0]{0,255}"),
                          "limit": P("integer", "quantos mostrar", minimum=5, maximum=40)}))


def register_checks(reg):
    for nome, rot, _k in STEPS:
        reg.register(Tool(nome, rot, rot, globals()[nome.split(".", 1)[1]], domain="storage",
                          llm=False, internal=True))
