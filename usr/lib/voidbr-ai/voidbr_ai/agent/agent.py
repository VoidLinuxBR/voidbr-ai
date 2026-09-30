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
import threading
import time
import unicodedata
from dataclasses import dataclass, field

from .. import APP_VERSION, config, context, explain, history, kb, report, tools
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

Contexto do sistema: {contexto}{documentacao}"""

KNOWLEDGE_PROMPT = """Você é o VoidBR AI, assistente do VoidBR Linux (baseado no Void Linux: init runit,
serviços em /etc/sv e /var/service, pacotes xbps; no VoidBR instala-se com vinstall; nunca systemd).
Responda de forma direta e curta (poucas frases), em português do Brasil, para um usuário comum.
Se envolver instalar algo no VoidBR, cite o comando com vinstall ou xbps-install.
Se pedirem um script ou código, entregue o código completo num bloco ``` com a linguagem
(ex: ```bash), comentado em português, e diga em uma linha como usar. Scripts bash para o
VoidBR: use sv (runit) e xbps; nunca systemctl/apt. Nomes de variáveis de cores em minúsculo.
Sistema: {contexto}{documentacao}"""

EXPLAIN_PROMPT = """Você é o VoidBR AI, técnico do VoidBR Linux (Void Linux: runit, xbps; no VoidBR
instala-se com vinstall; nunca systemd). O usuário colou um {tipo}. NADA foi executado.
{tarefa}
Português do Brasil, curto e claro, para um usuário comum. Use a análise automática abaixo
(os riscos listados são reais: não os minimize).
Análise automática: {analise}
Sistema: {contexto}{documentacao}"""

_TAREFA = {
    "comando": ("Explique o que o comando faz, parte por parte; diga o risco (seguro / cuidado / "
                "perigoso) e por quê; se for perigoso, diga o que pode dar errado e uma forma "
                "mais segura. Não mande o usuário executar nada perigoso."),
    "erro": ("Explique o que o erro significa, a causa mais provável e como resolver no VoidBR, "
             "passo a passo, com os comandos (sv, xbps/vinstall)."),
}

DOC_PROMPT = """

