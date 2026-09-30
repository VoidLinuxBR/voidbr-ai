# -*- coding: utf-8 -*-
#
#   voidbr_ai/history.py - histórico local e log
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Histórico local em ~/.local/share/voidbr-ai/:

    sessions/     uma sessão por arquivo JSON (pergunta, achados, ações, resultado)
    diagnostics/  o estado coletado da máquina em cada diagnóstico
    logs/         voidbr-ai.log

Nunca grava credenciais: a config (que pode apontar para a chave da API)
não entra no histórico.
"""

import json
import logging
import os
import time

from . import config

log = logging.getLogger("voidbr-ai")


def _dir(nome):
    d = os.path.join(config.data_dir(), nome)
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
    except OSError:
        return None
    return d


def setup_logging(level="info", verbose=False):
    nivel = getattr(logging, str(level).upper(), logging.INFO)
    log.setLevel(logging.DEBUG if verbose else nivel)
    if log.handlers:
        return
    d = _dir("logs")
    if d:
        h = logging.FileHandler(os.path.join(d, "voidbr-ai.log"), encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    if verbose:
        s = logging.StreamHandler()
        s.setFormatter(logging.Formatter("debug: %(message)s"))
        log.addHandler(s)


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _write(nome, prefixo, dados):
    d = _dir(nome)
    if not d:
        return None
    path = os.path.join(d, f"{prefixo}-{_stamp()}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
    except OSError as e:
        log.warning("não foi possível gravar %s: %s", path, e)
        return None
    return path


def save_diagnostic(domain, data):
    return _write("diagnostics", domain, data)


def save_session(session, path=None):
    """Grava a sessão; com `path`, atualiza o mesmo arquivo (ex: depois de uma ação)."""
    if not path:
        return _write("sessions", "sessao", session)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2, default=str)
    except OSError as e:
        log.warning("não foi possível gravar %s: %s", path, e)
    return path


def list_sessions(limit=50):
    d = _dir("sessions")
    if not d:
        return []
    arquivos = sorted((f for f in os.listdir(d) if f.endswith(".json")), reverse=True)
    itens = []
    for f in arquivos[:limit]:
        path = os.path.join(d, f)
        try:
            with open(path, encoding="utf-8") as fh:
                s = json.load(fh)
        except (OSError, ValueError):
            continue
        itens.append({"path": path, "time": s.get("time", ""),
                      "question": s.get("question", ""),
                      "summary": s.get("summary", "")})
    return itens
