# -*- coding: utf-8 -*-
#
#   voidbr_ai/agent/agent.py - o Agent (núcleo do VoidBR AI)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""O Agent segue sempre:

    OBSERVAR → DIAGNOSTICAR → EXPLICAR → PROPOR → CONFIRMAR → EXECUTAR → VERIFICAR

Dois modos, a mesma segurança:

  COM LLM (ajuda geral) — investigate():
    o modelo recebe um catálogo de ferramentas de LEITURA e decide o que
    consultar, em vários passos, até entender o problema. Termina chamando
    "responder" com o diagnóstico e as ações que propõe. Cada ação proposta
    é validada no Tool Registry (nome da lista branca + argumentos) — o que
    não passa é descartado. Nada é executado sem confirmação.

  SEM LLM (regras) — diagnose() / checkup():
    cada domínio (rede, disco, pacotes, serviços, áudio, Bluetooth, memória)
    tem coletas e regras fixas que geram achados confirmados e ações.

  execute(): roda a ação confirmada (helper root via pkexec, ou como o
  usuário), mostra a saída ao vivo e VERIFICA: a checagem da própria ação
  e, quando veio das regras, refaz o diagnóstico até o achado sumir.

CLI e GUI usam esta mesma classe; nenhuma delas executa comandos por conta própria.
"""

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field

from .. import APP_VERSION, config, context, history, tools
from ..util import run
from ..providers import ProviderError, get_provider

log = logging.getLogger("voidbr-ai")

INVESTIGATE_PROMPT = """Você é o VoidBR AI, um técnico de sistemas integrado ao VoidBR Linux.
O VoidBR é baseado no Void Linux: init runit (serviços em /etc/sv, habilitados com link em
/var/service, controlados com sv), pacotes xbps; no VoidBR instala-se com vinstall.
NUNCA sugira systemctl, journalctl, apt, dnf ou pacman.

Como trabalhar:
1. INVESTIGUE antes de concluir: chame as ferramentas de leitura necessárias, quantas vezes
   precisar. Não invente o estado da máquina: só afirme o que as ferramentas mostraram.
2. Para rede use network_diagnose; para áudio audio_status; Bluetooth bluetooth_status;
   espaço disk_usage; lentidão system_processes e system_memory.
3. Para instalar um programa, descubra o nome exato com pkg_search antes de propor pkg.install.
4. Termine SEMPRE chamando a ferramenta "responder". Nela:
   - "fatos": só o que as ferramentas mostraram; "hipoteses": o que é provável mas não confirmado;
   - "acoes": só ações do catálogo abaixo, com os argumentos certos. Elas só rodam se o
     usuário confirmar. Não proponha ação desnecessária;
   - perguntas de "como faço…" também valem: explique os passos para o VoidBR.
5. Português do Brasil, curto e claro, para um usuário comum.

Catálogo de ações (propor, nunca executar):
{catalogo}

