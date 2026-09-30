# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/packages.py - pacotes (xbps)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Pacotes via xbps.

Leitura (como o usuário): xbps-query (buscar, info, arquivos, dono de um
arquivo, órfãos, repositórios) e xbps-install -Mun (atualizações pendentes,
dry-run com sincronização só em memória — não precisa de root).

Ações (root, confirmadas): instalar, remover, atualizar o sistema, limpar o
cache, remover órfãos e kernels antigos (vkpurge). O helper usa o
xbps-install/xbps-remove direto (o vinstall é interativo e chama sudo).
"""

import os
import re

from ..util import run, which
from .privileged import run_helper
from .registry import P, Tool

RE_PKG = r"[A-Za-z0-9][A-Za-z0-9._+-]{0,99}"
CACHE = "/var/cache/xbps"

# mesma lista do helper (lá é a que vale; aqui só para avisar antes)
PROTEGIDOS = {"base-system", "base-files", "base-container", "base-minimal", "xbps",
              "voidbr-xbps", "runit", "runit-void", "glibc", "musl", "linux", "linux-base",
              "bash", "coreutils", "shadow", "sudo", "util-linux", "eudev", "dbus", "polkit",
              "voidbr-ai"}


def _nome(pkgver):
    """'firefox-130.0_1' -> 'firefox'."""
    m = re.match(r"^(.+)-[^-]+_\d+$", pkgver)
    return m.group(1) if m else pkgver


def installed(name):
    return run(["xbps-query", name], timeout=10)["rc"] == 0


def in_repo(name):
    return run(["xbps-query", "-R", name], timeout=30)["rc"] == 0


def _kv(texto):
    d = {}
    for linha in texto.splitlines():
        if ":" in linha and not linha.startswith(" "):
            k, v = linha.split(":", 1)
            d[k.strip()] = v.strip()
    return d


# ---------------------------------------------------------------------------
# leitura
# ---------------------------------------------------------------------------

def t_search(query):
    r = run(["xbps-query", "-Rs", query], timeout=60)
    itens = []
    for linha in r["out"].splitlines():
        m = re.match(r"^\[(.)\]\s+(\S+)\s+(.*)$", linha)
        if m:
            itens.append({"installed": m.group(1) == "*", "pkgver": m.group(2),
                          "name": _nome(m.group(2)), "desc": m.group(3).strip()})
    res = {"query": query, "results": itens[:40], "total": len(itens)}
    if r["rc"] not in (0, 2) and not itens:
        res["error"] = (r["err"] or r["out"]).strip()[:300] or "xbps-query falhou"
    return res


def t_info(name):
    local = run(["xbps-query", name], timeout=10)
    if local["rc"] == 0:
        d = _kv(local["out"])
        d["installed"] = True
    else:
        rem = run(["xbps-query", "-R", name], timeout=60)
        if rem["rc"] != 0:
            return {"name": name, "found": False,
                    "note": "não existe no repositório (tente pkg.search)"}
        d = _kv(rem["out"])
        d["installed"] = False
    campos = ("pkgver", "short_desc", "homepage", "license", "installed_size",
              "filename-size", "repository", "install-date", "automatic-install", "state")
    info = {k: d[k] for k in campos if k in d}
    info.update(name=name, found=True, installed=d["installed"])
    dep = run(["xbps-query", "-x", name] if d["installed"] else ["xbps-query", "-Rx", name], timeout=30)
    info["depends"] = dep["out"].split()[:40]
    if d["installed"]:
        rev = run(["xbps-query", "-X", name], timeout=10)
        info["required_by"] = rev["out"].split()[:40]
    return info


def t_files(name, limit=80):
    r = run(["xbps-query", "-f", name], timeout=10)
    if r["rc"] != 0:
        return {"name": name, "error": "pacote não instalado"}
    arqs = [l.split(" -> ")[0] for l in r["out"].splitlines()]
    return {"name": name, "files": arqs[:limit], "total": len(arqs)}


def t_owner(path):
    r = run(["xbps-query", "-o", path], timeout=20)
    donos = sorted({_nome(l.split(":", 1)[0].strip()) for l in r["out"].splitlines() if ":" in l})
    return {"path": path, "packages": donos}


def t_installed(filter=""):
    r = run(["xbps-query", "-l"], timeout=20)
    itens = []
    for linha in r["out"].splitlines():
        p = linha.split(None, 2)
        if len(p) >= 2:
            n = _nome(p[1])
            if not filter or filter.lower() in n.lower():
                itens.append(p[1])
    return {"filter": filter, "packages": itens[:80], "total": len(itens)}


def t_updates():
    r = run(["xbps-install", "-Mun"], timeout=180)
    itens = []
    for linha in r["out"].splitlines():
        p = linha.split()
        if len(p) >= 2 and p[1] in ("update", "install", "remove", "configure", "hold"):
            itens.append({"pkgver": p[0], "name": _nome(p[0]), "action": p[1]})
    res = {"updates": itens[:100], "total": len(itens)}
    if r["rc"] not in (0,) and not itens:
        erro = (r["err"] or r["out"]).strip()
        if "must be updated" in erro:
            res.update(total=1, updates=[{"name": "xbps", "action": "update"}],
                       note="o próprio xbps precisa ser atualizado primeiro")
        else:
            res["error"] = erro[:300] or f"xbps-install -Mun falhou (rc {r['rc']})"
    return res


def t_orphans():
    r = run(["xbps-query", "-O"], timeout=20)
    return {"orphans": r["out"].split()[:80], "total": len(r["out"].split())}


def t_repos():
    r = run(["xbps-query", "-L"], timeout=20)
    repos = []
    for linha in r["out"].splitlines():
        p = linha.split()
        if len(p) >= 2:
            try:
                n = int(p[0])
            except ValueError:
                continue
            repos.append({"packages": n, "url": p[1], "signed": "signed" in linha.lower()})
    return {"repositories": repos}


def cache_size():
    total, n = 0, 0
    try:
        for f in os.scandir(CACHE):
            if f.is_file():
                total += f.stat().st_size
                n += 1
    except OSError:
        pass
    return total, n


def t_cache():
    total, n = cache_size()
    return {"path": CACHE, "files": n, "size_mb": round(total / 1048576)}


def kernels():
    atual = os.uname().release
    r = run(["vkpurge", "list"], timeout=20)
    antigos = [k for k in r["out"].split() if k and k != atual]
    try:
        todos = sorted(os.listdir("/usr/lib/modules"))
    except OSError:
        todos = []
    return {"running": atual, "installed": todos, "removable": antigos,
            "vkpurge": not r["missing"]}


def t_kernels():
    return kernels()


# ---------------------------------------------------------------------------
# ações
# ---------------------------------------------------------------------------

def _c_install(args):
    for p in args["packages"]:
        if installed(p):
            return f"{p} já está instalado"
        if not in_repo(p):
            return f"{p} não existe no repositório"
    return None


def _c_remove(args):
    for p in args["packages"]:
        if p in PROTEGIDOS:
            return f"{p} é essencial e não pode ser removido"
        if not installed(p):
            return f"{p} não está instalado"
    return None


def a_install(packages, on_line=None):
    return run_helper("pkg-install", *packages, timeout=3600, on_line=on_line)


def a_remove(packages, on_line=None):
    return run_helper("pkg-remove", *packages, timeout=1800, on_line=on_line)


def a_update(on_line=None):
    return run_helper("system-update", timeout=7200, on_line=on_line)


def a_clean_cache(on_line=None):
    return run_helper("pkg-clean-cache", timeout=600, on_line=on_line)


def a_orphans(on_line=None):
    return run_helper("pkg-remove-orphans", timeout=1800, on_line=on_line)


def a_kernel_purge(on_line=None):
    return run_helper("kernel-purge", timeout=1800, on_line=on_line)


def _v_install(packages):
    faltam = [p for p in packages if not installed(p)]
    return not faltam, ("instalado: " + ", ".join(packages)) if not faltam \
        else ("não instalado: " + ", ".join(faltam))


def _v_remove(packages):
    ficaram = [p for p in packages if installed(p)]
    return not ficaram, ("removido: " + ", ".join(packages)) if not ficaram \
        else ("continua instalado: " + ", ".join(ficaram))


def _v_update():
    u = t_updates()
    if u.get("error"):
        return None, u["error"]
    return u["total"] == 0, "sistema atualizado" if u["total"] == 0 \
        else f"ainda há {u['total']} atualização(ões)"


def _v_cache():
    return True, f"cache do xbps agora com {t_cache()['size_mb']} MB"


def _v_orphans():
    n = t_orphans()["total"]
    return n == 0, "nenhum órfão" if n == 0 else f"ainda há {n} órfão(s)"


def _v_kernels():
    k = kernels()
    return not k["removable"], "só o kernel em uso ficou" if not k["removable"] \
        else "ainda há kernels antigos: " + ", ".join(k["removable"])


# ---------------------------------------------------------------------------
# check-up (sem LLM)
# ---------------------------------------------------------------------------

def c_updates(state=None, cfg=None):
    u = t_updates()
    if u.get("error"):
        u.update(summary="não foi possível consultar", status="info")
    else:
        u.update(summary=f"{u['total']} atualização(ões) pendente(s)" if u["total"] else "sistema em dia",
                 status="warn" if u["total"] else "ok")
    return u


def c_repos(state=None, cfg=None):
    if not which("xbps-query"):
        return {"missing": True, "repositories": [], "summary": "xbps não encontrado", "status": "info"}
    r = t_repos()
    ruins = [x for x in r["repositories"] if x["packages"] <= 0]
    r.update(summary=f"{len(r['repositories'])} repositório(s)"
             + (f", {len(ruins)} sem índice" if ruins else ""),
             status="warn" if ruins or not r["repositories"] else "ok")
    return r


def c_orphans(state=None, cfg=None):
    o = t_orphans()
    o.update(summary=f"{o['total']} órfão(s)", status="info" if o["total"] else "ok")
    return o


STEPS = [
    ("packages.c_repos", "Verificando repositórios", "repos"),
    ("packages.c_updates", "Procurando atualizações", "updates"),
    ("packages.c_orphans", "Procurando pacotes órfãos", "orphans"),
]
KEYWORDS = ["pacote", "pacotes", "instalar", "instala", "remover", "desinstalar", "atualizar",
            "atualizacao", "atualizacoes", "update", "xbps", "vinstall", "repositorio", "programa",
            "aplicativo", "app"]


def _achado(code, sev, title, detail="", step=""):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": step,
            "confirmed": True, "suggestions": []}


def analyze(state, reg):
    achados, acoes = [], []

    def acao(tool, args, reason, fixes):
        try:
            acoes.append(reg.make_action(tool, args, reason=reason, fixes=fixes))
        except ValueError:
            pass

    rp = state.get("repos", {})
    if rp.get("missing"):
        return [_achado("no_xbps", "info", "xbps não encontrado neste sistema", "", "repos")], []
    if rp and not rp.get("repositories"):
        achados.append(_achado("no_repos", "erro", "Nenhum repositório configurado no xbps",
                               "Sem repositórios não dá para instalar nem atualizar.", "repos"))
    for x in rp.get("repositories", []):
        if x["packages"] <= 0:
            achados.append(_achado(f"repo_empty:{x['url']}", "aviso",
                                   f"Repositório sem índice: {x['url']}",
                                   "O índice não foi baixado (sem internet, espelho fora do ar ou "
                                   "chave não importada). Uma sincronização (xbps-install -S) resolve "
                                   "se o espelho estiver no ar.", "repos"))
    up = state.get("updates", {})
    if up.get("total"):
        nomes = ", ".join(u["name"] for u in up["updates"][:8])
        achados.append(_achado("updates", "aviso", f"{up['total']} atualização(ões) pendente(s)",
                               f"{nomes}{'…' if up['total'] > 8 else ''}", "updates"))
        acao("system.update", {}, "atualizações pendentes", ["updates"])
    elif up and not up.get("error"):
        achados.append(_achado("updates_ok", "ok", "O sistema está atualizado", "", "updates"))
    orf = state.get("orphans", {})
    if orf.get("total"):
        achados.append(_achado("orphans", "info", f"{orf['total']} pacote(s) órfão(s)",
                               "Dependências que nenhum pacote usa mais: "
                               + ", ".join(orf["orphans"][:8]), "orphans"))
        acao("pkg.remove_orphans", {}, "pacotes que nada mais usa", ["orphans"])
    return achados, acoes


def register(reg):
    pk = P("string", "nome exato do pacote", pattern=RE_PKG)
    lista = P("array", "nomes exatos dos pacotes", items={"type": "string", "pattern": RE_PKG},
              maxItems=20)
    reg.register(Tool("pkg.search", "Buscando pacotes",
                      "Busca pacotes no repositório pelo nome/descrição (xbps-query -Rs). "
                      "Use para descobrir o nome exato de um programa.", t_search, domain="packages",
                      params={"query": P("string", "termo de busca", maxLength=60)}, required=["query"]))
    reg.register(Tool("pkg.info", "Consultando pacote",
                      "Informações de um pacote (instalado ou do repositório): versão, descrição, "
                      "dependências e quem depende dele.", t_info, domain="packages",
                      params={"name": pk}, required=["name"]))
    reg.register(Tool("pkg.files", "Listando arquivos do pacote",
                      "Arquivos instalados por um pacote.", t_files, domain="packages",
                      params={"name": pk}, required=["name"]))
    reg.register(Tool("pkg.owner", "Procurando o dono do arquivo",
                      "Qual pacote instalado fornece um arquivo (ex: /usr/bin/ffmpeg).", t_owner,
                      domain="packages", params={"path": P("string", "caminho absoluto",
                                                           pattern=r"/[^\0]{0,255}")},
                      required=["path"]))
    reg.register(Tool("pkg.installed", "Listando pacotes instalados",
                      "Pacotes instalados, opcionalmente filtrando por parte do nome.", t_installed,
                      domain="packages", params={"filter": P("string", "parte do nome", maxLength=60)}))
    reg.register(Tool("pkg.updates", "Procurando atualizações",
                      "Atualizações pendentes do sistema (sem instalar nada).", t_updates,
                      domain="packages"))
    reg.register(Tool("pkg.orphans", "Procurando órfãos",
                      "Pacotes órfãos (dependências que nada mais usa).", t_orphans, domain="packages"))
    reg.register(Tool("pkg.repos", "Consultando repositórios",
                      "Repositórios configurados e quantos pacotes cada um tem no índice.",
                      t_repos, domain="packages"))
    reg.register(Tool("pkg.cache", "Medindo o cache do xbps",
                      "Tamanho do cache de pacotes baixados (/var/cache/xbps).", t_cache,
                      domain="packages"))
    reg.register(Tool("kernel.list", "Listando kernels",
                      "Kernel em uso, kernels instalados e os antigos que podem ser removidos.",
                      t_kernels, domain="packages"))

    reg.register(Tool("pkg.install", "Instalar pacotes",
                      "Instala pacotes do repositório (nomes exatos; confira com pkg.search).",
                      a_install, kind="action", domain="packages", params={"packages": lista},
                      required=["packages"], check=_c_install, title="Instalar {packages}",
                      preview=lambda packages: "xbps-install -Sy " + " ".join(packages),
                      verify=_v_install))
    reg.register(Tool("pkg.remove", "Remover pacotes",
                      "Remove pacotes instalados (falha se outro pacote depender deles).",
                      a_remove, kind="action", domain="packages", params={"packages": lista},
                      required=["packages"], check=_c_remove, title="Remover {packages}",
                      preview=lambda packages: "xbps-remove -y " + " ".join(packages),
                      verify=_v_remove,
                      risk="Os programas desses pacotes deixam de funcionar."))
    reg.register(Tool("system.update", "Atualizar o sistema",
                      "Atualiza todos os pacotes (primeiro o xbps, depois o resto).", a_update,
                      kind="action", domain="packages", title="Atualizar o sistema",
                      preview=lambda: "xbps-install -Syu xbps  &&  xbps-install -yu",
                      verify=_v_update,
                      risk="Pode demorar e baixar bastante. Se o kernel for atualizado, reinicie depois."))
    reg.register(Tool("pkg.clean_cache", "Limpar o cache do xbps",
                      "Apaga do cache os pacotes baixados que não são mais a versão atual.",
                      a_clean_cache, kind="action", domain="packages",
                      title="Limpar o cache do xbps", preview=lambda: "xbps-remove -yO",
                      verify=_v_cache))
    reg.register(Tool("pkg.remove_orphans", "Remover pacotes órfãos",
                      "Remove dependências que nenhum pacote instalado usa mais.", a_orphans,
                      kind="action", domain="packages", title="Remover pacotes órfãos",
                      preview=lambda: "xbps-remove -yo", verify=_v_orphans))
    reg.register(Tool("kernel.purge", "Remover kernels antigos",
                      "Remove os kernels antigos, mantendo o que está em uso (vkpurge).",
                      a_kernel_purge, kind="action", domain="packages",
                      title="Remover kernels antigos", preview=lambda: "vkpurge rm all",
                      verify=_v_kernels,
                      risk="O kernel em uso fica; os antigos saem do menu de boot."))


def register_checks(reg):
    for nome, rot, _k in STEPS:
        reg.register(Tool(nome, rot, rot, globals()[nome.split(".", 1)[1]], domain="packages",
                          llm=False, internal=True))


def available():
    return bool(which("xbps-query"))
