# -*- coding: utf-8 -*-
#
#   voidbr_ai/providers/openai.py - OpenAI (e APIs compatíveis)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""OpenAI Chat Completions: POST {url}/chat/completions.

Serve para qualquer servidor compatível (llama.cpp, vLLM, LM Studio...)
trocando openai.url. A chave NÃO fica no config.toml: vem da variável de
ambiente indicada em openai.api_key_env ou do arquivo em openai.api_key_file.

Chamada de ferramentas: message.tool_calls = [{id, type: "function",
function: {name, arguments: "<json>"}}]; o resultado volta como
{role: "tool", tool_call_id, content}.
"""

import json
import os

from . import Provider, ProviderError, com_retentativa, http_json, parse_args, strip_thinking


class OpenAI(Provider):
    name = "openai"

    @property
    def url(self):
        return self.cfg.get("url", "https://api.openai.com/v1").rstrip("/")

    def api_key(self):
        if self.cfg.get("_api_key"):          # digitada na GUI e ainda não salva (teste)
            return self.cfg["_api_key"]
        env = self.cfg.get("api_key_env") or "OPENAI_API_KEY"
        if os.environ.get(env):
            return os.environ[env]
        arq = os.path.expanduser(self.cfg.get("api_key_file") or "")
        if arq and os.path.isfile(arq):
            with open(arq, encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def available(self):
        if not self.model:
            return False, "nenhum modelo configurado ([openai] model)"
        local = self.url.startswith(("http://127.", "http://localhost"))
        if not self.api_key() and not local:
            return False, (f"chave da API ausente (defina ${self.cfg.get('api_key_env') or 'OPENAI_API_KEY'} "
                           "ou openai.api_key_file)")
        return True, f"OpenAI {self.model}"

    def _headers(self):
        chave = self.api_key()
        return {"Authorization": f"Bearer {chave}"} if chave else {}

    def list_models(self):
        dados = http_json(f"{self.url}/models", headers=self._headers(),
                          timeout=int(self.cfg.get("timeout", 90)))
        ids = [str(m.get("id", "")) for m in dados.get("data", []) if isinstance(m, dict)]
        # o Gemini devolve "models/gemini-…"; no pedido vai só o nome
        return sorted(i.split("/", 1)[1] if i.startswith("models/") else i for i in ids if i)

    def _post(self, payload):
        headers = self._headers()
        dados = com_retentativa(lambda: http_json(f"{self.url}/chat/completions", payload,
                                                  headers=headers,
                                                  timeout=int(self.cfg.get("timeout", 90))))
        try:
            return dados["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("resposta inesperada da API") from None

    def chat(self, messages):
        msg = self._post({"model": self.model, "messages": messages,
                          "response_format": {"type": "json_object"}})
        return strip_thinking(msg.get("content") or "")

    def answer(self, messages, on_text=None):
        texto = strip_thinking(self._post({"model": self.model, "messages": messages})
                               .get("content") or "")
        if not texto:
            raise ProviderError("a API devolveu uma resposta vazia")
        if on_text:
            on_text(texto)
        return texto

    def chat_tools(self, messages, tools):
        msg = self._post({"model": self.model, "messages": messages, "tools": tools})
        chamadas = [{"id": c.get("id", f"call{i}"), "name": (c.get("function") or {}).get("name", ""),
                     "arguments": parse_args((c.get("function") or {}).get("arguments"))}
                    for i, c in enumerate(msg.get("tool_calls") or [])]
        return {"content": strip_thinking(msg.get("content") or ""), "tool_calls": chamadas}

    def assistant_message(self, resp):
        m = {"role": "assistant", "content": resp.get("content") or None}
        if resp.get("tool_calls"):
            m["tool_calls"] = [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"],
                                             "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                               for c in resp["tool_calls"]]
        return m

    def tool_message(self, call, content):
        return {"role": "tool", "tool_call_id": call["id"], "content": content}