Contexto do sistema: {contexto}"""

INTERPRET_PROMPT = """Você é o VoidBR AI, técnico de sistemas do VoidBR Linux (Void Linux, runit, xbps;
no VoidBR instala-se com vinstall; nunca systemd). Você recebe em JSON o estado REAL coletado,
os achados das regras (confirmados) e as ações permitidas (por id). Baseie-se só nos dados,
separe fatos de hipóteses e recomende ações apenas pelo "id" exato. Português do Brasil, curto.
Responda APENAS com JSON:
{"diagnostico": "...", "explicacao": "...", "fatos": [], "hipoteses": [], "acoes": ["ids"], "sugestoes": []}"""


def _responder_schema(nomes_acoes):
    return {"type": "function", "function": {
        "name": "responder",
        "description": "Entrega a resposta final ao usuário. Chame quando terminar de investigar.",
        "parameters": {"type": "object", "properties": {
            "diagnostico": {"type": "string",
                            "description": "conclusão principal em 1-2 frases, ou a resposta direta"},
            "explicacao": {"type": "string", "description": "o que os dados mostram / passo a passo"},
            "fatos": {"type": "array", "items": {"type": "string"},
                      "description": "fatos confirmados pelas ferramentas"},
            "hipoteses": {"type": "array", "items": {"type": "string"},
                          "description": "possíveis causas não confirmadas"},
            "acoes": {"type": "array", "description": "ações do catálogo para o usuário confirmar",
                      "items": {"type": "object", "properties": {
                          "acao": {"type": "string", "enum": nomes_acoes},
                          "argumentos": {"type": "object"},
                          "motivo": {"type": "string"}}, "required": ["acao"]}},
            "sugestoes": {"type": "array", "items": {"type": "string"},
                          "description": "passos/comandos manuais opcionais"},
        }, "required": ["diagnostico"]},
    }}


@dataclass
class Event:
    kind: str                # "step" | "tool" | "llm" | "verify" | "output" | "info"
    id: str
    label: str
    status: str = "running"  # running | ok | warn | fail | info
    summary: str = ""


@dataclass
class Report:
    question: str
    domain: str                                      # domínio, "checkup", "llm" ou ""
    mode: str = "regras"                             # regras | llm | checkup
    context: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    actions: list = field(default_factory=list)      # [Action] em ordem de prioridade
    llm: dict = None
    llm_error: str = ""
    provider: str = ""
    summary: str = ""
    time: str = ""
    session_path: str = ""
    needs_ai: bool = False                           # pergunta livre sem LLM configurado
    tool_calls: list = field(default_factory=list)
    executions: list = field(default_factory=list)

    @property
    def problems(self):
        return [f for f in self.findings if f["severity"] in ("erro", "aviso")]

    def to_dict(self, with_state=True):
        d = {
            "version": APP_VERSION, "time": self.time, "question": self.question,
            "domain": self.domain, "mode": self.mode, "summary": self.summary,
            "context": self.context, "findings": self.findings,
            "actions": [a.to_dict() for a in self.actions], "llm": self.llm,
            "llm_error": self.llm_error, "provider": self.provider,
            "tool_calls": [{k: c[k] for k in ("tool", "args")} for c in self.tool_calls],
            "executions": self.executions,
        }
        if with_state:
            d["state"] = self.state
            d["tool_results"] = self.tool_calls
        return d


@dataclass
class ExecResult:
    action: object
    ok: bool
    output: str = ""
    cancelled: bool = False
    resolved: bool = None     # None = não deu para verificar
    check: str = ""           # mensagem da verificação da própria ação
    remaining: list = field(default_factory=list)
    after: Report = None

    def to_dict(self):
        return {"action": self.action.to_dict(), "ok": self.ok, "output": self.output[-2000:],
                "cancelled": self.cancelled, "resolved": self.resolved, "check": self.check,
                "remaining": [f["title"] for f in self.remaining]}


def _norm(texto):
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def parse_json(texto):
    """Extrai o primeiro objeto JSON da resposta do modelo."""
    try:
        return json.loads(texto)
    except ValueError:
        m = re.search(r"\{.*\}", texto or "", flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    raise ProviderError("o modelo não respondeu em JSON válido")


_RE_O_QUE_E = re.compile(
    r"^\s*(?:o\s+que\s+(?:e|eh|significa)|que\s+e|para\s+que\s+serve|pra\s+que\s+serve|"
    r"como\s+funciona|quem\s+e)\s+(?:o\s+|a\s+|os\s+|as\s+|um\s+|uma\s+)?"
    r"([a-z0-9][a-z0-9._+-]*)\s*\??\s*$")


def _termo_pergunta(texto):
    """'o que é o ollama?' -> 'ollama' (só perguntas de uma palavra)."""
    m = _RE_O_QUE_E.match(_norm(texto))
    return m.group(1) if m else None


def _compacto(obj, limite=5000):
    texto = json.dumps(obj, ensure_ascii=False, default=str)
    if len(texto) > limite:
        texto = texto[:limite] + '… (resultado cortado)"'
    return texto


def _lista(v):
    return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])


class Agent:
    def __init__(self, cfg=None, on_event=None):
        self.cfg = cfg or config.load()
        self.on_event = on_event or (lambda ev: None)
        self.registry = tools.build_registry(self.cfg.get("tools", {}).get("disabled", []))
        self.provider = get_provider(self.cfg)
        self.history = []            # conversa (para perguntas de continuação)

    # -- utilidades ---------------------------------------------------------

    def emit(self, *args, **kw):
        try:
            self.on_event(Event(*args, **kw))
        except Exception:  # a interface nunca derruba o Agent
            log.exception("on_event falhou")

    def llm_status(self):
        if self.provider.name == "none":
            return False, self.provider.cfg.get("_motivo") or "sem IA configurada (só regras)"
        return self.provider.available()

    def reset(self):
        self.history = []

    def classify(self, text):
        """Domínios que a pergunta envolve (sem LLM: palavras-chave)."""
        texto = _norm(text)
        palavras = set(re.findall(r"[a-z0-9-]+", texto))
        achados = []
        for nome, mod in tools.DOMAINS.items():
            for k in mod.KEYWORDS:
                if (" " in k and k in texto) or k in palavras:
                    achados.append(nome)
                    break
        return achados

    def _novo(self, question, domain, mode):
        return Report(question=question, domain=domain, mode=mode,
                      time=time.strftime("%Y-%m-%d %H:%M:%S"))

    # -- OBSERVAR + DIAGNOSTICAR (regras) --------------------------------------

    def observe(self, domain, quiet=False):
        mod = tools.DOMAINS[domain]
        dcfg = self.cfg.get(domain, {})
        estado = {}
        for nome, rotulo, chave in mod.STEPS:
            if not self.registry.enabled(nome):
                if not quiet:
                    self.emit("step", nome, rotulo, "info", "desativado na configuração")
                continue
            if not quiet:
                self.emit("step", nome, rotulo + "…")
            try:
                estado[chave] = self.registry.call(nome, state=estado, cfg=dcfg)
            except Exception as e:
                log.exception("ferramenta %s falhou", nome)
                estado[chave] = {"error": str(e), "summary": f"falhou: {e}", "status": "fail"}
            if not quiet:
                st = estado[chave].get("status", "info")
                self.emit("step", nome, rotulo, {"ok": "ok", "warn": "warn", "fail": "fail"}
                          .get(st, "info"), estado[chave].get("summary", ""))
        return estado

    def _contexto(self, quiet):
        if not quiet:
            self.emit("step", "context", "Detectando o ambiente…")
        ctx = context.collect()
        if not quiet:
            self.emit("step", "context", "Detectando o ambiente", "ok",
                      f"{ctx['distro']['name']}, kernel {ctx['kernel']}, "
                      f"{ctx['init'].get('service_manager', '?')}")
        return ctx

    def diagnose(self, domain, question="", use_llm=True, quiet=False):
        domain = tools.ALIASES.get(domain, domain)
        mod = tools.DOMAINS[domain]
        rep = self._novo(question or f"diagnóstico: {tools.LABELS.get(domain, domain)}", domain,
                         "regras")
        rep.context = self._contexto(quiet)
        rep.state = self.observe(domain, quiet)
        rep.findings, rep.actions = mod.analyze(rep.state, self.registry)
        for f in rep.findings:
            f.setdefault("domain", domain)
        rep.summary = self._summary(rep)
        if use_llm and not quiet and self.provider.name != "none" and rep.problems:
            self.interpret(rep)
        if not quiet:
            history.save_diagnostic(domain, rep.state)
            rep.session_path = history.save_session(rep.to_dict(with_state=False)) or ""
        return rep

    def checkup(self, use_llm=True):
        """Check-up geral: todos os domínios com regras."""
        rep = self._novo("Check-up geral", "checkup", "checkup")
        rep.context = self._contexto(False)
        ordem = {"erro": 0, "aviso": 1, "info": 2, "ok": 3}
        for dom, mod in tools.DOMAINS.items():
            self.emit("info", f"hdr-{dom}", tools.LABELS[dom], "info")
            estado = self.observe(dom)
            rep.state[dom] = estado
            try:
                achados, acoes = mod.analyze(estado, self.registry)
            except Exception as e:
                log.exception("regras de %s falharam", dom)
                achados, acoes = [{"code": f"rules_failed:{dom}", "severity": "info",
                                   "title": f"Não foi possível analisar {tools.LABELS[dom]}",
                                   "detail": str(e), "step": "", "confirmed": True,
                                   "suggestions": []}], []
            for f in achados:
                f["domain"] = dom
            rep.findings += achados
            ids = {a.id for a in rep.actions}
            rep.actions += [a for a in acoes if a.id not in ids]
        rep.findings.sort(key=lambda f: ordem.get(f["severity"], 9))
        erros = sum(f["severity"] == "erro" for f in rep.findings)
        avisos = sum(f["severity"] == "aviso" for f in rep.findings)
        rep.summary = ("Tudo certo: nenhum problema encontrado" if not erros and not avisos else
                       f"{erros} problema(s) e {avisos} aviso(s) encontrados")
        if use_llm and self.provider.name != "none" and rep.problems:
            self.interpret(rep)
        history.save_diagnostic("checkup", rep.state)
        rep.session_path = history.save_session(rep.to_dict(with_state=False)) or ""
        return rep

    def _summary(self, rep):
        for sev in ("erro", "aviso"):
            x = [f for f in rep.findings if f["severity"] == sev]
            if x:
                oks = [f for f in rep.findings if f["severity"] == "ok"]
                if sev == "aviso" and oks:
                    return oks[0]["title"] + f" ({len(x)} aviso(s))"
                return x[0]["title"]
        oks = [f for f in rep.findings if f["severity"] == "ok"]
        return oks[0]["title"] if oks else "Nenhum problema encontrado"

    # -- EXPLICAR: interpretação de um diagnóstico por regras ---------------------

    def interpret(self, rep):
        rep.provider = self.provider.describe()
        self.emit("llm", "llm", f"Interpretando com a IA ({rep.provider})…")
        ok, msg = self.provider.available()
        if not ok:
            rep.llm_error = msg
            self.emit("llm", "llm", "IA indisponível — diagnóstico só pelas regras", "warn", msg)
            return
        mod = tools.DOMAINS.get(rep.domain)
        estado = mod.network_status(rep.state) if mod is not None and hasattr(mod, "network_status") \
            else rep.state
        entrada = {
            "pergunta": rep.question, "contexto": rep.context, "estado": estado,
            "achados": [{k: f.get(k) for k in ("code", "severity", "title", "detail", "confirmed")}
                        for f in rep.findings if f["severity"] != "ok"],
            "acoes_permitidas": [{"id": a.id, "titulo": a.title, "comando": a.command,
                                  "motivo": a.reason} for a in rep.actions],
        }
        msgs = [{"role": "system", "content": INTERPRET_PROMPT},
                {"role": "user", "content": _compacto(entrada, 14000)}]
        try:
            resp = parse_json(self.provider.chat(msgs))
        except ProviderError as e:
            rep.llm_error = str(e)
            self.emit("llm", "llm", "A IA falhou — diagnóstico só pelas regras", "warn", str(e))
            return
        ids = {a.id for a in rep.actions}
        escolhidas = [i for i in _lista(resp.get("acoes")) if i in ids]
        rep.llm = {"diagnostico": str(resp.get("diagnostico", "")).strip(),
                   "explicacao": str(resp.get("explicacao", "")).strip(),
                   "fatos": _lista(resp.get("fatos")), "hipoteses": _lista(resp.get("hipoteses")),
                   "acoes": escolhidas, "sugestoes": _lista(resp.get("sugestoes")),
                   "ignoradas": [i for i in _lista(resp.get("acoes")) if i not in ids]}
        if rep.llm["ignoradas"]:
            log.warning("IA sugeriu ações fora da lista (ignoradas): %s", rep.llm["ignoradas"])
        rep.actions.sort(key=lambda a: escolhidas.index(a.id) if a.id in escolhidas else 99)
        self.emit("llm", "llm", "Interpretação da IA", "ok", rep.llm["diagnostico"])

    # -- pergunta livre ---------------------------------------------------------

    def ask(self, text, use_llm=True):
        ok, msg = self.llm_status() if use_llm else (False, "IA desativada")
        if ok:
            return self.investigate(text)
        termo = _termo_pergunta(text)
        if termo:
            return self._explicar_termo(text, termo, msg)
        dominios = self.classify(text)
        if dominios:
            if len(dominios) == 1:
                rep = self.diagnose(dominios[0], question=text, use_llm=False)
            else:
                rep = self._varios(text, dominios)
            rep.llm_error = msg if self.provider.name != "none" else ""
            rep.needs_ai = True     # respondeu pelas regras; com IA a resposta seria sob medida
            return rep
        rep = self._novo(text, "", "regras")
        rep.needs_ai = True
        rep.llm_error = msg
        rep.summary = ("Para perguntas livres eu preciso da IA configurada. Sem ela, faço o "
                       "check-up e os diagnósticos prontos: rede, disco, pacotes, serviços, áudio, "
                       "Bluetooth, memória e CPU.")
        return rep

    def _explicar_termo(self, text, termo, msg):
        """Sem IA: "o que é X?" respondido com o que o sistema sabe de X
        (descrição do pacote no xbps, se o comando existe, whatis/man)."""
        rep = self._novo(text, "", "regras")
        rep.llm_error = msg if self.provider.name != "none" else ""
        self.emit("tool", "t1", f"Buscando pacotes ({termo})…")
        busca = self.registry.call("pkg.search", query=termo)
        self.emit("tool", "t1", f"Buscando pacotes ({termo})", "ok",
                  f"{busca.get('total', 0)} resultado(s)")
        cmd = self.registry.call("system.command", name=termo)
        w = run(["whatis", termo], timeout=5)
        man = w["out"].splitlines()[0].strip() if w["rc"] == 0 and w["out"].strip() else ""

        # o pacote com o nome exato vem primeiro, depois os que contêm o termo
        res = busca.get("results", [])
        res.sort(key=lambda r: (r["name"] != termo, termo not in r["name"], r["name"]))
        principais = [r for r in res if termo in r["name"]][:5] or res[:3]
        if principais:
            p = principais[0]
            rep.summary = f"{p['name']}: {p['desc']}"
        elif man:
            rep.summary = man
        else:
            rep.summary = (f"Não encontrei \"{termo}\" nos pacotes nem nos manuais do sistema. "
                           "Com a IA configurada eu explico qualquer assunto.")
        for r in principais:
            estado = "instalado" if r["installed"] else "não instalado"
            rep.findings.append({"code": f"pkg:{r['name']}", "severity": "info",
                                 "title": f"{r['name']} ({estado})", "detail": r["desc"],
                                 "step": "", "confirmed": True, "suggestions": []})
        if cmd.get("path"):
            rep.findings.append({"code": "cmd", "severity": "ok",
                                 "title": f"O comando {termo} está instalado: {cmd['path']}",
                                 "detail": f"pacote {cmd['package']}" if cmd.get("package") else "",
                                 "step": "", "confirmed": True,
                                 "suggestions": [f"Manual: man {termo}"] if man else []})
        if man and principais:
            rep.findings.append({"code": "man", "severity": "info", "title": man, "detail": "",
                                 "step": "", "confirmed": True, "suggestions": []})
        alvo = next((r for r in principais if not r["installed"]), None)
        if alvo and alvo is principais[0]:
            try:
                rep.actions.append(self.registry.make_action(
                    "pkg.install", {"packages": [alvo["name"]]}, reason="se quiser usar"))
            except ValueError:
                pass
        rep.domain = "info"
        rep.needs_ai = True
        rep.session_path = history.save_session(rep.to_dict(with_state=False)) or ""
        return rep

    def _varios(self, text, dominios):
        rep = self._novo(text, "checkup", "checkup")
        rep.context = self._contexto(False)
        for dom in dominios:
            self.emit("info", f"hdr-{dom}", tools.LABELS[dom], "info")
            estado = self.observe(dom)
            rep.state[dom] = estado
            achados, acoes = tools.DOMAINS[dom].analyze(estado, self.registry)
            for f in achados:
                f["domain"] = dom
            rep.findings += achados
            rep.actions += acoes
        rep.summary = self._summary(rep)
        rep.session_path = history.save_session(rep.to_dict(with_state=False)) or ""
        return rep

    # -- INVESTIGAR com o LLM (tool calling) ------------------------------------------

    def investigate(self, text):
        rep = self._novo(text, "llm", "llm")
        rep.provider = self.provider.describe()
        rep.context = context.collect()
        c = rep.context
        ctx = (f"{c['distro']['name']} ({c['distro']['libc']}), kernel {c['kernel']}, {c['arch']}, "
               f"init {c['init'].get('service_manager')}, sessão {c['desktop'].get('session')} "
               f"{c['desktop'].get('desktop')}".strip())
        acoes_nomes = [t.name for t in self.registry.list("action")
                       if t.llm and t.name not in self.registry.disabled]
        sistema = INVESTIGATE_PROMPT.format(catalogo=self.registry.action_catalog(), contexto=ctx)
        ferramentas = self.registry.llm_schemas() + [_responder_schema(acoes_nomes)]
        msgs = [{"role": "system", "content": sistema}, *self.history[-6:],
                {"role": "user", "content": text}]
        max_passos = int(self.cfg.get("agent", {}).get("max_steps", 8))
        final, texto_livre = None, ""

        for passo in range(1, max_passos + 2):
            ultimo = passo > max_passos
            if ultimo:
                msgs.append({"role": "user", "content": "Limite de consultas atingido. Responda "
                             "agora chamando a ferramenta responder com o que já coletou."})
            eid = f"think{passo}"
            self.emit("llm", eid, "🧠 Pensando…" if passo == 1 else "🧠 Analisando os resultados…")
            try:
                resp = self.provider.chat_tools(msgs, [ferramentas[-1]] if ultimo else ferramentas)
            except ProviderError as e:
                rep.llm_error = str(e)
                self.emit("llm", eid, "A IA falhou", "fail", str(e))
                break
            consultas = [c for c in resp["tool_calls"] if c["name"] != "responder"]
            self.emit("llm", eid, "🧠 IA", "info",
                      f"vai consultar {len(consultas)} ferramenta(s)" if consultas else "respondeu")
            msgs.append(self.provider.assistant_message(resp))
            if not resp["tool_calls"]:
                texto_livre = resp["content"]
                break
            for call in resp["tool_calls"]:
                if call["name"] == "responder":
                    final = call["arguments"]
                    msgs.append(self.provider.tool_message(call, "ok"))
                    continue
                msgs.append(self.provider.tool_message(call, self._chamar(rep, call)))
            if final is not None:
                break
        self.emit("llm", "done", "Investigação concluída", "ok" if (final or texto_livre) else "warn",
                  f"{len(rep.tool_calls)} consulta(s) ao sistema")

        if final is None and texto_livre:
            try:
                final = parse_json(texto_livre)
                if "diagnostico" not in final and "resposta" not in final:
                    final = None
            except ProviderError:
                final = None
            if final is None:
                final = {"diagnostico": texto_livre}
        if final is None:
            rep.summary = f"Não consegui concluir a investigação: {rep.llm_error or 'sem resposta'}"
            return self._fechar(rep, text)

        rep.llm = {"diagnostico": str(final.get("diagnostico") or final.get("resposta") or "").strip(),
                   "explicacao": str(final.get("explicacao", "")).strip(),
                   "fatos": _lista(final.get("fatos")), "hipoteses": _lista(final.get("hipoteses")),
                   "sugestoes": _lista(final.get("sugestoes")), "ignoradas": []}
        rep.summary = rep.llm["diagnostico"] or "Investigação concluída"
        rep.findings = [{"code": f"fato:{i}", "severity": "info", "title": f, "detail": "",
                         "step": "", "confirmed": True, "source": "llm", "suggestions": []}
                        for i, f in enumerate(rep.llm["fatos"])]
        for i, h in enumerate(rep.llm["hipoteses"]):
            rep.findings.append({"code": f"hipotese:{i}", "severity": "info", "title": h,
                                 "detail": "", "step": "", "confirmed": False, "source": "llm",
                                 "suggestions": []})
        for item in final.get("acoes") or []:
            if not isinstance(item, dict):
                continue
            nome, args = str(item.get("acao", "")), item.get("argumentos") or {}
            try:
                a = self.registry.make_action(nome, args if isinstance(args, dict) else {},
                                              reason=str(item.get("motivo", "")).strip(),
                                              source="llm")
            except ValueError as e:
                rep.llm["ignoradas"].append(f"{nome}: {e}")
                log.warning("ação proposta pela IA descartada: %s (%s)", nome, e)
                continue
            if a.id not in {x.id for x in rep.actions}:
                rep.actions.append(a)
        return self._fechar(rep, text)

    def _chamar(self, rep, call):
        tool = self.registry.get(call["name"])
        n = len(rep.tool_calls) + 1
        if tool is None or tool.kind != "read" or not tool.llm:
            res = {"erro": f"ferramenta desconhecida ou não permitida: {call['name']}"}
            self.emit("tool", f"t{n}", f"❓ {call['name']}", "warn", "não permitida")
        else:
            args = call["arguments"] if isinstance(call["arguments"], dict) else {}
            arg_txt = ", ".join(f"{v}" for v in args.values())[:60]
            rotulo = tool.label + (f" ({arg_txt})" if arg_txt else "")
            self.emit("tool", f"t{n}", rotulo + "…")
            try:
                res = self.registry.call(tool.name, **args)
                st = "fail" if isinstance(res, dict) and res.get("error") else "ok"
                self.emit("tool", f"t{n}", rotulo, st, str(res.get("error", ""))[:120]
                          if isinstance(res, dict) else "")
            except Exception as e:      # argumento inválido etc.: o modelo vê o erro e corrige
                res = {"erro": str(e)}
                self.emit("tool", f"t{n}", rotulo, "warn", str(e)[:120])
        rep.tool_calls.append({"tool": call["name"], "args": call["arguments"], "result": res})
        return _compacto(res)

    def _fechar(self, rep, text):
        resumo = rep.summary
        if rep.llm and rep.llm.get("explicacao"):
            resumo += "\n" + rep.llm["explicacao"]
        self.history += [{"role": "user", "content": text},
                         {"role": "assistant", "content": resumo[:1500]}]
        self.history = self.history[-8:]
        rep.session_path = history.save_session(rep.to_dict(with_state=False)) or ""
        return rep

    # -- EXECUTAR + VERIFICAR ---------------------------------------------------------

    def execute(self, action, report, confirmed=False):
        """Executa uma ação JÁ CONFIRMADA pelo usuário e verifica o resultado."""
        self.emit("verify", "exec", f"Executando: {action.command}")

        def linha(t):
            self.emit("output", "out", t[-160:], "info")

        res = self.registry.execute(action, confirmed=confirmed, on_line=linha)
        saida = "\n".join(x for x in (res.get("out"), res.get("err")) if x)
        r = ExecResult(action=action, ok=res.get("ok", False), output=saida,
                       cancelled=res.get("cancelled", False))
        if r.cancelled:
            self.emit("verify", "exec", "Autenticação cancelada — nada foi alterado", "warn")
            return self._registrar(report, r)
        if not r.ok:
            self.emit("verify", "exec", "O comando falhou", "fail", saida.splitlines()[-1] if saida else "")
            return self._registrar(report, r)
        self.emit("verify", "exec", f"Executado: {action.command}", "ok")

        # não basta o comando ter retornado 0: verifica de verdade
        self.emit("verify", "check", "Verificando o resultado…")
        ok, msg = self.registry.verify(action)
        r.check = msg
        if ok is not None:
            self.emit("verify", "check", "Verificação da ação", "ok" if ok else "fail", msg)

        dominio = report.domain if report.domain in tools.DOMAINS else \
            next((f.get("domain") for f in report.findings
                  if f["code"] in action.fixes and f.get("domain")), None)
        if action.fixes and dominio:
            tentativas = int(self.cfg.get("agent", {}).get("verify_attempts", 4))
            intervalo = float(self.cfg.get("agent", {}).get("verify_interval", 4))
            alvo = set(action.fixes)
            for n in range(1, tentativas + 1):
                self.emit("verify", "verify", f"Refazendo o diagnóstico ({n}/{tentativas})…")
                if n > 1 or not ok:
                    time.sleep(intervalo)
                depois = self.diagnose(dominio, report.question, use_llm=False, quiet=True)
                r.after, r.remaining = depois, [f for f in depois.findings if f["code"] in alvo]
                if not r.remaining:
                    break
            r.resolved = not r.remaining
            self.emit("verify", "verify", "Problema resolvido" if r.resolved else "O problema continua",
                      "ok" if r.resolved else "fail",
                      r.after.summary if r.resolved else "; ".join(f["title"] for f in r.remaining))
        else:
            r.resolved = ok
            if ok is None:
                self.emit("verify", "verify", "Executado; não há como verificar automaticamente",
                          "info", "confira você mesmo se resolveu")
        return self._registrar(report, r)

    def _registrar(self, report, r):
        report.executions.append(r.to_dict())
        if report.session_path:
            history.save_session(report.to_dict(with_state=False), report.session_path)
        return r
