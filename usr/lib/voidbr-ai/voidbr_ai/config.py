# -*- coding: utf-8 -*-
#
#   voidbr_ai/config.py - configuração (TOML)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Configuração do VoidBR AI.

Ordem de leitura (a seguinte sobrescreve a anterior):
    1. padrões embutidos (DEFAULTS)
    2. /etc/voidbr-ai/config.toml          (global)
    3. ~/.config/voidbr-ai/config.toml     (usuário)

Segredos (chave da OpenAI) não ficam no arquivo: a config guarda só o NOME
da variável de ambiente (openai.api_key_env) ou o caminho de um arquivo
(openai.api_key_file) com permissão restrita.
"""

import copy
import os
import tomllib

GLOBAL_CONFIG = "/etc/voidbr-ai/config.toml"

DEFAULTS = {
    "provider": "auto",              # auto | none | ollama | openai
                                     # auto = usa o Ollama local se estiver rodando com modelo
    "ollama": {
        "url": "http://127.0.0.1:11434",
        "model": "qwen3:4b",
        "timeout": 180,
        "num_ctx": 8192,             # contexto (tokens); maior = mais memória
        "keep_alive": "30m",         # tempo que o modelo fica carregado depois da última pergunta
        "think": False,              # qwen3: responde sem o modo "pensando" (bem mais rápido)
    },
    "openai": {
        "url": "https://api.openai.com/v1",   # qualquer API compatível
        "model": "",
        "api_key_env": "OPENAI_API_KEY",
        "api_key_file": "",
        "timeout": 90,
    },
    "network": {
        "ping_targets": ["1.1.1.1", "8.8.8.8"],
        "dns_test_hosts": ["voidbr.org", "voidlinux.org"],
        "ping_timeout": 2,
        "dns_timeout": 5,
    },
    "agent": {
        # quantas consultas ao sistema a IA pode fazer antes de responder
        "max_steps": 8,
        # depois de uma correção, quantas vezes refazer o diagnóstico
        # (e o intervalo em segundos) até considerar o problema resolvido
        "verify_attempts": 4,
        "verify_interval": 4,
    },
    "tools": {
        "disabled": [],              # ex: ["network.connectivity"]
    },
    "gui": {
        "width": 900,
        "height": 740,
        "ai_setup": "",              # "" = perguntar | "dispensado" | "feito"
    },
    "log": {
        "level": "info",             # debug | info | warning | error
    },
}


def user_config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "voidbr-ai")


def user_config_path():
    return os.environ.get("VOIDBR_AI_CONFIG") or os.path.join(user_config_dir(), "config.toml")


def data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "voidbr-ai")


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _read(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        # config quebrada não pode impedir o diagnóstico
        import logging
        logging.getLogger("voidbr-ai").warning("config ignorada (%s): %s", path, e)
        return {}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    _merge(cfg, _read(GLOBAL_CONFIG))
    _merge(cfg, _read(user_config_path()))
    return cfg


def read_user():
    """Só o que está no arquivo do usuário (para editar sem copiar os padrões)."""
    return _read(user_config_path())


# ---------------------------------------------------------------------------
# escrita (TOML simples: valores escalares, listas e tabelas de 1 nível)
# ---------------------------------------------------------------------------

def _valor(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_valor(i) for i in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def dumps(cfg):
    linhas = ["# VoidBR AI - configuração do usuário", ""]
    for k, v in cfg.items():
        if not isinstance(v, dict):
            linhas.append(f"{k} = {_valor(v)}")
    for k, v in cfg.items():
        if isinstance(v, dict):
            linhas += ["", f"[{k}]"]
            for kk, vv in v.items():
                if not isinstance(vv, dict):
                    linhas.append(f"{kk} = {_valor(vv)}")
    return "\n".join(linhas) + "\n"


def save_user(changes):
    """Mescla `changes` no arquivo do usuário e grava."""
    atual = _merge(read_user(), changes)
    path = user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(dumps(atual))
    os.replace(tmp, path)
    return path
