# -*- coding: utf-8 -*-
#
#   voidbr_ai - núcleo do VoidBR AI
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Assembled By Vilmar Catafesta for the VoidBR project.
#   Licença: MIT (veja /usr/share/licenses/voidbr-ai/LICENSE)
#
"""VoidBR AI — assistente de ajuda, diagnóstico e administração do VoidBR.

Camadas:
    agent/      núcleo: decide o que verificar, interpreta, propõe e verifica
    tools/      ferramentas explícitas (leitura e ações) + Tool Registry
    providers/  LLMs (Ollama, OpenAI) — opcionais
    context/    contexto do sistema (distro, kernel, init, ...)
    setup.py    assistente da IA local (Ollama)
    cli/        interface de linha de comando
    gui/        interface GTK4

A CLI e a GUI usam o mesmo Agent; nenhuma delas executa comandos diretamente.
"""

APP_NAME = "voidbr-ai"
APP_VERSION = "0.2.4"
