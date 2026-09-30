# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/registry.py - Tool Registry
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Tool Registry: a única porta de entrada para o sistema.

    LLM ──> Agent ──> Registry ──> ferramenta explícita
                                    ├── leitura: roda direto (como o usuário)
                                    └── ação: só com confirmação
                                          ├── root: helper via pkexec (lista branca)
                                          └── usuário: roda como você (ex: tirar o mudo)

O LLM nunca recebe um shell. Ele vê um catálogo de ferramentas com parâmetros
tipados; todo argumento é validado aqui antes de qualquer execução, e as
ações só rodam com confirmed=True (que a CLI/GUI passa depois que você confirma).
"""

import inspect
import re
from dataclasses import dataclass, field
from typing import Callable, Optional


class NotConfirmed(Exception):
    """Tentativa de executar uma ação sem confirmação do usuário."""


class ToolDisabled(Exception):
    pass


class InvalidArgs(ValueError):
    pass


def P(tipo="string", desc="", **kw):
    """Atalho para declarar um parâmetro (JSON Schema)."""
    d = {"type": tipo, "description": desc}
    d.update(kw)
    return d


@dataclass
class Tool:
    name: str                       # ex: "network.interfaces"
    label: str                      # ex: "Verificando interfaces"
    description: str                # o que o LLM lê
    func: Callable
    kind: str = "read"              # "read" | "action"
    domain: str = "system"
    params: dict = field(default_factory=dict)      # nome -> JSON Schema
    required: list = field(default_factory=list)
    check: Optional[Callable] = None                # validação extra: args -> erro|None
    # ações
    preview: Optional[Callable] = None              # args -> comando equivalente (para mostrar)
    title: str = ""                                 # "Reiniciar o serviço {name}"
    root: bool = True                               # False = roda como o usuário
    risk: str = ""                                  # aviso extra na confirmação
    risk_for: Optional[Callable] = None             # args -> aviso (depende do argumento)
    verify: Optional[Callable] = None               # args -> (ok, mensagem)
    snapshot: bool = False                          # snapshot do sistema antes (voidbr-snapper-manager)
    llm: bool = True                                # visível para o LLM
    internal: bool = False                          # recebe state/cfg (ferramentas do diagnóstico)

    @property
    def llm_name(self):
        # a API da OpenAI não aceita "." no nome da função
        return self.name.replace(".", "_")

    def schema(self):
        return {"type": "function", "function": {
            "name": self.llm_name,
            "description": self.description,
            "parameters": {"type": "object", "properties": self.params,
                           "required": self.required},
        }}

    def validate(self, args):
        args = dict(args or {})
        for k in list(args):
            if k not in self.params:
                del args[k]         # ignora argumentos inventados
        for k in self.required:
            if args.get(k) in (None, "", []):
                raise InvalidArgs(f"{self.name}: falta o argumento '{k}'")
        for k, v in list(args.items()):
            sch = self.params[k]
            t = sch.get("type", "string")
            if t == "integer":
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    raise InvalidArgs(f"{self.name}: '{k}' deve ser inteiro") from None
                lo, hi = sch.get("minimum"), sch.get("maximum")
                if lo is not None:
                    v = max(lo, v)
                if hi is not None:
                    v = min(hi, v)
            elif t == "boolean":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "sim", "yes")
            elif t == "array":
                if isinstance(v, str):
                    v = v.replace(",", " ").split()
                if not isinstance(v, list):
                    raise InvalidArgs(f"{self.name}: '{k}' deve ser uma lista")
                v = [str(i).strip() for i in v if str(i).strip()]
                mx = sch.get("maxItems")
                if mx and len(v) > mx:
                    raise InvalidArgs(f"{self.name}: '{k}' aceita no máximo {mx} itens")
                pat = sch.get("items", {}).get("pattern")
                for i in v:
                    if pat and not re.fullmatch(pat, i):
                        raise InvalidArgs(f"{self.name}: valor inválido em '{k}': {i}")
            else:
                v = str(v).strip()
                if "enum" in sch and v not in sch["enum"]:
                    raise InvalidArgs(f"{self.name}: '{k}' deve ser um de {sch['enum']}")
                if "pattern" in sch and not re.fullmatch(sch["pattern"], v):
                    raise InvalidArgs(f"{self.name}: valor inválido para '{k}': {v}")
                if len(v) > sch.get("maxLength", 256):
                    raise InvalidArgs(f"{self.name}: '{k}' longo demais")
            args[k] = v
        if self.check:
            erro = self.check(args)
            if erro:
                raise InvalidArgs(f"{self.name}: {erro}")
        return args


@dataclass
class Action:
    """Uma ação proposta. Só vira execução depois que o usuário confirma."""
    tool: str                       # nome da ferramenta de ação
    args: dict
    title: str                      # "Iniciar o NetworkManager"
    reason: str = ""                # por que está sendo proposta
    fixes: list = field(default_factory=list)   # códigos dos achados que resolve
    command: str = ""               # prévia do comando
    id: str = ""
    root: bool = True
    risk: str = ""
    source: str = "regras"          # "regras" | "llm"

    def to_dict(self):
        return {"id": self.id, "tool": self.tool, "args": self.args, "title": self.title,
                "reason": self.reason, "fixes": self.fixes, "command": self.command,
                "root": self.root, "risk": self.risk, "source": self.source}


class Registry:
    def __init__(self, disabled=None):
        self._tools = {}
        self.disabled = set(disabled or [])

    def register(self, tool):
        self._tools[tool.name] = tool
        return tool

    def get(self, name):
        """Aceita o nome normal ("pkg.search") ou o do LLM ("pkg_search")."""
        if name in self._tools:
            return self._tools[name]
        for t in self._tools.values():
            if t.llm_name == name:
                return t
        return None

    def list(self, kind=None, domain=None):
        return [t for t in self._tools.values()
                if (kind is None or t.kind == kind) and (domain is None or t.domain == domain)]

    def enabled(self, name):
        return name in self._tools and name not in self.disabled

    def llm_tools(self, kind, domains=None, extra=()):
        """Ferramentas visíveis ao LLM do tipo `kind`; com `domains`, só as desses
        domínios mais as de `extra` (menos ferramentas = prompt menor = mais rápido)."""
        return [t for t in self._tools.values()
                if t.kind == kind and t.llm and t.name not in self.disabled
                and (domains is None or t.domain in domains or t.name in extra)]

    def llm_schemas(self, domains=None, extra=()):
        """Ferramentas de LEITURA que o LLM pode chamar."""
        return [t.schema() for t in self.llm_tools("read", domains, extra)]

    def action_catalog(self, domains=None, extra=()):
        """Descrição das ações (para o LLM propor, nunca executar)."""
        itens = []
        for t in self.llm_tools("action", domains, extra):
            ps = ", ".join(f"{k}: {v.get('type')}" + (" (obrigatório)" if k in t.required else "")
                           for k, v in t.params.items())
            itens.append(f"- {t.name}({ps}): {t.description}")
        return "\n".join(itens)

    def call(self, name, /, **kwargs):
        """Chama uma ferramenta de LEITURA (argumentos validados)."""
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"ferramenta desconhecida: {name}")
        if tool.kind != "read":
            raise NotConfirmed(f"{name} é uma ação; use execute() com confirmação")
        if tool.name in self.disabled:
            raise ToolDisabled(tool.name)
        if tool.internal:
            return tool.func(**kwargs)
        return tool.func(**tool.validate(kwargs))

    def make_action(self, tool_name, args, title=None, reason="", fixes=None, source="regras"):
        tool = self.get(tool_name)
        if tool is None or tool.kind != "action":
            raise InvalidArgs(f"ação desconhecida: {tool_name}")
        if tool.name in self.disabled:
            raise InvalidArgs(f"ação desativada: {tool.name}")
        args = tool.validate(args)
        cmd = tool.preview(**args) if tool.preview else tool.name
        titulo = title or (tool.title.format(**{k: (" ".join(v) if isinstance(v, list) else v)
                                                for k, v in args.items()}) if tool.title else tool.label)
        aid = tool.name + ":" + ",".join(
            f"{k}={' '.join(v) if isinstance(v, list) else v}" for k, v in sorted(args.items()))
        return Action(tool=tool.name, args=args, title=titulo, reason=reason,
                      fixes=list(fixes or []), command=cmd, id=aid, root=tool.root,
                      risk=(tool.risk_for(args) if tool.risk_for else "") or tool.risk,
                      source=source)

    def execute(self, action, confirmed=False, on_line=None, snapshot=True):
        """Executa uma AÇÃO. Sem confirmed=True, recusa.

        snapshot: nas ações marcadas (pacotes, kernel, boot), pede ao helper um snapshot
        do sistema antes (se o voidbr-snapper-manager estiver instalado)."""
        if not confirmed:
            raise NotConfirmed(action.title)
        tool = self.get(action.tool)
        if tool is None or tool.kind != "action":
            raise KeyError(f"ação desconhecida: {action.tool}")
        if tool.name in self.disabled:
            raise ToolDisabled(tool.name)
        args = tool.validate(action.args)       # valida de novo: nunca confia na proposta
        from .privileged import set_snapshot
        set_snapshot(f"voidbr-ai: {action.title}" if (snapshot and tool.snapshot and tool.root) else None)
        try:
            if "on_line" in inspect.signature(tool.func).parameters:
                return tool.func(on_line=on_line, **args)
            return tool.func(**args)
        finally:
            set_snapshot(None)

    def verify(self, action):
        tool = self.get(action.tool)
        if tool is None or tool.verify is None:
            return None, ""
        try:
            return tool.verify(**action.args)
        except Exception as e:  # verificação nunca derruba o fluxo
            return None, f"não foi possível verificar: {e}"
