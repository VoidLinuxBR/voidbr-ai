# -*- coding: utf-8 -*-
#
#   voidbr_ai/kb.py - base de conhecimento local do VoidBR
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Base de conhecimento local: trechos do Void Handbook e das ferramentas do
VoidBR (vinstall, vservice, pkgmake) em /usr/share/voidbr-ai/kb/*.md.

Cada arquivo tem seções "## título" + "fonte: URL" + linhas curtas. A busca é
por palavras (sem acento, sem palavras vazias), com peso maior para o título
e o nome do arquivo. Funciona sem internet e sem IA: a IA recebe os trechos
mais relevantes junto da pergunta, e sem IA eles são mostrados direto.
"""

import glob
import math
import os
import re
import unicodedata

# instalado: /usr/share/voidbr-ai/kb ; no repositório: <repo>/usr/share/voidbr-ai/kb
_AQUI = os.path.dirname(os.path.abspath(__file__))
DIRS = [os.path.normpath(os.path.join(_AQUI, "..", "..", "..", "share", "voidbr-ai", "kb")),
        "/usr/share/voidbr-ai/kb", "/etc/voidbr-ai/kb"]

VAZIAS = set("""a o as os um uma uns umas de da do das dos em no na nos nas para pra por
pelo pela com sem que e ou se como qual quais quando onde meu minha meus minhas seu sua
eu voce isso este esta esse essa ao aos à às é eh ser ter tem tenho nao não mais muito
faz fazer faco faço sobre ja já tambem também porque pois me te lhe""".split())

# palavras do dia a dia -> termos que aparecem nas notas
SINONIMOS = {
    "som": ["audio", "pipewire"], "caixa": ["audio"], "microfone": ["audio", "pipewire"],
    "wifi": ["rede", "wi-fi", "iwd", "networkmanager"], "internet": ["rede", "dhcpcd"],
    "placa": ["video"], "tela": ["video", "wayland"], "driver": ["video", "firmware"],
    "nvidia": ["nvidia", "video"], "amd": ["amd", "video"], "intel": ["intel", "video"],
    "servico": ["runit", "sv"], "servicos": ["runit", "sv"], "iniciar": ["runit", "sv"],
    "instalar": ["xbps", "vinstall"], "pacote": ["xbps", "vinstall"], "pacotes": ["xbps", "vinstall"],
    "atualizar": ["xbps", "vinstall"], "atualizacao": ["xbps"], "remover": ["xbps", "vinstall"],
    "desinstalar": ["xbps", "vinstall"], "kernel": ["kernel", "dracut"], "initramfs": ["dracut"],
    "boot": ["grub", "boot"], "inicializacao": ["boot", "grub"], "grub": ["grub"],
    "log": ["socklog", "logs"], "logs": ["socklog"], "hora": ["ntp", "horario"],
    "relogio": ["horario", "ntp"], "data": ["horario"], "idioma": ["locale", "locales"],
    "teclado": ["locale", "keymap"], "usuario": ["usuarios", "grupo"], "grupo": ["usuarios"],
    "suspender": ["energia", "zzz"], "bateria": ["energia", "tlp"], "energia": ["energia", "acpid"],
    "bluetooth": ["bluetooth", "bluez"], "fone": ["bluetooth", "audio"],
    "sessao": ["sessao", "elogind", "seatd"], "wayland": ["wayland", "seatd", "elogind"],
    "portal": ["portais", "xdg-desktop-portal"], "compilar": ["pkgmake"], "empacotar": ["pkgmake"],
}


def _norm(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _palavras(t):
    return [p for p in re.findall(r"[a-z0-9][a-z0-9_.+-]*", _norm(t)) if p not in VAZIAS and len(p) > 1]


_cache = None


def secoes():
    """[{arquivo, titulo, fonte, texto, _tokens, _titulo}] de todos os .md."""
    global _cache
    if _cache is not None:
        return _cache
    vistos, itens = set(), []
    for d in DIRS:
        for arq in sorted(glob.glob(os.path.join(d, "*.md"))):
            nome = os.path.basename(arq)
            if nome in vistos:
                continue
            vistos.add(nome)
            try:
                with open(arq, encoding="utf-8") as f:
                    conteudo = f.read()
            except OSError:
                continue
            for bloco in re.split(r"(?m)^## ", conteudo):
                bloco = bloco.strip()
                if not bloco:
                    continue
                linhas = bloco.splitlines()
                titulo = linhas[0].strip()
                fonte = ""
                corpo = []
                for l in linhas[1:]:
                    if l.startswith("fonte:") and not fonte:
                        fonte = l.split(":", 1)[1].strip()
                    else:
                        corpo.append(l)
                texto = "\n".join(corpo).strip()
                itens.append({"arquivo": nome, "titulo": titulo, "fonte": fonte, "texto": texto,
                              "_tokens": _palavras(texto),
                              "_titulo": set(_palavras(titulo + " " + nome[:-3]))})
    _cache = itens
    return itens


def search(query, limit=3, minimo=1.5):
    """Seções mais relevantes para a pergunta: [{titulo, fonte, texto, arquivo, score}]."""
    itens = secoes()
    if not itens:
        return []
    termos = _palavras(query)
    for t in list(termos):
        termos += SINONIMOS.get(t, [])
    if not termos:
        return []
    n = len(itens)
    df = {}
    for it in itens:
        for t in set(it["_tokens"]) | it["_titulo"]:
            df[t] = df.get(t, 0) + 1
    res = []
    for it in itens:
        score = 0.0
        for t in set(termos):
            idf = math.log(1 + n / (1 + df.get(t, 0)))
            tf = it["_tokens"].count(t)
            if tf:
                score += (1 + math.log(tf)) * idf
            if t in it["_titulo"]:
                score += 2.5 * idf
        if score >= minimo:
            res.append({"titulo": it["titulo"], "fonte": it["fonte"], "texto": it["texto"],
                        "arquivo": it["arquivo"], "score": round(score, 2)})
    res.sort(key=lambda r: r["score"], reverse=True)
    return res[:limit]


def contexto(query, limite_chars=1800, limit=3):
    """Texto com os trechos relevantes para colocar no prompt da IA ("" se nada)."""
    partes, total = [], 0
    for r in search(query, limit=limit):
        bloco = f"### {r['titulo']} (fonte: {r['fonte']})\n{r['texto']}"
        if total + len(bloco) > limite_chars:
            bloco = bloco[:max(0, limite_chars - total)]
        if len(bloco) < 80:
            break
        partes.append(bloco)
        total += len(bloco)
    return "\n\n".join(partes)


def t_search(query, limit=3):
    """Ferramenta para o LLM."""
    r = search(query, limit=int(limit or 3), minimo=1.0)
    return {"results": [{k: x[k] for k in ("titulo", "fonte", "texto")} for x in r],
            "total": len(r)}


def register(reg):
    from .tools.registry import P, Tool
    reg.register(Tool("kb.search", "Consultando a documentação do VoidBR",
                      "Busca na documentação local do Void/VoidBR (Void Handbook, runit, xbps, "
                      "vinstall, vservice, pkgmake, áudio, vídeo, rede, boot, logs...). Use para "
                      "confirmar comandos e nomes de pacotes antes de responder.",
                      t_search, domain="kb",
                      params={"query": P("string", "o que procurar (palavras-chave)", maxLength=200),
                              "limit": P("integer", "quantos trechos", minimum=1, maximum=5)},
                      required=["query"]))
