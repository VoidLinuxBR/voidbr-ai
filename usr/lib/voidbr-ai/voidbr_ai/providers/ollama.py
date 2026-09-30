# -*- coding: utf-8 -*-
#
#   voidbr_ai/providers/ollama.py - Ollama (modelos locais)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Ollama: roda o modelo na própria máquina (nada sai para a internet).

    GET  {url}/api/tags   lista os modelos baixados
    POST {url}/api/chat   {model, messages, tools?, stream: false, format?}
    POST {url}/api/pull   baixa um modelo (stream de progresso; ver setup.py)

Chamada de ferramentas (docs/api.md do Ollama): message.tool_calls traz
[{function: {name, arguments: {...}}}] e o resultado volta como
{role: "tool", content, tool_name}.
"""

from . import Provider, ProviderError, http_json, parse_args, strip_thinking


class Ollama(Provider):
    name = "ollama"

    @property
    def url(self):
        return self.cfg.get("url", "http://127.0.0.1:11434").rstrip("/")

    def models(self, timeout=3):
        dados = http_json(f"{self.url}/api/tags", timeout=timeout)
        return [m.get("name", "") for m in dados.get("models", [])]

    def available(self):
        try:
            nomes = self.models()
        except ProviderError as e:
            return False, f"Ollama não responde em {self.url} ({e})"
        m = self.model
        if not m:
            return False, "nenhum modelo configurado ([ollama] model)"
        if m not in nomes and f"{m}:latest" not in nomes:
            return False, f"modelo '{m}' não baixado (rode: ollama pull {m})"
        return True, f"Ollama {m}"

    def _payload(self, messages, **extra):
        p = {"model": self.model, "messages": messages, "stream": False,
             "options": {"temperature": 0.2, "num_ctx": int(self.cfg.get("num_ctx", 16384))}}
        if "think" in self.cfg:
            p["think"] = bool(self.cfg["think"])
        p.update(extra)
        return p

    def _post(self, payload):
        timeout = int(self.cfg.get("timeout", 180))
        try:
            return http_json(f"{self.url}/api/chat", payload, timeout=timeout)
        except ProviderError as e:
            texto = str(e).lower()
            if "think" in payload and "think" in texto:
                # modelo sem suporte a "think": tenta de novo sem o parâmetro
                payload = {k: v for k, v in payload.items() if k != "think"}
                return http_json(f"{self.url}/api/chat", payload, timeout=timeout)
            if "does not support tools" in texto:
                raise ProviderError(f"o modelo '{self.model}' não suporta ferramentas; use um "
                                    "modelo com suporte (ex: qwen3, llama3.1)") from None
            raise

    def chat(self, messages):
        dados = self._post(self._payload(messages, format="json"))
        texto = (dados.get("message") or {}).get("content", "")
        if not texto:
            raise ProviderError("o Ollama devolveu uma resposta vazia")
        return strip_thinking(texto)

    def chat_tools(self, messages, tools):
        dados = self._post(self._payload(messages, tools=tools))
        msg = dados.get("message") or {}
        chamadas = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            f = c.get("function") or {}
            chamadas.append({"id": c.get("id") or f"call{i}", "name": f.get("name", ""),
                             "arguments": parse_args(f.get("arguments"))})
        return {"content": strip_thinking(msg.get("content", "")), "tool_calls": chamadas}

    def assistant_message(self, resp):
        m = {"role": "assistant", "content": resp.get("content", "")}
        if resp.get("tool_calls"):
            m["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                               for c in resp["tool_calls"]]
        return m

    def tool_message(self, call, content):
        return {"role": "tool", "content": content, "tool_name": call["name"]}