Trechos da documentação local do Void/VoidBR (confiáveis; prefira estes comandos e nomes
de pacotes, e cite a fonte quando usar):
{trechos}"""

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
    kind: str                # "step" | "tool" | "llm" | "verify" | "output" | "info" | "stream"
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
    streamed: bool = False                           # a resposta já foi mostrada ao vivo
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
            # nomes de redes Wi-Fi vistos na coleta: o relatório exportado os oculta
            "redact": sorted(report._ssids(self.state)),
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
    snapshot: int = None      # snapshot criado antes (voidbr-snapper-manager), para desfazer

    def to_dict(self):
        return {"action": self.action.to_dict(), "ok": self.ok, "output": self.output[-2000:],
                "cancelled": self.cancelled, "resolved": self.resolved, "check": self.check,
                "remaining": [f["title"] for f in self.remaining], "snapshot": self.snapshot}


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


# pergunta de conhecimento ("o que é", "para que serve", "explique"...) ou pedido de
# texto/código ("faça um script..."): a IA responde direto, sem ferramentas — bem mais
# rápido. Se falar da máquina do usuário ("minha rede não funciona"), investiga.
_RE_CONHECIMENTO = re.compile(
    r"^\s*(?:o\s+que\s+(?:e|eh|sao|significa|quer\s+dizer)|que\s+e|o\s+que\s+faz|"
    r"para\s+que\s+serve|pra\s+que\s+serve|como\s+funciona|quem\s+(?:e|foi)|"
    r"qual\s+(?:e\s+)?a\s+diferenca|(?:me\s+)?expli(?:que|ca)|defina|"
    r"(?:me\s+)?(?:faca|faz|crie|cria|escreva|escreve|gere|gera|monte|monta)\s+(?:um|uma|o|a)\b|"
    r"como\s+(?:eu\s+|se\s+|posso\s+|devo\s+|faco\s+para\s+)?(?:faco|faz|instal[oa]r?|habilit[oa]r?|"
    r"ativ[oa]r?|desativ[oa]r?|configur[oa]r?|mud[oa]r?|troc[oa]r?|remov[oa]r?|desinstal[oa]r?|"
    r"atualiz[oa]r?|us[oa]r?|cri[oa]r?|adicion[oa]r?|coloc[oa]r?|vej[oa]|ver|reinici[oa]r?|"
    r"inici[oa]r?|compil[oa]r?|empacot[oa]r?|limp[oa]r?|refaz(?:er|o)?)\b|"
    r"qual\s+(?:e\s+)?o\s+comando)")
_RE_CODIGO = re.compile(r"\b(?:script|codigo|programa\s+em|funcao\s+(?:em|que)|regex|"
                        r"one-?liner|alias)\b")
_RE_PESSOAL = re.compile(r"\b(?:meu|minha|meus|minhas|aqui|nesta|neste|nessa|nesse|esse\s+erro|"
                         r"este\s+erro|deu|dando|nao\s+funciona|parou|travou|travando)\b")


_RE_EXPLIQUE = re.compile(r"^\s*(?:me\s+)?(?:explique|explica|o\s+que\s+faz)\s+(?:o\s+|este\s+|esse\s+|"
                          r"a\s+|esta\s+|essa\s+)?(?:comando|erro|mensagem)\s*:?\s*(.+)$",
                          re.S | re.I)


def _conhecimento(texto):
    t = _norm(texto)
    if _RE_CODIGO.search(t):            # pedido de script/código: sempre resposta direta
        return True
    return bool(_RE_CONHECIMENTO.match(t)) and not _RE_PESSOAL.search(t)


# ferramentas enviadas ao LLM por assunto (em vez do catálogo inteiro)
_TOOL_DOMAINS = {
    "network": {"network"},
    "storage": {"storage"},
    "packages": {"packages"},
    "services": {"services"},
    "audio": {"audio", "services"},
    "bluetooth": {"bluetooth", "services"},
    "system": {"system", "hardware", "boot"},
    "graphics": {"graphics", "hardware"},
    "boot": {"boot", "packages"},
    "logs": {"logs", "services"},
    "printing": {"printing", "services"},
}
_TOOLS_BASE = ("system.info", "system.memory", "system.processes", "system.log",
               "service.status", "pkg.search", "pkg.info", "pkg.install", "kb.search")


def _documentacao(texto, limite=1800):
    """Trechos da base local relevantes para a pergunta, já no formato do prompt."""
    try:
        trechos = kb.contexto(texto, limite_chars=limite)
    except Exception:  # a base nunca derruba a pergunta
        log.exception("falha na base de conhecimento")
        trechos = ""
    return DOC_PROMPT.format(trechos=trechos) if trechos else ""


class _Relogio:
    """Atualiza "🧠 Pensando… 12 s" a cada segundo enquanto espera a IA."""

    def __init__(self, emit, eid, rotulo):
        self.emit, self.eid, self.rotulo = emit, eid, rotulo
        self.inicio = time.monotonic()
        self._parar = threading.Event()
        self._t = threading.Thread(target=self._rodar, daemon=True)
        self._t.start()

    def _rodar(self):
        while not self._parar.wait(1):
            self.emit("llm", self.eid, f"{self.rotulo} {self.segundos} s")

    @property
    def segundos(self):
        return int(time.monotonic() - self.inicio)

    def parar(self):
        self._parar.set()
        self._t.join(timeout=2)
        return self.segundos


def _compacto(obj, limite=3500):
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
        m = _RE_EXPLIQUE.match(text)
        if m:
            return self.explain(m.group(1), use_llm)
        if text.lstrip().startswith("$ ") or ("\n" in text.strip() and explain.parece_erro(text)):
            return self.explain(text, use_llm)
        ok, msg = self.llm_status() if use_llm else (False, "IA desativada")
        if ok:
            return self.investigate(text)
        termo = _termo_pergunta(text)
        docs = kb.search(text)
        if docs and (_conhecimento(text) or not self.classify(text)):
            return self._da_documentacao(text, docs, msg)
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

    # -- EXPLICAR um comando ou erro colado ------------------------------------------

    def explain(self, texto, use_llm=True):
        """Explica um comando (o que faz e se é perigoso) ou uma mensagem de erro.
        Nada do texto é executado."""
        texto = (texto or "").strip()[:4000]
        rep = self._novo(texto, "explain", "regras")
        self.emit("tool", "an", "Analisando o texto (nada é executado)…")
        a = explain.analisar(texto)
        rep.state = {"explain": a}
        rep.context = context.collect()
        self.emit("tool", "an", "Analisando o texto", "ok",
                  f"{a['tipo']}: {a['nivel']}" if a["tipo"] == "comando" else
                  f"{len(a['erros'])} erro(s) conhecido(s)")
        sev = {"perigoso": "erro", "cuidado": "aviso"}
        for r in a["riscos"]:
            rep.findings.append({"code": f"risco:{r['motivo'][:40]}", "severity": sev[r["nivel"]],
                                 "title": f"{r['nivel'].capitalize()}: {r['motivo']}", "detail": "",
                                 "step": "", "confirmed": True, "suggestions": []})
        for c in a["comandos"]:
            det = c["descricao"] or ("não instalado" if not c["instalado"] else "")
            if c["pacote"]:
                det += f" (pacote {c['pacote']})"
            rep.findings.append({"code": f"cmd:{c['nome']}", "severity": "info",
                                 "title": c["nome"], "detail": det.strip(), "step": "",
                                 "confirmed": True, "suggestions": []})
        for e in a["erros"]:
            rep.findings.append({"code": f"erro:{e['titulo']}", "severity": "aviso",
                                 "title": e["titulo"], "detail": e["explicacao"], "step": "",
                                 "confirmed": True, "suggestions": e["sugestoes"]})
        if a["tipo"] == "comando":
            rep.summary = {"perigoso": "⚠️ Comando PERIGOSO — não execute sem entender",
                           "cuidado": "Comando que exige cuidado"}.get(
                a["nivel"], "Nenhum risco conhecido neste comando")
        else:
            rep.summary = a["erros"][0]["titulo"] if a["erros"] else "Mensagem de erro"

        ok, msg = self.llm_status() if use_llm else (False, "IA desativada")
        if not ok:
            rep.llm_error = msg if self.provider.name != "none" else ""
            rep.needs_ai = not a["erros"] and not a["riscos"]
            rep.session_path = history.save_session(rep.to_dict(with_state=False)) or ""
            return rep

        c = rep.context
        ctx = f"{c['distro']['name']}, kernel {c['kernel']}, {c['arch']}"
        prompt = EXPLAIN_PROMPT.format(
            tipo="comando" if a["tipo"] == "comando" else "mensagem de erro",
            tarefa=_TAREFA[a["tipo"]], analise=_compacto(a, 1500), contexto=ctx,
            documentacao=_documentacao(texto, 1200))
        final = self._responder_direto(rep, texto, ctx, sistema=prompt)
        final.domain = "explain"            # os riscos (findings) continuam no relatório
        return final

    def _da_documentacao(self, text, docs, msg):
        """Sem IA: responde com os trechos da base local (Void Handbook, vinstall, pkgmake...)."""
        rep = self._novo(text, "info", "regras")
        rep.llm_error = msg if self.provider.name != "none" else ""
        self.emit("tool", "kb", "Consultando a documentação do VoidBR", "ok",
                  f"{len(docs)} trecho(s)")
        rep.summary = f"Da documentação: {docs[0]['titulo']}"
        for d in docs:
            rep.findings.append({"code": f"kb:{d['arquivo']}:{d['titulo']}", "severity": "info",
                                 "title": d["titulo"], "detail": d["texto"], "step": "",
                                 "confirmed": True,
                                 "suggestions": [f"Fonte: {d['fonte']}"] if d["fonte"] else []})
        rep.needs_ai = True
        rep.session_path = history.save_session(rep.to_dict(with_state=False)) or ""
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
        if _conhecimento(text):
            return self._responder_direto(rep, text, ctx)

        # só as ferramentas do assunto (+ as básicas); assunto desconhecido = todas
        dominios = self.classify(text)
        tdom = set().union(*(_TOOL_DOMAINS.get(d, {d}) for d in dominios)) if dominios else None
        extra = _TOOLS_BASE if tdom else ()
        acoes_nomes = [t.name for t in self.registry.llm_tools("action", tdom, extra)]
        sistema = INVESTIGATE_PROMPT.format(catalogo=self.registry.action_catalog(tdom, extra),
                                            contexto=ctx, documentacao=_documentacao(text, 1200))
        ferramentas = self.registry.llm_schemas(tdom, extra) + [_responder_schema(acoes_nomes)]
        log.info("IA: %d ferramenta(s) (%s)", len(ferramentas) - 1,
                 ", ".join(sorted(tdom)) if tdom else "todas")
        inicio = time.monotonic()
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
            rotulo = "🧠 Pensando…" if passo == 1 else "🧠 Analisando os resultados…"
            self.emit("llm", eid, rotulo)
            relogio = _Relogio(self.emit, eid, rotulo)
            try:
                resp = self.provider.chat_tools(msgs, [ferramentas[-1]] if ultimo else ferramentas)
            except ProviderError as e:
                rep.llm_error = str(e)
                self.emit("llm", eid, f"A IA falhou ({relogio.parar()} s)", "fail")
                break
            seg = relogio.parar()
            consultas = [c for c in resp["tool_calls"] if c["name"] != "responder"]
            self.emit("llm", eid, f"🧠 IA ({seg} s)", "info",
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
        if final or texto_livre:
            self.emit("llm", "done", f"Investigação concluída ({int(time.monotonic() - inicio)} s)",
                      "ok", f"{len(rep.tool_calls)} consulta(s) ao sistema")

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
            rep.summary = (f"A IA falhou: {rep.llm_error}" if rep.llm_error else
                           "Não consegui concluir a investigação: a IA não respondeu")
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

    def _responder_direto(self, rep, text, ctx, sistema=None):
        """Pergunta de conhecimento: resposta em texto, sem ferramentas, mostrada
        conforme a IA escreve (eventos "stream")."""
        rep.mode, rep.provider = "llm", self.provider.describe()
        sistema = sistema or KNOWLEDGE_PROMPT.format(contexto=ctx, documentacao=_documentacao(text))
        msgs = [{"role": "system", "content": sistema},
                *self.history[-6:], {"role": "user", "content": text}]
        rotulo = "🧠 Pensando…"
        self.emit("llm", "think1", rotulo)
        relogio = _Relogio(self.emit, "think1", rotulo)
        primeiro = []

        def pedaco(t):
            if not primeiro:
                primeiro.append(relogio.parar())
                self.emit("llm", "think1", f"🧠 IA ({primeiro[0]} s até começar)", "info")
            self.emit("stream", "resposta", t, "info")

        try:
            texto = self.provider.answer(msgs, on_text=pedaco)
        except ProviderError as e:
            seg = primeiro[0] if primeiro else relogio.parar()
            rep.llm_error = str(e)
            self.emit("llm", "done", f"A IA falhou ({seg} s)", "fail")
            rep.summary = f"A IA falhou: {e}"
            return self._fechar(rep, text)
        if not primeiro:
            relogio.parar()
        self.emit("llm", "done", f"Resposta concluída ({int(time.monotonic() - relogio.inicio)} s)",
                  "ok")
        rep.streamed = True
        rep.llm = {"diagnostico": texto.strip(), "explicacao": "", "fatos": [], "hipoteses": [],
                   "sugestoes": [], "ignoradas": []}
        rep.summary = texto.strip()
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

    def load_session(self, path):
        """Reabre uma sessão do histórico como Report (para ver, exportar e continuar a
        conversa). As ações são validadas de novo no Tool Registry; as que não valem mais
        (ex: pacote já instalado) não voltam."""
        import json as _json
        with open(path, encoding="utf-8") as f:
            d = _json.load(f)
        rep = Report(question=d.get("question", ""), domain=d.get("domain", ""),
                     mode=d.get("mode", "regras"), context=d.get("context") or {},
                     findings=d.get("findings") or [], llm=d.get("llm"),
                     llm_error=d.get("llm_error", ""), provider=d.get("provider", ""),
                     summary=d.get("summary", ""), time=d.get("time", ""), session_path=path,
                     tool_calls=[{**c, "result": None} for c in d.get("tool_calls") or []],
                     executions=d.get("executions") or [])
        rep.state = {"_redact": d.get("redact") or []}
        feitas = {(e.get("action") or {}).get("id") for e in rep.executions if e.get("ok")}
        for a in d.get("actions") or []:
            if a.get("id") in feitas:
                continue
            try:
                rep.actions.append(self.registry.make_action(
                    a.get("tool", ""), a.get("args") or {}, reason=a.get("reason", ""),
                    fixes=a.get("fixes") or [], source=a.get("source", "regras")))
            except ValueError:
                pass
        resumo = rep.summary + ("\n" + rep.llm["explicacao"] if rep.llm and rep.llm.get("explicacao") else "")
        self.history = [{"role": "user", "content": rep.question},
                        {"role": "assistant", "content": resumo[:1500]}]
        return rep

    def report_markdown(self, rep):
        """Relatório para compartilhar (dados pessoais ocultos)."""
        d = rep.to_dict(with_state=False)
        d["redact"] = sorted(set(d.get("redact") or []) | set((rep.state or {}).get("_redact", [])))
        return report.markdown(d, {"ssid_list": [{"ssid": s} for s in d["redact"]]})

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

        res = self.registry.execute(action, confirmed=confirmed, on_line=linha,
                                    snapshot=bool(self.cfg.get("agent", {}).get("snapshot", True)))
        saida = "\n".join(x for x in (res.get("out"), res.get("err")) if x)
        r = ExecResult(action=action, ok=res.get("ok", False), output=saida,
                       cancelled=res.get("cancelled", False), snapshot=res.get("snapshot"))
        if r.snapshot:
            self.emit("verify", "snap", f"📸 Snapshot {r.snapshot} do sistema criado antes da mudança",
                      "ok", "dá para desfazer pelo Gerenciador de snapshots")
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
