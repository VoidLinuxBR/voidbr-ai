# -*- coding: utf-8 -*-
#
#   voidbr_ai/util.py - execução de comandos e leitura do sistema
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Utilitários usados pelas ferramentas.

Todos os comandos rodam com argv explícito (nunca shell=True) e LC_ALL=C,
para que a saída seja previsível na hora de interpretar.
"""

import logging
import os
import shutil
import subprocess

log = logging.getLogger("voidbr-ai")

_ENV = dict(os.environ, LC_ALL="C", LANG="C")


def which(prog):
    """Procura também em /usr/sbin e /sbin (fora do PATH de alguns usuários)."""
    return shutil.which(prog) or shutil.which(prog, path="/usr/sbin:/sbin:/usr/bin:/bin")


def run(argv, timeout=10):
    """Executa argv e devolve dict {cmd, rc, out, err, missing, timeout}."""
    res = {"cmd": " ".join(argv), "rc": None, "out": "", "err": "",
           "missing": False, "timeout": False}
    prog = which(argv[0])
    if not prog:
        res["missing"] = True
        res["rc"] = 127
        return res
    try:
        p = subprocess.run([prog, *argv[1:]], capture_output=True, text=True,
                           timeout=timeout, env=_ENV)
        res.update(rc=p.returncode, out=p.stdout, err=p.stderr)
    except subprocess.TimeoutExpired:
        res.update(rc=124, timeout=True)
    except OSError as e:
        res.update(rc=126, err=str(e))
    log.debug("run %s -> %s", res["cmd"], res["rc"])
    return res


def read_file(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def read_int(path, default=None):
    v = read_file(path)
    try:
        return int(v.strip())
    except (AttributeError, ValueError):
        return default


def running_processes():
    """Nomes (comm) dos processos em execução, lidos de /proc."""
    nomes = set()
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return nomes
    for pid in pids:
        comm = read_file(f"/proc/{pid}/comm")
        if comm:
            nomes.add(comm.strip())
    return nomes
