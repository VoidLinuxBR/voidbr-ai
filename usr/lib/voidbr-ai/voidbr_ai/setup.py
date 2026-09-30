# -*- coding: utf-8 -*-
#
#   voidbr_ai/setup.py - assistente de configuração da IA local (Ollama)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Assistente de primeira execução: IA local com o Ollama.

    1. instala o voidbr-ollama (se preciso) e a aceleração da placa de vídeo:
       NVIDIA -> voidbr-ollama-cuda (bibliotecas CUDA, ~2 GB)
       AMD    -> vulkan-loader + mesa-vulkan-radeon (Vulkan, ligado por padrão no Ollama)
       Intel  -> vulkan-loader + mesa-vulkan-intel                   → pkexec
    2. habilita/inicia o serviço runit ollama (se preciso) → pkexec
    3. baixa o modelo escolhido pela API (/api/pull), com progresso
    4. testa se o modelo responde com chamada de ferramentas
    5. grava provider = "ollama" e o modelo em ~/.config/voidbr-ai/config.toml

O modelo sugerido depende da memória da máquina. Tamanhos da biblioteca do
Ollama (ollama.com/library/qwen3, set/2026); todos suportam ferramentas.
Nada é feito sem o usuário confirmar a lista de passos.
"""

import json
import os
import time
import urllib.error
import urllib.request

from . import config
from .providers import ProviderError
from .providers.ollama import Ollama
from .tools import packages as pkgs
from .tools import services as svc
from .util import read_file, run, which

PACOTE = "voidbr-ollama"              # binário + CPU/Vulkan + serviço (~100 MB)
PACOTE_CUDA = "voidbr-ollama-cuda"    # bibliotecas CUDA para NVIDIA (~2,1 GB)
SERVICO = "ollama"
LIB_DIR = "/usr/lib/ollama"

# (tag, download em GB, RAM mínima em GB, descrição)
MODELOS = [
    ("qwen3:1.7b", 1.4, 4, "leve — para máquinas com pouca memória"),
    ("qwen3:4b", 2.5, 8, "equilibrado — bom para a maioria das máquinas"),
    ("qwen3:8b", 5.2, 16, "mais preciso — 16 GB de RAM ou placa de vídeo com 8 GB"),
    ("qwen3:14b", 9.3, 32, "o mais preciso — 32 GB de RAM ou placa de vídeo com 12 GB+"),
]


def gb(x):
    """2.5 -> '2,5' (pt_BR)."""
    return f"{x:.1f}".replace(".", ",")


def hardware():
    ram = 0
    for linha in (read_file("/proc/meminfo") or "").splitlines():
        if linha.startswith("MemTotal"):
            ram = int(linha.split()[1]) / 1048576
    gpus = []
    r = run(["lspci"], timeout=5)
    for l in r["out"].splitlines():
        if " VGA " in l or "3D controller" in l or "Display controller" in l:
            gpus.append(l.split(": ", 1)[-1])
    livre = 0
    for alvo in ("/var/lib", "/"):
        try:
            st = os.statvfs(alvo)
            livre = st.f_bavail * st.f_frsize / 1073741824
            break
        except OSError:
            continue
    return {"ram_gb": round(ram, 1), "gpus": gpus, "free_disk_gb": round(livre, 1),
            "nvidia": any("nvidia" in g.lower() for g in gpus),
            "amd": any(("amd" in g.lower() or "ati " in g.lower() or "radeon" in g.lower())
                       for g in gpus),
            "intel": any("intel" in g.lower() for g in gpus)}


def recommend(hw):
    ram = hw["ram_gb"]
    if ram >= 30:
        return "qwen3:8b"          # o 14b fica como opção, não como sugestão
    if ram >= 14 or (hw["nvidia"] and ram >= 12):
        return "qwen3:8b"
    if ram >= 7:
        return "qwen3:4b"
    return "qwen3:1.7b"


def model_info(tag):
    return next((m for m in MODELOS if m[0] == tag), (tag, 0, 0, ""))


def state(cfg=None):
    cfg = cfg or config.load()
    prov = Ollama(cfg.get("ollama", {}))
    st = svc.status(SERVICO)
    d = {"installed": bool(which("ollama")), "service_available": st["available"],
         "enabled": st["enabled"], "running": st["running"], "api": False, "models": [],
         "url": prov.url,
         "cuda": any(os.path.isdir(os.path.join(LIB_DIR, v)) for v in ("cuda_v12", "cuda_v13"))}
    try:
        d["models"] = prov.models()
        d["api"] = True
    except ProviderError:
        pass
    return d


def gpu_packages(hw):
    """Aceleração para a placa: (pacotes, descrição). NVIDIA tem prioridade (notebook híbrido)."""
    hw = hw or {}
    if hw.get("nvidia"):
        return [PACOTE_CUDA], "placa NVIDIA, via CUDA"
    if hw.get("amd"):
        return ["vulkan-loader", "mesa-vulkan-radeon"], "placa AMD, via Vulkan"
    if hw.get("intel"):
        return ["vulkan-loader", "mesa-vulkan-intel"], "placa Intel, via Vulkan"
    return [], ""


def missing_packages(st, hw=None):
    """Pacotes que faltam: o voidbr-ollama e a aceleração da placa de vídeo."""
    pacotes = [] if st["installed"] else [PACOTE]
    for p in gpu_packages(hw)[0]:
        ja = st.get("cuda") if p == PACOTE_CUDA else pkgs.installed(p)
        if not ja:
            pacotes.append(p)
    return pacotes


def plan(st, modelo, hw=None):
    """Passos que ainda faltam: [(tipo, descrição, comando)]."""
    passos = []
    pacotes = missing_packages(st, hw)
    if pacotes:
        partes = []
        if PACOTE in pacotes:
            partes.append(f"{PACOTE} (~100 MB)")
        placa = gpu_packages(hw)[1]
        if PACOTE_CUDA in pacotes:
            partes.append(f"{PACOTE_CUDA} (~2,1 GB, aceleração na {placa}; requer o driver nvidia)")
        vk = [p for p in pacotes if p not in (PACOTE, PACOTE_CUDA)]
        if vk:
            partes.append(f"{' + '.join(vk)} (aceleração na {placa})")
        passos.append(("install", "Instalar " + " e ".join(partes),
                       "xbps-install -Sy " + " ".join(pacotes)))
        if PACOTE not in pacotes and st["running"]:
            passos.append(("restart", f"Reiniciar o serviço ollama (para usar a {placa})",
                           f"sv restart {SERVICO}"))
    if not st["api"] and not (st["enabled"] and st["running"]):
        passos.append(("service", "Habilitar e iniciar o serviço ollama",
                       f"ln -s /etc/sv/{SERVICO} /var/service/  &&  sv start {SERVICO}"))
    if modelo not in st["models"] and f"{modelo}:latest" not in st["models"]:
        tam = model_info(modelo)[1]
        passos.append(("pull", f"Baixar o modelo {modelo}" + (f" (~{gb(tam)} GB)" if tam else ""),
                       f"ollama pull {modelo}"))
    passos.append(("test", "Testar o modelo", ""))
    passos.append(("save", "Usar a IA local no VoidBR AI (grava em ~/.config/voidbr-ai/config.toml)", ""))
    return passos


def pull(url, modelo, on_progress=None, timeout=7200):
    """Baixa o modelo pela API do Ollama; on_progress(status, fração|None)."""
    corpo = json.dumps({"model": modelo, "name": modelo, "stream": True}).encode()
    req = urllib.request.Request(f"{url}/api/pull", data=corpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for linha in r:
                try:
                    d = json.loads(linha)
                except ValueError:
                    continue
                if d.get("error"):
                    raise ProviderError(d["error"])
                total, feito = d.get("total"), d.get("completed")
                frac = (feito / total) if total and feito is not None else None
                if on_progress:
                    on_progress(d.get("status", ""), frac)
                if d.get("status") == "success":
                    return True
    except urllib.error.URLError as e:
        raise ProviderError(f"falha ao baixar: {e.reason}") from None
    except OSError as e:
        raise ProviderError(f"falha ao baixar: {e}") from None
    return False


def run_setup(agent, modelo, on_progress=None, hw=None):
    """Executa o plano. A confirmação é a tela que lista os passos (antes de chamar).

    Usa o Tool Registry do agent (as mesmas ações/helper de sempre)."""
    cfg = agent.cfg
    emit = agent.emit
    st = state(cfg)
    hw = hw or hardware()
    for tipo, desc, cmd in plan(st, modelo, hw):
        if tipo == "install":
            pacotes = missing_packages(st, hw)
            try:
                a = agent.registry.make_action("pkg.install", {"packages": pacotes}, reason="IA local")
            except ValueError as e:
                return False, str(e)
            r = agent.execute(a, _Rel(), confirmed=True)
            if not r.ok:
                return False, "cancelado" if r.cancelled else f"falha ao instalar {' '.join(pacotes)}"
        elif tipo == "restart":
            try:
                a = agent.registry.make_action("service.restart", {"name": SERVICO},
                                               reason="usar a placa de vídeo")
            except ValueError as e:
                return False, str(e)
            r = agent.execute(a, _Rel(), confirmed=True)
            if not r.ok:
                return False, "cancelado" if r.cancelled else "falha ao reiniciar o serviço ollama"
        elif tipo == "service":
            nome = "service.start" if svc.status(SERVICO)["enabled"] else "service.enable"
            try:
                a = agent.registry.make_action(nome, {"name": SERVICO}, reason="IA local")
            except ValueError as e:
                return False, str(e)
            r = agent.execute(a, _Rel(), confirmed=True)
            if not r.ok:
                return False, "cancelado" if r.cancelled else "falha ao iniciar o serviço ollama"
        elif tipo == "pull":
            emit("step", "api", "Esperando a API do Ollama…")
            for _ in range(60):
                if state(cfg)["api"]:
                    break
                time.sleep(1)
            else:
                emit("step", "api", "A API do Ollama não respondeu", "fail", st["url"])
                return False, "o serviço ollama não respondeu em 60 s (veja: sv status ollama)"
            emit("step", "api", "API do Ollama respondendo", "ok", st["url"])
            emit("step", "pull", desc + "…")
            try:
                pull(Ollama(cfg["ollama"]).url, modelo, on_progress)
            except ProviderError as e:
                emit("step", "pull", desc, "fail", str(e))
                return False, str(e)
            emit("step", "pull", desc, "ok", "concluído")
        elif tipo == "test":
            emit("step", "test", "Testando o modelo (a primeira carga pode demorar)…")
            prov = Ollama({**cfg["ollama"], "model": modelo})
            teste = {"type": "function", "function": {
                "name": "responder", "description": "responde ao usuário",
                "parameters": {"type": "object", "properties": {"texto": {"type": "string"}},
                               "required": ["texto"]}}}
            try:
                prov.chat_tools([{"role": "user", "content": "Chame a ferramenta responder com o texto ok."}],
                                [teste])
            except ProviderError as e:
                emit("step", "test", "O modelo não respondeu", "fail", str(e))
                return False, str(e)
            emit("step", "test", "O modelo respondeu", "ok", modelo)
        elif tipo == "save":
            config.save_user({"provider": "ollama", "ollama": {"model": modelo},
                              "gui": {"ai_setup": "feito"}})
            emit("step", "save", "IA local configurada", "ok", f"ollama: {modelo}")
    return True, f"IA local pronta: {modelo}"


class _Rel:
    """Relatório mínimo para o agent.execute registrar a execução."""

    def __init__(self):
        self.domain = "setup"
        self.question = "configurar IA local"
        self.findings = []
        self.executions = []
        self.session_path = ""

    def to_dict(self, with_state=False):
        return {}
