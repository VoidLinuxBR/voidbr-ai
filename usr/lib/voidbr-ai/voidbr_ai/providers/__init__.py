# -*- coding: utf-8 -*-
#
#   voidbr_ai/providers - LLMs (opcionais)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Providers de LLM. Todos opcionais: sem provider, o diagnóstico continua
funcionando só com as regras do Agent."""

import json
import re
import urllib.error
import urllib.request


class ProviderError(Exception):
    pass


class Provider:
    name = "none"

    def __init__(self, cfg):
        self.cfg = cfg or {}

    @property
    def model(self):
        return self.cfg.get("model", "")

    def available(self):
        """(ok, mensagem) — checagem rápida, sem gerar texto."""
        return False, "nenhum provider configurado"

    def chat(self, messages):
        """Recebe [{role, content}] e devolve o texto da resposta (JSON)."""
        raise ProviderError("nenhum provider configurado")

    def chat_tools(self, messages, tools):
        """Conversa com chamada de ferramentas nativa.

        Devolve {"content": str, "tool_calls": [{"id", "name", "arguments": dict}]}."""
        raise ProviderError("nenhum provider configurado")

    def assistant_message(self, resp):
        """A resposta do modelo no formato que a API espera de volta no histórico."""
        raise NotImplementedError

    def tool_message(self, call, content):
        """O resultado de uma ferramenta no formato da API."""
        raise NotImplementedError

    def describe(self):
        return f"{self.name}: {self.model}" if self.model else self.name


def http_json(url, payload=None, headers=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        raise ProviderError(f"HTTP {e.code}: {corpo}") from None
    except urllib.error.URLError as e:
        raise ProviderError(f"sem conexão com {url}: {e.reason}") from None
    except (TimeoutError, OSError) as e:
        raise ProviderError(f"falha ao falar com {url}: {e}") from None
    except ValueError:
        raise ProviderError(f"resposta inválida de {url}") from None


def parse_args(v):
    """Argumentos de uma chamada: dict (Ollama) ou string JSON (OpenAI)."""
    if isinstance(v, dict):
        return v
    try:
        d = json.loads(v or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def strip_thinking(texto):
    """Remove blocos <think>…</think> de modelos de raciocínio (qwen3, deepseek-r1)."""
    return re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S).strip()


def get_provider(cfg):
    nome = (cfg.get("provider") or "none").lower()
    if nome == "ollama":
        from .ollama import Ollama
        return Ollama(cfg.get("ollama", {}))
    if nome == "openai":
        from .openai import OpenAI
        return OpenAI(cfg.get("openai", {}))
    return Provider({})
