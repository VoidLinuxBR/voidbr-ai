# -*- coding: utf-8 -*-
#
#   voidbr_ai/tools/boot.py - boot: kernels, initramfs e bootloader
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Licença: MIT
#
"""Boot no VoidBR (Void Handbook, kernel e GRUB):

- cada pacote linuxX.Y instala /boot/vmlinuz-<versão> e os módulos em
  /usr/lib/modules/<versão>; o dracut gera /boot/initramfs-<versão>.img;
- regerar o initramfs: xbps-reconfigure -f linuxX.Y (roda os hooks do kernel,
  que também atualizam o menu do GRUB);
- GRUB: update-grub; Limine: o update-limine do VoidBR (se existir).
"""

import os
import re

from ..util import read_file, run, which
from .privileged import run_helper
from .registry import P, Tool

LIMINE_CONFS = ["/boot/limine.conf", "/boot/limine/limine.conf", "/boot/efi/limine/limine.conf",
                "/boot/EFI/limine/limine.conf", "/boot/efi/EFI/limine/limine.conf",
                "/efi/limine/limine.conf"]
UPDATE_LIMINE = ["/usr/local/bin/update-limine", "/usr/bin/update-limine", "/usr/bin/limine-update"]
RE_KPKG = r"linux\d+\.\d+"


def _kernels():
    """[{pkg: linux6.12, version: 6.12.44_1}] dos kernels instalados pelo xbps."""
    r = run(["xbps-query", "-l"], timeout=20)
    ks = []
    for linha in r["out"].splitlines():
        p = linha.split()
        if len(p) >= 2:
            m = re.fullmatch(rf"({RE_KPKG})-(\d[^\s]*)", p[1])
            if m:
                ks.append({"pkg": m.group(1), "version": m.group(2)})
    return ks


def _versao_ordem(v):
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[._-]", v)]


def _livre_mb(caminho):
    try:
        st = os.statvfs(caminho)
        return round(st.f_bavail * st.f_frsize / 1048576)
    except OSError:
        return None


def t_status():
    em_uso = os.uname().release
    d = {"firmware": "UEFI" if os.path.isdir("/sys/firmware/efi") else "BIOS",
         "running_kernel": em_uso,
         "running_modules_present": os.path.isdir(f"/usr/lib/modules/{em_uso}"),
         "cmdline": (read_file("/proc/cmdline") or "").strip()[:300],
         "initramfs_generator": [g for g in ("dracut", "mkinitcpio") if which(g)],
         "kernels": [], "grub": None, "limine": None,
         "boot_free_mb": _livre_mb("/boot"),
         "efi_free_mb": _livre_mb("/boot/efi") if os.path.ismount("/boot/efi") else None}
    for k in _kernels():
        v = k["version"]
        k.update(vmlinuz=os.path.exists(f"/boot/vmlinuz-{v}") or os.path.exists(f"/boot/vmlinux-{v}"),
                 initramfs=os.path.exists(f"/boot/initramfs-{v}.img"),
                 modules=os.path.isdir(f"/usr/lib/modules/{v}"), running=v == em_uso)
        d["kernels"].append(k)
    d["kernels"].sort(key=lambda k: _versao_ordem(k["version"]))
    if os.path.exists("/boot/grub/grub.cfg"):
        cfg = read_file("/boot/grub/grub.cfg")
        d["grub"] = {"config": "/boot/grub/grub.cfg", "readable": cfg is not None,
                     "update_grub": bool(which("update-grub")),
                     "kernels_in_menu": [k["version"] for k in d["kernels"]
                                         if cfg and k["version"] in cfg] if cfg else None}
    conf = next((c for c in LIMINE_CONFS if os.path.exists(c)), None)
    if conf:
        texto = read_file(conf)
        d["limine"] = {"config": conf, "readable": texto is not None,
                       "update_limine": next((c for c in UPDATE_LIMINE if os.access(c, os.X_OK)), ""),
                       "kernels_in_menu": [k["version"] for k in d["kernels"]
                                           if texto and k["version"] in texto] if texto else None}
    return d


