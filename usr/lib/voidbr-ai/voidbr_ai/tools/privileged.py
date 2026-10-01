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
import pty
import re
import select
import signal
import subprocess
import termios
import threading
import time
import unicodedata

# instalado: /usr/lib/voidbr-ai/voidbr-ai-helper
# no repositório: <repo>/usr/lib/voidbr-ai/voidbr-ai-helper
HELPER = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                       "voidbr-ai-helper"))


# Na GUI o pkexec precisa de um agente gráfico do polkit. Sem desligar o terminal,
# o pkexec pediria a senha no terminal de onde a GUI foi aberta (e a janela ficaria
# parada em "Executando…"). A GUI liga isto; a CLI continua pedindo no terminal.
SEM_TERMINAL = False

SEM_AGENTE = ("Nenhum agente do polkit está rodando para pedir a sua senha, então nada foi "
              "executado. Instale um agente (ex: polkit-gnome) e inicie-o com a sessão, "
              "ou rode a ação pelo terminal com: voidbr-ai")

# Sem agente, a GUI pede a senha na própria janela: função (texto) -> senha | None,
# chamada na thread que executa a ação. A GUI define; None = não pedir.
PEDIR_SENHA = None

# agentes do polkit que dá para iniciar sozinho (executável -> pacote do Void)
AGENTES = [
    ("/usr/libexec/polkit-gnome-authentication-agent-1", "polkit-gnome"),
    ("/usr/libexec/xfce-polkit", "xfce-polkit"),
    ("/usr/bin/lxqt-policykit-agent", "lxqt-policykit"),
    ("/usr/libexec/polkit-mate-authentication-agent-1", "mate-polkit"),
    ("/usr/libexec/hyprpolkitagent", "hyprpolkitagent"),
    ("/usr/lib/hyprpolkitagent/hyprpolkitagent", "hyprpolkitagent"),
    ("/usr/bin/hyprpolkitagent", "hyprpolkitagent"),
    ("/usr/libexec/polkit-kde-authentication-agent-1", "polkit-kde-agent"),
    ("/usr/bin/lxpolkit", "lxpolkit"),
]
AGENTE_PADRAO = ("/usr/libexec/polkit-gnome-authentication-agent-1", "polkit-gnome")


def agente_instalado():
    """Primeiro agente do polkit instalado (caminho), ou ""."""
    return next((c for c, _p in AGENTES if os.access(c, os.X_OK)), "")


