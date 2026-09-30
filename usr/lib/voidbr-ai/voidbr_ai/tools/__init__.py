# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools - ferramentas explícitas
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Módulos de ferramentas.

Cada módulo registra:
  - ferramentas de LEITURA que o LLM pode chamar (register)
  - AÇÕES, que só rodam com confirmação (register)
  - e, se tiver check-up sem LLM: STEPS, KEYWORDS, analyze(state, reg) e
    register_checks(reg)

Um domínio novo (ex: vídeo, impressora) é um módulo novo aqui; o Agent, a CLI e
a GUI não mudam.
"""

from . import audio, bluetooth, network, packages, services, storage, system
from .registry import (Action, InvalidArgs, NotConfirmed, Registry, Tool,  # noqa: F401
                       ToolDisabled)

# domínios com check-up por regras (funcionam sem LLM), na ordem do check-up geral
DOMAINS = {
    "network": network,
    "storage": storage,
    "packages": packages,
    "services": services,
    "audio": audio,
    "bluetooth": bluetooth,
    "system": system,
}

LABELS = {
    "network": "🌐 Rede",
    "storage": "💾 Disco",
    "packages": "📦 Pacotes",
    "services": "⚙️ Serviços",
    "audio": "🔊 Áudio",
    "bluetooth": "🔵 Bluetooth",
    "system": "🧠 Memória e CPU",
}

ALIASES = {"rede": "network", "disk": "storage", "disco": "storage", "pacotes": "packages",
           "servicos": "services", "audio": "audio", "som": "audio", "sistema": "system",
           "memoria": "system"}


def build_registry(disabled=None):
    reg = Registry(disabled)
    for mod in (system, services, packages, storage, network, audio, bluetooth):
        mod.register(reg)
        if hasattr(mod, "register_checks"):
            mod.register_checks(reg)
    return reg
