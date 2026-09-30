# -*- coding: utf-8 -*-
#
#   voidbr_ai/monitor.py - avisos em segundo plano (opcional)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Check-up leve de tempos em tempos, com notificação no desktop (notify-send).

    voidbr-ai --monitor         roda em segundo plano (iniciado com a sessão)
    voidbr-ai --monitor-once    uma checagem só (para testar)

Só lê o sistema (as mesmas regras do check-up, sem IA e sem nenhuma ação) e só
avisa de problemas novos: o mesmo aviso não se repete por 24 horas. Clicar em
"Abrir" na notificação abre o VoidBR AI.

Para iniciar com a sessão: a GUI cria ~/.config/autostart/voidbr-ai-monitor.desktop
(ambientes que seguem o XDG autostart); no Hyprland use
    exec-once = voidbr-ai --monitor
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time

from . import config, tools

log = logging.getLogger("voidbr-ai")

PADRAO_DOMINIOS = ["storage", "packages", "services", "boot"]
REPETIR_APOS = 24 * 3600
AUTOSTART = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                         "autostart", "voidbr-ai-monitor.desktop")
DESKTOP = """[Desktop Entry]
Type=Application
Name=VoidBR AI (avisos)
Comment=Check-up leve do sistema de tempos em tempos, com notificação
Exec=voidbr-ai --monitor
Icon=dialog-information
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def _estado_path():
    return os.path.join(config.data_dir(), "monitor.json")


def _ler_estado():
    try:
        with open(_estado_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"avisados": {}}


def _gravar_estado(st):
    try:
        os.makedirs(config.data_dir(), mode=0o700, exist_ok=True)
        with open(_estado_path(), "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning("monitor: não foi possível gravar o estado: %s", e)


def checar(agent, dominios=None):
    """Problemas (erro/aviso) encontrados agora: [{code, severity, title, domain}]."""
    probs = []
    for dom in dominios or PADRAO_DOMINIOS:
        if dom not in tools.DOMAINS:
            continue
        try:
            rep = agent.diagnose(dom, use_llm=False, quiet=True)
        except Exception:  # um domínio com problema não derruba o monitor
            log.exception("monitor: %s falhou", dom)
            continue
        probs += [{"code": f"{dom}:{f['code']}", "severity": f["severity"], "title": f["title"],
                   "domain": dom} for f in rep.findings if f["severity"] in ("erro", "aviso")]
    return probs


def _abrir_gui():
    gui = shutil.which("voidbr-ai-gui")
    if gui:
        subprocess.Popen([gui], start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def notificar(titulo, corpo, urgente=False):
    ns = shutil.which("notify-send")
    if not ns:
        log.info("monitor: notify-send não encontrado (pacote libnotify): %s — %s", titulo, corpo)
        print(f"{titulo}\n{corpo}")
        return False
    base = [ns, "-a", "VoidBR AI", "-i", "dialog-warning" if urgente else "dialog-information",
            "-u", "critical" if urgente else "normal"]
    ajuda = subprocess.run([ns, "--help"], capture_output=True, text=True).stdout

    if "--action" in ajuda:
        # espera o clique em outra thread (o notify-send fica aberto até a notificação sumir)
        def esperar():
            try:
                r = subprocess.run(base + ["--action=abrir=Abrir o VoidBR AI", titulo, corpo],
                                   capture_output=True, text=True, timeout=3600)
                if r.stdout.strip() == "abrir":
                    _abrir_gui()
            except (subprocess.TimeoutExpired, OSError):
                pass
        threading.Thread(target=esperar, daemon=True).start()
    else:
        subprocess.run(base + [titulo, corpo], timeout=15)
    return True


def uma_vez(agent, dominios=None, forcar=False):
    """Uma checagem: notifica o que for novo. Devolve os problemas avisados."""
    st = _ler_estado()
    agora = time.time()
    avisados = {k: v for k, v in st.get("avisados", {}).items() if agora - v < REPETIR_APOS}
    probs = checar(agent, dominios)
    novos = [p for p in probs if forcar or p["code"] not in avisados]
    if novos:
        urgente = any(p["severity"] == "erro" for p in novos)
        linhas = [("❌ " if p["severity"] == "erro" else "⚠️ ") + p["title"] for p in novos[:4]]
        if len(novos) > 4:
            linhas.append(f"… e mais {len(novos) - 4}")
        notificar("VoidBR AI: " + (f"{len(novos)} problema(s) no sistema" if len(novos) > 1
                                   else "um problema no sistema"),
                  "\n".join(linhas) + "\nAbra o VoidBR AI para ver e corrigir.", urgente)
        for p in novos:
            avisados[p["code"]] = agora
    st["avisados"] = avisados
    st["ultima"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _gravar_estado(st)
    return novos


def _pidfile():
    base = os.environ.get("XDG_RUNTIME_DIR") or config.data_dir()
    return os.path.join(base, "voidbr-ai-monitor.pid")


def _ja_rodando():
    try:
        with open(_pidfile()) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return pid if b"--monitor" in f.read() else 0
    except (OSError, ValueError):
        return 0


def loop(agent):
    """--monitor: roda até a sessão acabar. Espera um pouco no início para não
    pesar no login."""
    cfg = agent.cfg.get("monitor", {})
    pid = _ja_rodando()
    if pid:
        print(f"voidbr-ai: o monitor já está rodando (pid {pid})")
        return 0
    try:
        with open(_pidfile(), "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    horas = max(1.0, float(cfg.get("interval_hours", 6)))
    dominios = cfg.get("domains") or PADRAO_DOMINIOS
    time.sleep(float(cfg.get("start_delay", 120)))
    while True:
        try:
            uma_vez(agent, dominios)
        except Exception:
            log.exception("monitor: checagem falhou")
        time.sleep(horas * 3600)


def autostart(ligar):
    """Cria/remove ~/.config/autostart/voidbr-ai-monitor.desktop."""
    if ligar:
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        with open(AUTOSTART, "w", encoding="utf-8") as f:
            f.write(DESKTOP)
    elif os.path.exists(AUTOSTART):
        os.remove(AUTOSTART)
    return AUTOSTART


def parar():
    pid = _ja_rodando()
    if pid:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    return pid


def iniciar():
    """Inicia o monitor agora (desacoplado da GUI)."""
    if _ja_rodando():
        return False
    exe = shutil.which("voidbr-ai")
    if not exe:
        return False
    subprocess.Popen([exe, "--monitor"], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