def iniciar_agente():
    """Inicia um agente instalado, desacoplado (fica rodando na sessão). Devolve o caminho."""
    caminho = agente_instalado()
    if not caminho:
        return ""
    try:
        subprocess.Popen([caminho], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return ""
    return caminho


def _sem_agente(texto):
    t = texto.lower()
    return "no authentication agent" in t or "textual authentication agent" in t


def _pkexec_com_senha(argv, timeout, on_line, primeira=True):
    """Roda o pkexec num terminal simulado (pty): sem agente gráfico, o próprio pkexec pede
    a senha nesse terminal ("Password:") e a GUI responde com a senha digitada na janela.
    A senha só passa da memória para o pkexec: não é gravada nem aparece na saída."""
    env = dict(os.environ, LC_ALL="C", LANG="C")
    pid, fd = pty.fork()
    if pid == 0:                                   # filho: vira o pkexec
        try:
            os.execvpe(argv[0], argv, env)
        finally:
            os._exit(127)
    # sem eco no terminal simulado: a senha nunca volta na saída (o pkexec também desliga
    # o eco, mas só depois de mostrar a pergunta; assim não há corrida)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except termios.error:
        pass
    buf, linhas, cancelado, falhou = "", [], False, False
    segredo = None
    limite = time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > limite:
                os.kill(pid, signal.SIGKILL)
                break
            r, _w, _x = select.select([fd], [], [], 0.2)
            if not r:
                continue
            try:
                dados = os.read(fd, 4096).decode("utf-8", "replace")
            except OSError:                        # o pkexec terminou (EIO no pty)
                break
            if not dados:
                break
            buf += re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", dados).replace("\r", "")
            # linhas completas: saída normal (vai para a tela)
            while "\n" in buf:
                linha, buf = buf.split("\n", 1)
                if "AUTHENTICATION FAILED" in linha:
                    falhou = True
                if segredo is not None and linha.strip() == segredo:
                    continue                       # segurança extra: nunca mostra a senha
                if linha.strip() and not linha.startswith("===="):
                    linhas.append(linha)
                    if on_line:
                        try:
                            on_line(linha)
                        except Exception:
                            pass
            # perguntas sem quebra de linha no fim
            m = re.search(r"Choose identity to authenticate as \(1-(\d+)\):\s*$", buf)
            if m:
                eu = os.environ.get("USER") or ""
                opcoes = re.findall(r"^\s*(\d+)\.\s+(.*)$", "\n".join(linhas[-20:]), re.M)
                escolha = next((n for n, nome in opcoes if eu and f"({eu})" in nome or nome.strip() == eu), "1")
                os.write(fd, (escolha + "\n").encode())
                buf = ""
                continue
            if re.search(r"(password|senha)[^:\n]*:\s*$", buf, re.I):
                texto = ("O VoidBR AI precisa da sua senha para executar esta ação como administrador."
                         if primeira and not falhou else "Senha incorreta. Digite de novo:")
                senha = PEDIR_SENHA(texto) if PEDIR_SENHA else None
                if senha is None:
                    cancelado = True
                    os.kill(pid, signal.SIGTERM)
                    break
                os.write(fd, (senha + "\n").encode())
                segredo, senha = senha, None
                buf = ""
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        _p, status = os.waitpid(pid, 0)
        rc = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        rc = 1
    segredo = None
    out = "\n".join(linhas[-60:])
    return rc, out, cancelado, falhou


def _stream(argv, timeout, on_line, env=None):
    try:
        extra = {"stdin": subprocess.DEVNULL, "start_new_session": True} if SEM_TERMINAL else {}
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors="replace", env=env, **extra)
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
    def linha_visivel(t):
        if on_line and not _sem_agente(t):      # não mostra o erro do pkexec sem agente
            on_line(t)
    rc, out, estourou = _stream(argv, timeout, linha_visivel)
    if estourou:
        return {"ok": False, "rc": 124, "out": out, "err": "tempo esgotado", "cancelled": False}
    aviso = ""
    # quem decide se há agente é o próprio pkexec (não dá para adivinhar pelo nome do
    # processo: há agentes embutidos, como o do gnome-shell, sem processo próprio)
    if argv[0] == "pkexec" and _sem_agente(out) and SEM_TERMINAL:
        # 1) há um agente instalado mas parado: inicia e tenta de novo
        if iniciar_agente():
            for espera in (1.5, 2.5):
                time.sleep(espera)
                rc, out, estourou = _stream(argv, timeout, linha_visivel)
                if not _sem_agente(out):
                    break
        # 2) nenhum agente: a própria janela pede a senha (pkexec num pty)
        if _sem_agente(out) and PEDIR_SENHA:
            for tentativa in range(3):
                rc, out, cancelado, falhou = _pkexec_com_senha(argv, timeout, on_line,
                                                               primeira=tentativa == 0)
                if cancelado:
                    return {"ok": False, "rc": 126, "out": out, "err": "", "cancelled": True,
                            "snapshot": None, "sem_agente": True}
                if not falhou:
                    break
            aviso = "sem_agente"
            if falhou:
                return {"ok": False, "rc": rc, "out": "Senha incorreta (3 tentativas). Nada foi executado.",
                        "err": "", "cancelled": False, "snapshot": None, "sem_agente": True}
    if argv[0] == "pkexec" and _sem_agente(out):
        return {"ok": False, "rc": rc, "out": SEM_AGENTE, "err": SEM_AGENTE, "cancelled": False,
                "snapshot": None, "sem_agente": True}
    # pkexec: 126 = autenticação cancelada/negada, 127 = não autorizado
    cancelado = argv[0] == "pkexec" and rc in (126, 127) and "OK:" not in out
    m = re.search(r"^SNAPSHOT: (\d+)$", out, re.M)
    return {"ok": rc == 0, "rc": rc, "out": out.strip(), "err": "", "cancelled": cancelado,
            "snapshot": int(m.group(1)) if m else None, "sem_agente": aviso == "sem_agente"}


def run_user(argv, timeout=60, on_line=None):
    """Ação que roda como o próprio usuário (sem pkexec)."""
    rc, out, estourou = _stream(argv, timeout, on_line)
    return {"ok": rc == 0 and not estourou, "rc": 124 if estourou else rc, "out": out.strip(),
            "err": "tempo esgotado" if estourou else "", "cancelled": False}