def c_status(state=None, cfg=None):
    d = t_status()
    bl = [n for n in ("grub", "limine") if d[n]]
    d["summary"] = f"{d['firmware']}, {' + '.join(bl) or 'bootloader ?'}, kernel {d['running_kernel']}"
    faltando = [k for k in d["kernels"] if k["modules"] and not k["initramfs"]]
    d["status"] = "fail" if faltando or not d["running_modules_present"] else "ok"
    return d


def a_reconfigure(kernel, on_line=None):
    return run_helper("kernel-reconfigure", kernel, timeout=1800, on_line=on_line)


def a_grub_update(on_line=None):
    return run_helper("grub-update", timeout=600, on_line=on_line)


def a_limine_update(on_line=None):
    return run_helper("limine-update", timeout=600, on_line=on_line)


def _v_reconfigure(kernel):
    k = next((x for x in t_status()["kernels"] if x["pkg"] == kernel), None)
    ok = bool(k and k["initramfs"])
    return ok, (f"initramfs de {kernel} presente" if ok else f"{kernel} continua sem initramfs")


def _v_menu(nome):
    def f():
        s = t_status()
        b = s[nome]
        if not b or b["kernels_in_menu"] is None:
            return None, "não foi possível ler o menu (sem permissão)"
        faltam = [k["version"] for k in s["kernels"] if k["version"] not in b["kernels_in_menu"]]
        return not faltam, ("todos os kernels estão no menu" if not faltam
                            else "fora do menu: " + ", ".join(faltam))
    return f


def _c_kernel(args):
    if not os.path.exists(f"/usr/share/doc/{args['kernel']}") and \
            run(["xbps-query", args["kernel"]], timeout=10)["rc"] != 0:
        return f"{args['kernel']} não está instalado"
    return None


STEPS = [("boot.c_status", "Verificando boot, kernels e initramfs", "boot")]
KEYWORDS = ["boot", "inicializacao", "grub", "limine", "initramfs", "dracut", "bootloader",
            "kernel panic", "nao inicia", "nao liga", "nao da boot", "efi", "uefi", "vmlinuz",
            "menu de boot"]


def _achado(code, sev, title, detail="", sug=None):
    return {"code": code, "severity": sev, "title": title, "detail": detail, "step": "boot",
            "confirmed": True, "suggestions": sug or []}


