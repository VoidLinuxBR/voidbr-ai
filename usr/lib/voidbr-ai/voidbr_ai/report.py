# -*- coding: utf-8 -*-
#
#   voidbr_ai/report.py - relatório para compartilhar (fórum, grupo, issue)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Gera um relatório em Markdown de uma sessão (diagnóstico, check-up,
pergunta ou análise de comando), pronto para colar num fórum ou grupo.

Antes de sair, o texto passa por redigir(): some com o que identifica você
ou a sua rede (IP público, IPv6 global, MAC, nome da rede Wi-Fi, nome da
máquina, nome de usuário e caminhos da sua pasta, e-mails). IPs de rede
local (192.168.x, 10.x, 172.16-31.x) ficam, porque ajudam no diagnóstico.
"""

import ipaddress
import os
import pwd
import re
import socket

from . import APP_VERSION

ICONE = {"erro": "❌", "aviso": "⚠️", "info": "ℹ️", "ok": "✅"}
RE_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RE_IPV6 = re.compile(r"(?<![\w:])[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,7}(?![\w:])")
RE_MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def _ssids(obj, achados=None):
    """Nomes de redes Wi-Fi guardados no estado coletado (chaves ssid/SSID/connection)."""
    achados = achados if achados is not None else set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and k.lower() in ("ssid", "essid", "network_name") and len(v) >= 2:
                achados.add(v)
            else:
                _ssids(v, achados)
    elif isinstance(obj, list):
        for v in obj:
            _ssids(v, achados)
    return achados


def _ip4(m):
    ip = m.group(0)
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if a.is_private or a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast:
        return ip
    if ip in ("1.1.1.1", "8.8.8.8", "8.8.4.4", "9.9.9.9", "1.0.0.1"):   # DNS públicos conhecidos
        return ip
    return "x.x.x.x"


def _ip6(m):
    ip = m.group(0)
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if a.is_loopback or a.is_link_local or a.is_private or a.is_multicast:
        return ip
    return "<ipv6>"


def redigir(texto, extras=()):
    """Tira do texto o que identifica o usuário ou a rede dele."""
    t = RE_MAC.sub("xx:xx:xx:xx:xx:xx", texto)
    t = RE_IPV4.sub(_ip4, t)
    t = RE_IPV6.sub(_ip6, t)
    t = RE_EMAIL.sub("<email>", t)
    for s in sorted({x for x in extras if x}, key=len, reverse=True):
        t = t.replace(s, "<rede wifi>")
    try:
        usuario = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        usuario = os.environ.get("USER", "")
    casa = os.path.expanduser("~")
    if casa not in ("/", "/root", ""):
        t = t.replace(casa, "/home/<usuario>")
    if usuario and len(usuario) >= 3 and usuario not in ("root", "user"):
        t = re.sub(rf"\b{re.escape(usuario)}\b", "<usuario>", t)
    host = socket.gethostname()
    if host and len(host) >= 3 and host not in ("localhost", "void", "voidbr"):
        t = re.sub(rf"\b{re.escape(host)}\b", "<host>", t)
    return t


def markdown(d, state=None):
    """d = Report.to_dict() (ou uma sessão do histórico)."""
    ln = []
    ctx = d.get("context") or {}
    ln.append("## 🔵 Relatório do VoidBR AI")
    ln.append("")
    ln.append(f"- **Data:** {d.get('time', '')}   **VoidBR AI:** {d.get('version') or APP_VERSION}")
    if ctx:
        di = ctx.get("distro") or {}
        de = ctx.get("desktop") or {}
        partes = [di.get("name"), f"kernel {ctx.get('kernel')}" if ctx.get("kernel") else None,
                  ctx.get("arch"), (ctx.get("init") or {}).get("service_manager"),
                  " ".join(x for x in (de.get("session"), de.get("desktop")) if x) or None]
        ln.append("- **Sistema:** " + ", ".join(p for p in partes if p))
    if d.get("question"):
        q = d["question"].strip()
        if "\n" in q or d.get("domain") == "explain":
            ln += ["- **Pergunta / texto analisado:**", "", "```", q[:2000], "```"]
        else:
            ln.append(f"- **Pergunta:** {q}")
    ln.append("")
    ln.append(f"### {'Resposta' if d.get('mode') == 'llm' else 'Diagnóstico'}")
    ln.append("")
    ln.append(d.get("summary", "").strip() or "-")
    llm = d.get("llm") or {}
    if llm.get("explicacao"):
        ln += ["", llm["explicacao"].strip()]
    achados = d.get("findings") or []
    conf = [f for f in achados if f.get("confirmed", True)]
    hip = [f for f in achados if not f.get("confirmed", True)]
    if conf:
        ln += ["", "### Análise automática (nada foi executado)" if d.get("domain") == "explain"
               else "### Encontrado (confirmado pelos dados)", ""]
        for f in conf:
            linha = f"- {ICONE.get(f.get('severity'), '•')} {f.get('title', '')}"
            if f.get("detail"):
                det = f["detail"].strip().replace("\n", "\n  ")
                linha += f"\n  {det}"
            ln.append(linha)
    if hip or llm.get("hipoteses"):
        ln += ["", "### Hipóteses (não confirmadas)", ""]
        ln += [f"- {f.get('title', '')}" for f in hip]
        ln += [f"- {h}" for h in llm.get("hipoteses", []) if h not in {f.get('title') for f in hip}]
    if llm.get("sugestoes"):
        ln += ["", "### Sugestões", ""] + [f"- `{s}`" for s in llm["sugestoes"]]
    acoes = d.get("actions") or []
    if acoes:
        ln += ["", "### Correções propostas", ""]
        ln += [f"- {a.get('title', '')}: `{a.get('command', '')}`" for a in acoes]
    execs = d.get("executions") or []
    if execs:
        ln += ["", "### O que foi executado", ""]
        for e in execs:
            a = e.get("action") or {}
            st = "✅ resolvido" if e.get("resolved") else "❌ não resolveu" if e.get("resolved") is False \
                else ("⏹️ cancelado" if e.get("cancelled") else ("executado" if e.get("ok") else "❌ falhou"))
            ln.append(f"- `{a.get('command', '')}` → {st}" +
                      (f" (snapshot {e['snapshot']} antes)" if e.get("snapshot") else ""))
    consultas = [c.get("tool") for c in d.get("tool_calls") or []]
    if consultas:
        ln += ["", f"<sub>Consultas ao sistema: {', '.join(consultas)}</sub>"]
    if d.get("provider"):
        ln += ["", f"<sub>IA: {d['provider']}</sub>"]
    ln += ["", "<sub>Gerado pelo VoidBR AI. Dados pessoais (IP público, MAC, rede Wi-Fi, "
           "usuário, máquina) foram ocultados.</sub>"]
    return redigir("\n".join(ln), _ssids(state or d.get("state") or {}))
