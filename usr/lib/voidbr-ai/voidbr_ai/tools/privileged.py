# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/privileged.py - execução de ações
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Execução das ações confirmadas.

Ações root passam pelo helper /usr/lib/voidbr-ai/voidbr-ai-helper via pkexec.
O helper tem a sua própria lista branca de verbos e valida os argumentos:
mesmo que alguém chame o pkexec direto, ele não executa nada fora dela.

A saída é lida linha a linha (on_line) para a GUI/CLI mostrarem o progresso
de operações longas (instalar pacotes, atualizar o sistema).
"""

import os
import re
import subprocess
import threading
import unicodedata

# instalado: /usr/lib/voidbr-ai/voidbr-ai-helper
# no repositório: <repo>/usr/lib/voidbr-ai/voidbr-ai-helper
HELPER = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                       "voidbr-ai-helper"))


def _stream(argv, timeout, on_line, env=None):
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors="replace", env=env)
    except FileNotFoundError as e:
        return 127, f"não encontrado: {e.filename}", False
    linhas = []
    estourou = [False]

    def matar():
        estourou[0] = True
        p.kill()

    t = threading.Timer(timeout, matar)
    t.start()
    try:
        for linha in p.stdout:
            linha = linha.rstrip("\n")
            linhas.append(linha)
            if on_line and linha.strip():
                try:
                    on_line(linha)
                except Exception:
                    pass
        p.wait()
    finally:
        t.cancel()
    # guarda só o final (a saída de um update pode ser enorme)
    return p.returncode, "\n".join(linhas[-60:]), estourou[0]


# snapshot antes da ação (definido pelo Registry.execute na thread que executa)
_local = threading.local()


def set_snapshot(desc):
    """Descrição do snapshot para o próximo run_helper desta thread (None = sem snapshot)."""
    if desc:
        t = unicodedata.normalize("NFKD", desc)
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = re.sub(r"[^A-Za-z0-9 ._:/()+,-]", "", t).strip()[:80]
        desc = t or None
    _local.snapshot = desc


def run_helper(verb, *args, timeout=600, on_line=None):
    """Roda o helper (root) e devolve dict {ok, rc, out, err, cancelled, snapshot}."""
    snap = getattr(_local, "snapshot", None)
    _local.snapshot = None
    argv = [HELPER, *(["--snapshot", snap] if snap else []), verb, *[str(a) for a in args]]
    if os.geteuid() != 0:
        argv = ["pkexec", *argv]
    rc, out, estourou = _stream(argv, timeout, on_line)
    if estourou:
        return {"ok": False, "rc": 124, "out": out, "err": "tempo esgotado", "cancelled": False}
    # pkexec: 126 = autenticação cancelada/negada, 127 = não autorizado
    cancelado = argv[0] == "pkexec" and rc in (126, 127) and "OK:" not in out
    m = re.search(r"^SNAPSHOT: (\d+)$", out, re.M)
    return {"ok": rc == 0, "rc": rc, "out": out.strip(), "err": "", "cancelled": cancelado,
            "snapshot": int(m.group(1)) if m else None}


def run_user(argv, timeout=60, on_line=None):
    """Ação que roda como o próprio usuário (sem pkexec)."""
    rc, out, estourou = _stream(argv, timeout, on_line)
    return {"ok": rc == 0 and not estourou, "rc": 124 if estourou else rc, "out": out.strip(),
            "err": "tempo esgotado" if estourou else "", "cancelled": False}