def analyze(state, reg):
    achados, acoes = [], []
    d = state.get("boot", {})
    if not d:
        return achados, acoes

    def acao(tool, args, reason, fixes):
        try:
            acoes.append(reg.make_action(tool, args, reason=reason, fixes=fixes))
        except ValueError:
            pass

    if not d["kernels"]:
        # kernel que não veio do xbps (container, VM com kernel externo): nada a checar aqui
        achados.append(_achado("boot_external", "info", "Nenhum kernel do xbps instalado",
                               f"O kernel em uso ({d['running_kernel']}) não veio de um pacote linuxX.Y."))
        return achados, acoes
    if not d["initramfs_generator"]:
        achados.append(_achado("no_initramfs_gen", "erro", "Nenhum gerador de initramfs instalado",
                               "O Void usa o dracut por padrão; sem ele um kernel novo não boota."))
        acao("pkg.install", {"packages": ["dracut"]}, "gera o initramfs", ["no_initramfs_gen"])
    for k in d["kernels"]:
        if k["modules"] and not k["initramfs"]:
            achados.append(_achado(f"no_initramfs:{k['pkg']}", "erro",
                                   f"Kernel {k['version']} sem initramfs",
                                   f"Falta /boot/initramfs-{k['version']}.img: esse kernel não vai bootar."))
            acao("kernel.reconfigure", {"kernel": k["pkg"]}, "refaz o initramfs",
                 [f"no_initramfs:{k['pkg']}"])
        if k["modules"] and not k["vmlinuz"]:
            achados.append(_achado(f"no_vmlinuz:{k['pkg']}", "erro",
                                   f"Kernel {k['version']} sem /boot/vmlinuz",
                                   "O /boot pode não estar montado ou o pacote está incompleto.",
                                   [f"sudo xbps-install -f {k['pkg']}"]))
    if not d["running_modules_present"]:
        achados.append(_achado("running_removed", "aviso", "O kernel em uso foi atualizado/removido",
                               f"Não existe /usr/lib/modules/{d['running_kernel']}: módulos novos "
                               "(USB, som, rede) podem falhar até reiniciar.", ["Reinicie o computador"]))
    elif d["kernels"]:
        novo = d["kernels"][-1]
        if novo["version"] != d["running_kernel"] and \
                _versao_ordem(novo["version"]) > _versao_ordem(d["running_kernel"]):
            achados.append(_achado("newer_kernel", "info", f"Há um kernel mais novo instalado ({novo['version']})",
                                   f"Em uso: {d['running_kernel']}. Reinicie para usar o novo."))
    for nome, rot in (("grub", "GRUB"), ("limine", "Limine")):
        b = d.get(nome)
        if not b or b["kernels_in_menu"] is None:
            continue
        fora = [k["version"] for k in d["kernels"] if k["version"] not in b["kernels_in_menu"]]
        if fora:
            achados.append(_achado(f"menu_{nome}", "aviso", f"Kernel fora do menu do {rot}",
                                   f"Não aparecem em {b['config']}: {', '.join(fora)}."))
            if nome == "grub" and b["update_grub"]:
                acao("boot.grub_update", {}, "atualiza o menu", ["menu_grub"])
            if nome == "limine" and b["update_limine"]:
                acao("boot.limine_update", {}, "atualiza o menu", ["menu_limine"])
    for rot, livre in (("/boot", d["boot_free_mb"]), ("/boot/efi", d["efi_free_mb"])):
        if livre is not None and livre < 100:
            achados.append(_achado(f"boot_full:{rot}", "aviso", f"{rot} com pouco espaço ({livre} MB)",
                                   "Kernels e initramfs novos podem não caber.",
                                   ["Remova kernels antigos (vkpurge)"]))
            acao("kernel.purge", {}, "libera espaço no /boot", [f"boot_full:{rot}"])
    if not any(a["severity"] in ("erro", "aviso") for a in achados):
        bl = " + ".join(n.upper() if n == "grub" else n.capitalize() for n in ("grub", "limine") if d[n])
        achados.insert(0, _achado("boot_ok", "ok", "Boot sem problemas",
                                  f"{d['firmware']}, {bl or 'bootloader não identificado'}; "
                                  f"{len(d['kernels'])} kernel(s), em uso {d['running_kernel']}."))
    return achados, acoes


def register(reg):
    reg.register(Tool("boot.status", "Verificando o boot",
                      "Boot: UEFI/BIOS, GRUB/Limine e se os kernels estão no menu, kernels instalados "
                      "(vmlinuz, initramfs, módulos), kernel em uso, gerador de initramfs, espaço "
                      "livre no /boot e /boot/efi, linha de comando do kernel.",
                      t_status, domain="boot"))
    reg.register(Tool("kernel.reconfigure", "Refazer o initramfs",
                      "Regera o initramfs de um kernel e roda os hooks (xbps-reconfigure -f linuxX.Y).",
                      a_reconfigure, kind="action", snapshot=True, domain="boot",
                      params={"kernel": P("string", "pacote do kernel (ex: linux6.12)", pattern=RE_KPKG)},
                      required=["kernel"], check=_c_kernel,
                      title="Refazer o initramfs do {kernel}",
                      preview=lambda kernel: f"xbps-reconfigure -f {kernel}", verify=_v_reconfigure))
    reg.register(Tool("boot.grub_update", "Atualizar o menu do GRUB",
                      "Regera o menu do GRUB (update-grub).", a_grub_update, kind="action",
                      snapshot=True, domain="boot", title="Atualizar o menu do GRUB",
                      preview=lambda: "update-grub", verify=_v_menu("grub")))
    reg.register(Tool("boot.limine_update", "Atualizar o menu do Limine",
                      "Regera o menu do Limine (update-limine do VoidBR).", a_limine_update,
                      kind="action", snapshot=True, domain="boot", title="Atualizar o menu do Limine",
                      preview=lambda: "update-limine", verify=_v_menu("limine")))


def register_checks(reg):
    reg.register(Tool("boot.c_status", STEPS[0][1], STEPS[0][1], c_status,
                      domain="boot", llm=False, internal=True))
