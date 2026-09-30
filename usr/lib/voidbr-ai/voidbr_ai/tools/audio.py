# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/audio.py - áudio (PipeWire / ALSA)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Áudio no VoidBR.

No Void o PipeWire NÃO é um serviço runit: ele roda na sessão do usuário.
Segundo o Void Handbook, o WirePlumber e o pipewire-pulse sobem junto com o
pipewire quando existem os links em /etc/pipewire/pipewire.conf.d:

    /usr/share/examples/wireplumber/10-wireplumber.conf
    /usr/share/examples/pipewire/20-pipewire-pulse.conf

e o próprio pipewire precisa ser iniciado pela sessão (autostart do desktop,
ou exec-once no Hyprland).
"""

import os
import re

from ..util import read_file, run, which
from .privileged import run_helper, run_user
from .registry import P, Tool

CONF_D = "/etc/pipewire/pipewire.conf.d"
CONFS = {
    "wireplumber": "/usr/share/examples/wireplumber/10-wireplumber.conf",
    "pulse": "/usr/share/examples/pipewire/20-pipewire-pulse.conf",
}


def _meus_processos():
    uid = str(os.getuid())
    nomes = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        st = read_file(f"/proc/{pid}/status") or ""
        m = re.search(r"^Uid:\s+(\d+)", st, re.M)
        if m and m.group(1) == uid:
            comm = (read_file(f"/proc/{pid}/comm") or "").strip()
            nomes.add(comm)
    return nomes


def _conf_ligada(parte):
    alvo = os.path.basename(CONFS[parte])
    user = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                        "pipewire", "pipewire.conf.d", alvo)
    return os.path.exists(os.path.join(CONF_D, alvo)) or os.path.exists(user)


def _volume():
    if not which("wpctl"):
        return None
    r = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=5)
    m = re.search(r"Volume:\s*([\d.]+)", r["out"])
    if not m:
        return {"error": (r["err"] or r["out"]).strip()[:200]}
    return {"volume": float(m.group(1)), "muted": "MUTED" in r["out"]}


def _sinks():
    if not which("wpctl"):
        return []
    r = run(["wpctl", "status"], timeout=5)
    saida, dentro = [], False
    for linha in r["out"].splitlines():
        limpo = linha.strip(" │├└─")
        if limpo.startswith("Sinks:"):
            dentro = True
            continue
        if dentro:
            if not limpo or limpo.endswith(":"):
                break
            saida.append(limpo)
    return saida


def t_status():
    procs = _meus_processos()
    cartas = []
    for linha in (read_file("/proc/asound/cards") or "").splitlines():
        m = re.match(r"\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)", linha)
        if m:
            cartas.append({"index": int(m.group(1)), "id": m.group(2), "name": m.group(3)})
    pactl = run(["pactl", "info"], timeout=5) if which("pactl") else None
    servidor = ""
    if pactl and pactl["rc"] == 0:
        m = re.search(r"Server Name:\s*(.*)", pactl["out"])
        servidor = m.group(1).strip() if m else ""
    return {
        "graphical_session": bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")),
        "alsa_cards": cartas,
        "pipewire": "pipewire" in procs,
        "wireplumber": "wireplumber" in procs,
        "pipewire_pulse": "pipewire-pulse" in procs or ("pipewire" in procs and "PipeWire" in servidor),
        "pulseaudio": "pulseaudio" in procs,
        "pulse_server": servidor,
        "conf_wireplumber": _conf_ligada("wireplumber"),
        "conf_pulse": _conf_ligada("pulse"),
        "wpctl": bool(which("wpctl")),
        "default_sink": _volume(),
        "sinks": _sinks(),
    }


# ---------------------------------------------------------------------------
# ações
# ---------------------------------------------------------------------------

def a_unmute(on_line=None):
    return run_user(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], timeout=10)


def a_volume(percent, on_line=None):
    return run_user(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"], timeout=10)


def a_start(on_line=None):
    return run_user(["setsid", "-f", "pipewire"], timeout=10)


def a_conf(part, on_line=None):
    return run_helper("pipewire-conf", part, timeout=30, on_line=on_line)


def _v_unmute():
    v = _volume() or {}
    return (not v.get("muted")), "som ligado" if not v.get("muted") else "continua mudo"


def _v_volume(percent):
    v = _volume() or {}
    ok = abs(v.get("volume", -1) * 100 - percent) < 2
    return ok, f"volume em {round(v.get('volume', 0) * 100)}%"


def _v_start():
    import time
    for _ in range(10):
        p = _meus_processos()
        if "pipewire" in p and "wireplumber" in p:
            return True, "pipewire e wireplumber rodando"
        time.sleep(0.5)
    p = _meus_processos()
    return False, "pipewire " + ("rodando" if "pipewire" in p else "não iniciou") + \
        ", wireplumber " + ("rodando" if "wireplumber" in p else "não iniciou")


def _v_conf(part):
    ok = _conf_ligada(part)
    return ok, f"configuração {part} " + ("ativada" if ok else "não encontrada") + \
        " (reinicie a sessão ou o pipewire para valer)"


# ---------------------------------------------------------------------------
# check-up
# ---------------------------------------------------------------------------

def c_status(state=None, cfg=None):
    s = t_status()
    if not s["alsa_cards"]:
        s.update(summary="nenhuma placa de som", status="fail")
    elif s["pipewire"]:
        v = s["default_sink"] or {}
        extra = " (mudo)" if v.get("muted") else ""
        s.update(summary=f"PipeWire rodando, {len(s['alsa_cards'])} placa(s){extra}",
                 status="warn" if extra or not s["wireplumber"] else "ok")
    elif s["pulseaudio"]:
        s.update(summary="PulseAudio rodando", status="ok")
    else:
        s.update(summary="nenhum servidor de áudio rodando",
                 status="fail" if s["graphical_session"] else "info")
    return s


STEPS = [("audio.c_status", "Verificando o áudio", "audio")]
KEYWORDS = ["audio", "som", "sem som", "microfone", "mic", "alto-falante", "caixa de som",
            "fone", "headphone", "pipewire", "wireplumber", "pulseaudio", "alsa", "volume", "mudo",
            "hdmi"]


def _achado(code, sev, title, detail="", sug=None, confirmed=True):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": "audio",
            "confirmed": confirmed, "suggestions": sug or []}


def analyze(state, reg):
    achados, acoes = [], []

    def acao(tool, args, reason, fixes):
        try:
            acoes.append(reg.make_action(tool, args, reason=reason, fixes=fixes))
        except ValueError:
            pass

    s = state.get("audio", {})
    if not s:
        return achados, acoes
    if not s["alsa_cards"]:
        achados.append(_achado("no_soundcard", "erro", "Nenhuma placa de som detectada",
                               "O kernel não expôs nenhum dispositivo de áudio (ALSA). Costuma ser "
                               "firmware faltando (notebooks recentes usam o sof-firmware).",
                               ["Veja o driver: lspci -k | grep -A3 -i audio",
                                "Instale: vinstall sof-firmware alsa-firmware (e reinicie)"]))
    if s["graphical_session"] and not s["pipewire"] and not s["pulseaudio"]:
        achados.append(_achado("pipewire_down", "erro", "O PipeWire não está rodando na sua sessão",
                               "No Void o PipeWire não é um serviço runit: a sessão gráfica precisa "
                               "iniciá-lo (autostart ou, no Hyprland, exec-once = pipewire).",
                               ["Hyprland: adicione 'exec-once = pipewire' ao hyprland.conf",
                                "Outros: ln -s /usr/share/applications/pipewire.desktop "
                                "/etc/xdg/autostart/"]))
        acao("audio.start", {}, "PipeWire parado nesta sessão", ["pipewire_down"])
    for parte, proc, code, titulo in (
            ("wireplumber", "wireplumber", "no_wireplumber", "O WirePlumber não está ativo"),
            ("pulse", "pipewire_pulse", "no_pipewire_pulse", "O pipewire-pulse não está ativo")):
        if s["pipewire"] and not s[proc]:
            if not s[f"conf_{parte}"]:
                achados.append(_achado(code, "erro" if parte == "wireplumber" else "aviso", titulo,
                                       f"Falta o link da configuração em {CONF_D} (Void Handbook). "
                                       + ("Sem o WirePlumber nenhum dispositivo aparece."
                                          if parte == "wireplumber" else
                                          "Sem ele, programas que usam PulseAudio ficam mudos.")))
                acao("audio.enable_conf", {"part": parte}, f"ativa o {parte} junto com o pipewire",
                     [code])
            else:
                achados.append(_achado(code, "aviso", titulo,
                                       "A configuração existe, mas o processo não está rodando: "
                                       "reinicie a sessão (ou o pipewire).", confirmed=False))
    if s["pipewire_pulse"] and s["pulseaudio"]:
        achados.append(_achado("pulse_conflict", "aviso", "PulseAudio e pipewire-pulse rodando juntos",
                               "Os dois disputam o áudio; normalmente só um deve rodar.",
                               ["Remova o autostart do pulseaudio (ou o pacote pulseaudio)"]))
    v = s.get("default_sink") or {}
    if v.get("muted"):
        achados.append(_achado("muted", "aviso", "A saída de som padrão está no mudo"))
        acao("audio.unmute", {}, "saída padrão no mudo", ["muted"])
    elif v.get("volume") is not None and v["volume"] < 0.05:
        achados.append(_achado("volume_zero", "aviso", "O volume da saída padrão está em zero"))
        acao("audio.volume", {"percent": 50}, "volume zerado", ["volume_zero"])
    if not achados:
        achados.append(_achado("audio_ok", "ok", "O áudio está configurado",
                               s.get("pulse_server") or "PipeWire + WirePlumber rodando"))
    return achados, acoes


def register(reg):
    reg.register(Tool("audio.status", "Verificando o áudio",
                      "Estado do áudio: placas ALSA, PipeWire/WirePlumber/pipewire-pulse/PulseAudio "
                      "rodando na sessão, links de configuração do Void, saída padrão, volume e mudo.",
                      t_status, domain="audio"))
    reg.register(Tool("audio.unmute", "Tirar o mudo", "Tira o mudo da saída de som padrão (wpctl).",
                      a_unmute, kind="action", domain="audio", root=False,
                      title="Tirar o mudo da saída de som",
                      preview=lambda: "wpctl set-mute @DEFAULT_AUDIO_SINK@ 0", verify=_v_unmute))
    reg.register(Tool("audio.volume", "Ajustar o volume", "Ajusta o volume da saída padrão (wpctl).",
                      a_volume, kind="action", domain="audio", root=False,
                      params={"percent": P("integer", "volume em %", minimum=0, maximum=100)},
                      required=["percent"], title="Ajustar o volume para {percent}%",
                      preview=lambda percent: f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {percent}%",
                      verify=_v_volume))
    reg.register(Tool("audio.start", "Iniciar o PipeWire",
                      "Inicia o PipeWire nesta sessão (ele sobe o WirePlumber e o pipewire-pulse "
                      "se as configurações do Void estiverem ativas).", a_start, kind="action",
                      domain="audio", root=False, title="Iniciar o PipeWire nesta sessão",
                      preview=lambda: "setsid -f pipewire", verify=_v_start))
    reg.register(Tool("audio.enable_conf", "Ativar configuração do PipeWire",
                      "Cria o link da configuração do WirePlumber ou do pipewire-pulse em "
                      "/etc/pipewire/pipewire.conf.d (como manda o Void Handbook).", a_conf,
                      kind="action", domain="audio",
                      params={"part": P("string", "wireplumber ou pulse", enum=["wireplumber", "pulse"])},
                      required=["part"], title="Ativar o {part} no PipeWire",
                      preview=lambda part: f"ln -s {CONFS[part]} {CONF_D}/", verify=_v_conf))


def register_checks(reg):
    reg.register(Tool("audio.c_status", STEPS[0][1], STEPS[0][1], c_status, domain="audio",
                      llm=False, internal=True))
