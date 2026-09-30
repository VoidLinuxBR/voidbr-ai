# -*- coding: utf-8 -*-
#
#   voidbr_ai/explain.py - "explique este comando / este erro"
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Análise de um comando ou de uma mensagem de erro colada pelo usuário.

Nada aqui é executado: o texto só é lido. As regras abaixo funcionam sem IA
(o que é perigoso, o que cada comando é, erros comuns do VoidBR); com IA a
explicação completa vem do modelo, que recebe também este resultado.
"""

import re
import shlex
import shutil

from .util import run

# (regex, nível, motivo) — nível: "perigoso" | "cuidado"
PERIGOS = [
    (r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)*(-[a-zA-Z]*\s+)*(/|/\*|~|~/|\$HOME|/home|/etc|/usr|/boot|/var)(\s|$)",
     "perigoso", "apaga recursivamente um diretório do sistema ou a sua pasta pessoal"),
    (r"--no-preserve-root", "perigoso", "desliga a proteção do rm contra apagar o /"),
    (r"\brm\s+(-\S+\s+)*-[a-zA-Z]*[rRf]", "cuidado",
     "apaga arquivos/pastas sem volta (não vai para a lixeira)"),
    (r"\bdd\b.*\bof=/dev/(sd|nvme|vd|hd|mmcblk)", "perigoso",
     "grava direto num disco: apaga o que estiver nele se o dispositivo estiver errado"),
    (r"\b(mkfs(\.\w+)?|wipefs|mkswap)\b", "perigoso", "formata/apaga um disco ou partição"),
    (r"\b(fdisk|sfdisk|gdisk|sgdisk|parted|cfdisk)\b", "cuidado", "altera a tabela de partições"),
    (r">\s*/dev/(sd|nvme|vd|hd|mmcblk)", "perigoso", "escreve direto num disco"),
    (r"\bshred\b", "perigoso", "destrói o conteúdo de arquivos/discos sem volta"),
    (r"\bchmod\s+(-R\s+)?[0-7]*777\s+/(\s|$)|\bchmod\s+-R\s+\S+\s+/(etc|usr|bin|boot)?(\s|$)",
     "perigoso", "muda permissões do sistema inteiro (pode deixar o sistema inseguro ou sem boot)"),
    (r"\bchown\s+-R\s+\S+\s+/(etc|usr|bin|boot|var)?(\s|$)", "perigoso",
     "muda o dono de arquivos do sistema inteiro"),
    (r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|fi|da)?sh\b", "cuidado",
     "baixa um script da internet e executa sem você ler antes"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "perigoso", "fork bomb: trava o sistema"),
    (r"/proc/sysrq-trigger", "perigoso", "comando direto ao kernel (pode reiniciar/desligar na hora)"),
    (r"\bkill\s+-9\s+1\b|\bkill\s+-9\s+-1\b", "perigoso", "mata o init ou todos os processos"),
    (r"\bxbps-remove\b.*\b(base-system|glibc|xbps|runit|linux)\b", "perigoso",
     "remove um pacote essencial do sistema"),
    (r"\bxbps-remove\b.*\s-[a-zA-Z]*F", "cuidado", "força a remoção, ignorando dependências"),
    (r"\bxbps-install\b.*\s-[a-zA-Z]*f", "cuidado", "força a reinstalação/downgrade"),
    (r"\bmv\s+\S+\s+/dev/null\b", "perigoso", "o arquivo some (não existe 'mover para o /dev/null')"),
    (r">\s*/etc/(passwd|shadow|fstab|sudoers)\b", "perigoso", "sobrescreve um arquivo vital do sistema"),
    (r"\b(reboot|poweroff|shutdown|halt)\b", "cuidado", "reinicia/desliga a máquina"),
    (r"\bsv\s+(down|stop|exit)\s+\S+", "cuidado", "para um serviço (se for o de rede/login, você perde o acesso)"),
    (r"\brm\s+.*(/var/service/|/etc/sv/)", "cuidado", "desabilita/apaga um serviço do runit"),
    (r"\bsudo\s+(-i|su\b|-s\b)", "cuidado", "abre um shell de root: tudo depois roda sem proteção"),
]

# (regex, título, explicação, sugestões) — erros comuns no VoidBR
ERROS = [
    (r"command not found|comando n[aã]o encontrado|: not found",
     "Comando não encontrado",
     "O programa não está instalado ou não está no PATH.",
     ["Procure o pacote: xbps-query -Rs <nome>  (ou vinstall -Ss <nome>)",
      "Descubra o pacote que tem o arquivo: xlocate <nome> (pacote xtools)"]),
    (r"permission denied|permiss[aã]o negada|operation not permitted|opera[cç][aã]o n[aã]o permitida",
     "Sem permissão",
     "O usuário atual não pode fazer isso: precisa de root ou de estar num grupo "
     "(ex: audio, video, bluetooth, socklog).",
     ["Seus grupos: id", "Com root: sudo <comando>", "Grupo: sudo gpasswd -a $USER <grupo> (vale no próximo login)"]),
    (r"no space left on device|sem espa[cç]o",
     "Disco cheio", "O sistema de arquivos ficou sem espaço (ou sem inodes).",
     ["voidbr-ai --diagnose storage", "df -h ; df -i"]),
    (r"could not resolve host|temporary failure in name resolution|name or service not known",
     "Falha de DNS", "Não conseguiu traduzir o nome do site para um IP (DNS ou sem internet).",
     ["voidbr-ai --diagnose network", "cat /etc/resolv.conf"]),
    (r"unresolvable shlib|broken, unresolvable|unresolved dependenc",
     "Dependências do xbps quebradas",
     "O xbps não achou bibliotecas/dependências: costuma ser atualização parcial ou repositório "
     "desatualizado.",
     ["Atualize o sistema inteiro: sudo xbps-install -Su (ou vinstall -Syu)",
      "Confira o banco de pacotes: sudo xbps-pkgdb -a"]),
    (r"error while loading shared libraries",
     "Biblioteca ausente", "O programa precisa de uma biblioteca que não está instalada ou mudou de versão.",
     ["Atualize: sudo xbps-install -Su", "Confira: sudo xbps-pkgdb -a",
      "Pacote que tem a lib: xlocate <arquivo.so> (pacote xtools)"]),
    (r"unable to open supervise/ok|fail: \S+: unable to change to service directory|warning: \S+: unable to open",
     "Serviço não habilitado no runit",
     "O sv não achou o serviço em /var/service: ele não está habilitado (ou o runsvdir não o assumiu ainda).",
     ["Habilite: sudo ln -s /etc/sv/<serviço> /var/service/", "Com vservice: sudo vservice enable <serviço>"]),
    (r"failed to connect to (the )?bus|dbus.*(not running|no such file)|DBUS_SESSION_BUS_ADDRESS",
     "Sem D-Bus", "O programa precisa do D-Bus (de sistema ou da sessão) e ele não está rodando.",
     ["Sistema: sudo ln -s /etc/sv/dbus /var/service/",
      "Sessão: inicie o compositor com dbus-run-session (ou use um display manager)"]),
    (r"XDG_RUNTIME_DIR( is)? (not set|invalid)",
     "XDG_RUNTIME_DIR ausente", "Sem gerenciador de sessão (elogind/seatd/turnstile) essa variável não é criada.",
     ["Instale e habilite o elogind (ou seatd + grupo _seatd)", "voidbr-ai --diagnose graphics"]),
    (r"(cannot|could not|failed to) (open|connect to) (the )?(display|wayland)",
     "Sem acesso à tela", "O programa não achou a sessão gráfica (DISPLAY/WAYLAND_DISPLAY) ou está fora dela.",
     ["Rode de dentro da sessão gráfica", "voidbr-ai --diagnose graphics"]),
    (r"segmentation fault|falha de segmenta",
     "Programa travou (segfault)", "O programa acessou memória inválida: bug, biblioteca incompatível ou hardware.",
     ["Atualize o sistema e o programa", "Veja o dmesg logo depois: dmesg | tail"]),
    (r"out of memory|oom-kill|killed process",
     "Falta de memória", "O kernel matou um processo por falta de RAM.",
     ["voidbr-ai --diagnose system", "Considere zram/swap"]),
    (r"signature verification failed|not signed|repository .* (unsigned|key)",
     "Assinatura do repositório", "O xbps não confia na chave do repositório (primeira vez ou chave mudou).",
     ["Confirme a importação da chave quando o xbps perguntar", "Confira os repositórios: xbps-query -L"]),
    (r"failed to fetch|connection (timed out|refused)|could not connect",
     "Falha de conexão", "Não conseguiu baixar/conectar: internet, espelho do repositório fora ou firewall.",
     ["voidbr-ai --diagnose network", "Troque o espelho: xmirror (pacote xmirror)"]),
]

_SEPARADORES = re.compile(r"\|\||&&|;|\||\n")


def parece_comando(texto):
    t = texto.strip()
    if t.startswith(("$ ", "# ", "sudo ")):
        return True
    prim = t.split()[0] if t.split() else ""
    return bool(prim) and "\n" not in t.strip() and len(t) < 400 and shutil.which(prim) is not None


def parece_erro(texto):
    t = texto.lower()
    return any(re.search(p, t, re.I) for p, *_ in ERROS) or \
        bool(re.search(r"\b(error|erro|failed|falhou|fatal|warning|aviso|traceback)\b", t))


def comandos(texto):
    """Os programas usados no texto (o 1º nome de cada parte), sem sudo/env."""
    nomes = []
    for parte in _SEPARADORES.split(texto):
        parte = parte.strip().lstrip("$#").strip()
        if not parte:
            continue
        try:
            tokens = shlex.split(parte)
        except ValueError:
            tokens = parte.split()
        while tokens and (tokens[0] in ("sudo", "doas", "env", "nohup", "time", "exec") or
                          re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]) or
                          tokens[0].startswith("-")):
            tokens.pop(0)
        if tokens and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", tokens[0]):
            if tokens[0] not in nomes:
                nomes.append(tokens[0])
    return nomes[:8]


def riscos(texto):
    achados = []
    for pat, nivel, motivo in PERIGOS:
        if re.search(pat, texto):
            achados.append({"nivel": nivel, "motivo": motivo})
    if re.search(r"(^|\s|;|&&|\|)sudo\b", texto) and not achados:
        achados.append({"nivel": "cuidado", "motivo": "roda como root (sudo): confira o que faz antes"})
    return achados


def _whatis(nome):
    r = run(["whatis", nome], timeout=5)
    if r["rc"] == 0 and r["out"].strip():
        return r["out"].splitlines()[0].split(" - ", 1)[-1].strip()
    return ""


def _pacote_de(nome):
    caminho = shutil.which(nome)
    if not caminho:
        return caminho, ""
    r = run(["xbps-query", "-o", caminho], timeout=10)
    pac = r["out"].split(":", 1)[0].strip() if r["rc"] == 0 and r["out"] else ""
    return caminho, pac


def analisar(texto):
    """Resultado estruturado (sem IA): tipo, riscos, comandos, erros reconhecidos."""
    texto = (texto or "").strip()
    tipo = "erro" if parece_erro(texto) and not parece_comando(texto) else "comando"
    cmds = []
    for n in comandos(texto) if tipo == "comando" else []:
        caminho, pac = _pacote_de(n)
        cmds.append({"nome": n, "descricao": _whatis(n), "caminho": caminho or "", "pacote": pac,
                     "instalado": bool(caminho)})
    erros = [{"titulo": t, "explicacao": e, "sugestoes": s}
             for p, t, e, s in ERROS if re.search(p, texto, re.I)]
    rs = riscos(texto) if tipo == "comando" else []
    nivel = "perigoso" if any(r["nivel"] == "perigoso" for r in rs) else \
        "cuidado" if rs else "sem riscos conhecidos"
    return {"tipo": tipo, "nivel": nivel, "riscos": rs, "comandos": cmds, "erros": erros}
