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
import logging
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("voidbr-ai")

# servidor ocupado / limite de uso: espera e tenta de novo (segundos)
ESPERAS = (3, 8, 15)
TEMPORARIOS = (429, 500, 502, 503, 504)


class ProviderError(Exception):
    def __init__(self, msg, status=0):
        super().__init__(msg)
        self.status = status


def _msg_http(code, corpo):
    """Resposta de erro da API -> uma linha curta e em português."""
    msg = ""
    try:
        d = json.loads(corpo)
        if isinstance(d, list) and d:
            d = d[0]
        err = d.get("error", d) if isinstance(d, dict) else d
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        msg = corpo
    msg = " ".join(str(msg).split())
    if len(msg) > 160:
        msg = msg[:160] + "…"
    dica = {401: "chave da API inválida ou ausente",
            403: "a chave não tem permissão para isso",
            404: "modelo ou endereço não encontrado (confira o nome do modelo; voidbr-ai --list-models)",
            429: "limite de uso atingido; tente mais tarde",
            503: "o serviço está sobrecarregado agora; tente mais tarde"}.get(code, "")
    return f"HTTP {code}: " + (f"{dica} — {msg}" if dica and msg else dica or msg)


class Provider:
    name = "none"

    def __init__(self, cfg):
        self.cfg = cfg or {}

    @property
    def model(self):
        return self.cfg.get("model", "")

    def available(self):
        """(ok, mensagem) — checagem rápida, sem gerar texto."""
        return False, self.cfg.get("_motivo") or "nenhum provider configurado"

    def chat(self, messages):
        """Recebe [{role, content}] e devolve o texto da resposta (JSON)."""
        raise ProviderError("nenhum provider configurado")

    def chat_tools(self, messages, tools):
        """Conversa com chamada de ferramentas nativa.

        Devolve {"content": str, "tool_calls": [{"id", "name", "arguments": dict}]}."""
        raise ProviderError("nenhum provider configurado")

    def list_models(self):
        """Modelos que este provider (e a chave) pode usar."""
        raise ProviderError("nenhum provider configurado")

    def answer(self, messages, on_text=None):
        """Resposta em texto livre (sem ferramentas). on_text(pedaço) recebe o
        texto conforme o modelo escreve, quando o provider suporta streaming."""
        raise ProviderError("nenhum provider configurado")

    def assistant_message(self, resp):
        """A resposta do modelo no formato que a API espera de volta no histórico."""
        raise NotImplementedError

    def tool_message(self, call, content):
        """O resultado de uma ferramenta no formato da API."""
        raise NotImplementedError

    def describe(self):
        return f"{self.name}: {self.model}" if self.model else self.name


def com_retentativa(fn):
    """Chama fn(); se o servidor estiver ocupado (429/5xx), espera e tenta de novo."""
    for espera in (*ESPERAS, None):
        try:
            return fn()
        except ProviderError as e:
            if espera is None or e.status not in TEMPORARIOS:
                raise
            log.info("IA ocupada (%s); nova tentativa em %d s", e.status, espera)
            time.sleep(espera)


def http_json(url, payload=None, headers=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:2000]
        raise ProviderError(_msg_http(e.code, corpo), e.code) from None
    except urllib.error.URLError as e:
        raise ProviderError(f"sem conexão com {url}: {e.reason}") from None
    except (TimeoutError, OSError) as e:
        raise ProviderError(f"falha ao falar com {url}: {e}") from None
    except ValueError:
        raise ProviderError(f"resposta inválida de {url}") from None


def http_stream(url, payload, headers=None, timeout=30):
    """POST com resposta em NDJSON (uma linha JSON por pedaço): gera cada objeto."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for linha in r:
                linha = linha.strip()
                if linha:
                    yield json.loads(linha.decode("utf-8"))
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:2000]
        raise ProviderError(_msg_http(e.code, corpo), e.code) from None
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


def detect_ollama(cfg):
    """provider = "auto": usa o Ollama local se ele responder e tiver modelo.

    Devolve o provider pronto ou um Provider vazio com o motivo (para a mensagem)."""
    import shutil
    from .ollama import Ollama
    o = cfg.get("ollama", {})
    try:
        nomes = Ollama(o).models(timeout=1)
    except ProviderError:
        if shutil.which("ollama"):
            return Provider({"_motivo": "Ollama instalado, mas o serviço não responde "
                                        "(sudo sv status ollama; ou voidbr-ai --setup-ai)"})
        return Provider({})
    if not nomes:
        return Provider({"_motivo": "Ollama rodando, mas sem nenhum modelo baixado "
                                    "(voidbr-ai --setup-ai baixa um)"})
    m = o.get("model", "")
    escolhido = m if (m in nomes or f"{m}:latest" in nomes) else nomes[0]
    return Ollama({**o, "model": escolhido})


def get_provider(cfg):
    nome = (cfg.get("provider") or "none").lower()
    if nome == "auto":
        return detect_ollama(cfg)
    if nome == "ollama":
        from .ollama import Ollama
        return Ollama(cfg.get("ollama", {}))
    if nome == "openai":
        from .openai import OpenAI
        return OpenAI(cfg.get("openai", {}))
    return Provider({})
