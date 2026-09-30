# -*- coding: utf-8 -*-
#
#   voidbr_ai/cli/main.py - interface de linha de comando
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""voidbr-ai — CLI do VoidBR AI.

    voidbr-ai                                  modo interativo (conversa)
    voidbr-ai "como instalo o steam?"
    voidbr-ai --checkup                        check-up geral (sem IA)
    voidbr-ai --diagnose network [--json]      um domínio: network, storage, packages,
                                               services, audio, bluetooth, system
    voidbr-ai --setup-ai                       configura a IA local (Ollama)

Usa o mesmo Agent da GUI. Ações só rodam depois de confirmadas aqui.
"""

import argparse
import json
import os
import sys

from .. import APP_NAME, APP_VERSION, config, history, setup, tools
from ..agent import Agent

red = yellow = green = blue = cyan = bold = dim = reset = ""


def cores(ativar):
    global red, yellow, green, blue, cyan, bold, dim, reset
    if ativar:
        red, yellow, green = "\033[1;31m", "\033[1;33m", "\033[1;32m"
        blue, cyan = "\033[1;34m", "\033[1;36m"
        bold, dim, reset = "\033[1m", "\033[2m", "\033[0m"


ICONE = {"erro": "❌", "aviso": "⚠️ ", "info": "ℹ️ ", "ok": "✅"}
ICONE_STEP = {"ok": "✅", "warn": "⚠️ ", "fail": "❌", "info": "•"}


class Saida:
    """Mostra os eventos do Agent no terminal."""

    def __init__(self, silencioso=False):
        self.silencioso = silencioso
        self.fluxo = False           # escrevendo a resposta da IA ao vivo

    def __call__(self, ev):
        if self.silencioso:
            return
        if ev.kind == "stream":
            if not self.fluxo:
                self.fluxo = True
                print("\033[2K", end="", flush=True, file=sys.stderr)
                print(f"\n{bold}{cyan}🤖{reset} ", end="", flush=True)
            print(ev.label, end="", flush=True)
            return
        if self.fluxo:
            self.fluxo = False
            print("\n", flush=True)
        if ev.kind == "output":
            print(f"\033[2K    {dim}{ev.label[:110]}{reset}", end="\r", flush=True, file=sys.stderr)
            return
        if ev.kind == "info" and ev.id.startswith("hdr-"):
            print(f"\033[2K\n  {bold}{ev.label}{reset}", file=sys.stderr)
            return
        if ev.status == "running":
            print(f"\033[2K  {dim}● {ev.label}{reset}", end="\r", flush=True, file=sys.stderr)
            return
        cor = {"ok": green, "warn": yellow, "fail": red}.get(ev.status, cyan)
        resumo = f" {dim}— {ev.summary}{reset}" if ev.summary else ""
        print(f"\033[2K  {cor}{ICONE_STEP.get(ev.status, '•')}{reset} {ev.label}{resumo}",
              file=sys.stderr)


def mostrar(rep):
    print()
    l = rep.llm or {}
    if rep.mode == "llm":
        if not rep.streamed:         # já foi mostrada enquanto a IA escrevia
            print(f"{bold}{cyan}🤖 {rep.summary}{reset}")
        if l.get("explicacao"):
            print(f"   {l['explicacao']}")
        fatos = [f for f in rep.findings if f.get("confirmed", True)]
        hips = [f for f in rep.findings if not f.get("confirmed", True)]
        if fatos:
            print(f"\n{bold}🔎 Encontrado nos dados:{reset}")
            for f in fatos:
                print(f"  • {f['title']}")
        if hips:
            print(f"\n{bold}🤔 Hipóteses (não confirmadas):{reset}")
            for f in hips:
                print(f"  ? {f['title']}")
        for s in l.get("sugestoes", []):
            print(f"  → {s}")
    elif not rep.domain:
        print(f"{bold}{cyan}🤖 {rep.summary}{reset}")
    elif rep.domain == "info":
        print(f"{bold}{cyan}📖 {rep.summary}{reset}")
        for f in rep.findings:
            print(f"  • {f['title']}" + (f"\n     {dim}{f['detail']}{reset}" if f["detail"] else ""))
            for s in f.get("suggestions", []):
                print(f"     → {s}")
    else:
        print(f"{bold}🩺 Diagnóstico:{reset} {rep.summary}")
        print(f"\n{bold}🔎 O que foi encontrado (confirmado pelos dados):{reset}")
        for f in rep.findings:
            cor = {"erro": red, "aviso": yellow, "ok": green}.get(f["severity"], cyan)
            hip = f" {dim}[hipótese]{reset}" if not f.get("confirmed", True) else ""
            dom = f"{dim}[{tools.LABELS.get(f.get('domain'), '')}]{reset} " if rep.mode == "checkup" else ""
            print(f"  {ICONE.get(f['severity'], '•')} {dom}{cor}{f['title']}{reset}{hip}")
            if f["detail"]:
                print(f"     {dim}{f['detail']}{reset}")
            for s in f.get("suggestions", []):
                print(f"     → {s}")
        if l:
            print(f"\n{bold}🤖 Interpretação ({rep.provider}):{reset} {l['diagnostico']}")
            if l["explicacao"]:
                print(f"   {l['explicacao']}")
            for h in l["hipoteses"]:
                print(f"     ? {h}")
            for s in l["sugestoes"]:
                print(f"     → {s}")

    if rep.llm_error and not l and rep.provider:
        print(f"\n{dim}🤖 IA: {rep.llm_error}{reset}")
    if rep.needs_ai and rep.domain:
        print(f"\n{dim}💡 Com a IA configurada a resposta é sob medida: voidbr-ai --setup-ai{reset}")
    if rep.actions:
        print(f"\n{bold}🛠️  Ações propostas:{reset}")
        for n, a in enumerate(rep.actions, 1):
            quem = "IA" if a.source == "llm" else "regras"
            print(f"  {bold}{n}.{reset} {a.title}  {dim}({a.reason or quem}){reset}")
            print(f"     {cyan}$ {a.command}{reset}")
            if a.risk:
                print(f"     {yellow}⚠️  {a.risk}{reset}")


def perguntar(msg):
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def sim(msg):
    return (perguntar(msg) or "").lower() in ("s", "sim", "y", "yes")


def oferecer_acoes(agent, rep):
    while rep.actions:
        esc = perguntar(f"\nExecutar uma ação? [1-{len(rep.actions)}, Enter = não] ") or ""
        if not esc.isdigit() or not 1 <= int(esc) <= len(rep.actions):
            return
        a = rep.actions[int(esc) - 1]
        como = "como root, via pkexec" if a.root else "como o seu usuário"
        print(f"\n  Será executado ({como}):\n    {cyan}$ {a.command}{reset}")
        if a.risk:
            print(f"  {yellow}⚠️  {a.risk}{reset}")
        if not sim("  Confirma? [s/N] "):
            print("  Cancelado.")
            continue
        r = agent.execute(a, rep, confirmed=True)
        print("\033[2K", end="", file=sys.stderr)
        if r.cancelled:
            continue
        if not r.ok:
            print(f"\n{red}❌ Falhou:{reset}\n{dim}{r.output[-1500:]}{reset}")
            continue
        rep.actions = [x for x in rep.actions if x.id != a.id]
        if r.resolved:
            print(f"\n{green}✅ Resolvido.{reset} {r.after.summary if r.after else r.check}")
            if not r.after:
                continue
            return
        if r.resolved is False:
            print(f"\n{red}❌ Ainda não resolveu:{reset} "
                  + ("; ".join(f["title"] for f in r.remaining) or r.check))
            if r.after:
                rep.actions = [x for x in r.after.actions if x.id != a.id]
                rep.findings = r.after.findings
        if rep.actions:
            mostrar(rep)


def listar_ferramentas(agent):
    for t in sorted(agent.registry.list(), key=lambda t: (t.kind, t.name)):
        if not t.llm and t.kind == "read":
            continue
        tipo = f"{yellow}ação{reset}   " if t.kind == "action" else f"{green}leitura{reset}"
        off = f" {red}(desativada){reset}" if t.name in agent.registry.disabled else ""
        quem = "" if t.kind == "read" else (" [root]" if t.root else " [usuário]")
        print(f"  {tipo} {bold}{t.name}{reset}{quem}{off} — {t.description}")


def assistente_ia(agent):
    """--setup-ai: o mesmo assistente da GUI, no terminal."""
    hw = setup.hardware()
    st = setup.state(agent.cfg)
    print(f"\n{bold}🦙 IA local com o Ollama{reset}")
    print(f"  Memória: {setup.gb(hw['ram_gb'])} GB   Disco livre: {setup.gb(hw['free_disk_gb'])} GB   "
          f"Vídeo: {', '.join(hw['gpus']) or '?'}")
    sug = setup.recommend(hw)
    print("\n  Modelos:")
    for n, (tag, tam, _ram, desc) in enumerate(setup.MODELOS, 1):
        marca = f" {green}← sugerido{reset}" if tag == sug else ""
        print(f"   {n}. {tag:11} ~{setup.gb(tam):>4} GB  {dim}{desc}{reset}{marca}")
    esc = perguntar(f"\n  Qual? [1-{len(setup.MODELOS)}, Enter = {sug}] ") or ""
    modelo = setup.MODELOS[int(esc) - 1][0] if esc.isdigit() and 1 <= int(esc) <= len(setup.MODELOS) \
        else sug
    passos = setup.plan(st, modelo, hw)
    print(f"\n  {bold}Passos:{reset}")
    for _t, desc, cmd in passos:
        print(f"   • {desc}" + (f"\n       {cyan}$ {cmd}{reset}" if cmd else ""))
    if not sim("\n  Continuar? [s/N] "):
        print("  Cancelado.")
        return 1

    def prog(status, frac):
        barra = f" {frac * 100:5.1f}%" if frac is not None else ""
        print(f"\033[2K    {dim}{status}{barra}{reset}", end="\r", flush=True, file=sys.stderr)

    ok, msg = setup.run_setup(agent, modelo, prog, hw)
    print(f"\n{green if ok else red}{'✅' if ok else '❌'} {msg}{reset}")
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog=APP_NAME, description="VoidBR AI — ajuda e diagnóstico do sistema")
    p.add_argument("pergunta", nargs="*", help="sua pergunta ou o problema")
    p.add_argument("-c", "--checkup", action="store_true", help="check-up geral do sistema")
    p.add_argument("-d", "--diagnose", metavar="DOMINIO",
                   choices=sorted(tools.DOMAINS) + sorted(tools.ALIASES),
                   help="diagnóstico de um domínio: " + ", ".join(tools.DOMAINS))
    p.add_argument("--json", action="store_true", help="saída em JSON (sem perguntas)")
    p.add_argument("--no-llm", action="store_true", help="não usar a IA (só regras)")
    p.add_argument("--provider", choices=["none", "ollama", "openai"], help="sobrescreve a config")
    p.add_argument("--model", help="sobrescreve o modelo do provider")
    p.add_argument("--setup-ai", action="store_true", help="configura a IA local (Ollama)")
    p.add_argument("--list-tools", action="store_true", help="lista as ferramentas e ações")
    p.add_argument("--history", action="store_true", help="lista as últimas sessões")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-V", "--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    a = p.parse_args(argv)

    cores(sys.stdout.isatty() and not a.json and not os.environ.get("NO_COLOR"))
    cfg = config.load()
    if a.provider:
        cfg["provider"] = a.provider
    if a.model and cfg["provider"] in ("ollama", "openai"):
        cfg[cfg["provider"]]["model"] = a.model
    history.setup_logging(cfg.get("log", {}).get("level", "info"), a.verbose)

    agent = Agent(cfg, on_event=Saida(silencioso=a.json))
    use_llm = not a.no_llm

    if a.list_tools:
        listar_ferramentas(agent)
        return 0
    if a.history:
        for s in history.list_sessions(20):
            print(f"  {dim}{s['time']}{reset}  {s['question']}  →  {s['summary']}")
        return 0
    if a.setup_ai:
        return assistente_ia(agent)

    interativo = sys.stdin.isatty() and not a.json
    if a.diagnose or a.pergunta or a.checkup:
        if a.checkup:
            rep = agent.checkup(use_llm=use_llm)
        elif a.diagnose:
            rep = agent.diagnose(a.diagnose, use_llm=use_llm)
        else:
            rep = agent.ask(" ".join(a.pergunta), use_llm=use_llm)
        if a.json:
            d = rep.to_dict()
            mod = tools.DOMAINS.get(rep.domain)
            if mod and hasattr(mod, "network_status"):
                d["network_status"] = mod.network_status(rep.state)
            print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
        else:
            mostrar(rep)
            if interativo:
                oferecer_acoes(agent, rep)
        return 1 if any(f["severity"] == "erro" for f in rep.findings) else 0

    # modo interativo (conversa: a IA lembra das últimas perguntas)
    ok, msg = agent.llm_status()
    print(f"{bold}{cyan}🤖 VoidBR AI {APP_VERSION}{reset}  {dim}IA: {msg}{reset}")
    print(f"{dim}Pergunte ou descreva o problema. 'checkup' faz o check-up geral; 'sair' encerra.{reset}")
    if not ok and agent.provider.name == "none" and not cfg.get("gui", {}).get("ai_setup"):
        print(f"{dim}💡 Para perguntas livres, configure a IA local: voidbr-ai --setup-ai{reset}")
    while True:
        texto = perguntar(f"\n{bold}voidbr-ai>{reset} ")
        if texto is None:       # Ctrl+D / fim da entrada
            break
        if not texto:
            continue
        if texto.lower() in ("sair", "exit", "quit", "q"):
            break
        rep = agent.checkup(use_llm) if texto.lower() in ("checkup", "check-up") \
            else agent.ask(texto, use_llm=use_llm)
        mostrar(rep)
        oferecer_acoes(agent, rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
