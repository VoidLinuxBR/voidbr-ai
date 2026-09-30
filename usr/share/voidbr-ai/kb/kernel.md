## Kernel: séries e pacotes
fonte: https://docs.voidlinux.org/config/kernel.html
- Séries de kernel são pacotes `linux<x>.<y>` (ex.: `linux6.12`).
- Listar séries disponíveis: `xbps-query --regex -Rs '^linux[0-9.]+-[0-9._]+' | sort -Vrk2`
- O metapacote `linux` (instalado por padrão) depende da série padrão.
- Para usar outra série com módulos DKMS: instalar `linux<x>.<y>-headers` e reconfigurar o `linux<x>.<y>`.
- Trocar para `linux-lts` ou `linux-mainline`: instalar o metapacote (e `-headers` se preciso), pôr `linux` e `linux-headers` em `ignorepkg` e removê-los.
- Remover a série padrão: instalar `linux-base` (ou marcá-lo como manual) antes de remover os pacotes do kernel padrão.

## Kernel: remover kernels antigos (vkpurge)
fonte: https://docs.voidlinux.org/config/kernel.html
- Kernels antigos ficam instalados após atualização; `/boot` cheio pode gerar initramfs incompleto e kernel panic.
- `vkpurge` vem pré-instalado (fornecido pelo pacote `base-files`), roda os hooks de remoção e remove kernels, não pacotes.
- Uso (man vkpurge(8)): `vkpurge list` lista removíveis; `vkpurge rm all` remove todos os removíveis; `vkpurge rm <versão>` remove versões específicas.
- Só lista/remove versões que não estão em uso (bootadas) e não pertencem a pacote instalado.

## Kernel: initramfs e hooks
fonte: https://docs.voidlinux.org/config/kernel.html
- Gerador de initramfs padrão: dracut; alternativa: mkinitcpio, via grupo de alternativas `initramfs`.
- Ver alternativas: `xbps-alternatives -l -g initramfs`; trocar: `xbps-alternatives -s mkinitcpio`.
- Hooks do kernel em `/etc/kernel.d/{pre-install,post-install,pre-remove,post-remove}` (atualizam menus de bootloader como grub).
- Regerar initramfs (roda os install hooks): `xbps-reconfigure --force linux<x>.<y>` (forma curta `xbps-reconfigure -f linux<x>.<y>`).
- Os remove hooks são executados pelo `vkpurge`.
- Logs de build DKMS: `/var/lib/dkms/`.

## Kernel: cmdline e módulos
fonte: https://docs.voidlinux.org/config/kernel.html
- Cmdline atual: `/proc/cmdline`.
- GRUB: editar `GRUB_CMDLINE_LINUX_DEFAULT` em `/etc/default/grub` e rodar `update-grub`.
- dracut `kernel_cmdline` só é passado ao kernel em executável UEFI; em initramfs comum vai para `/etc/cmdline.d` dentro da imagem.
- Carregar módulo no boot: arquivo `.conf` em `/etc/modules-load.d/` (ex.: `virtio-net`).
- Blacklist após initramfs: `/etc/modprobe.d/<x>.conf` com `blacklist <módulo>`.
- Blacklist no initramfs dracut: `/etc/dracut.conf.d/<x>.conf` com `omit_drivers+=" <módulo> "`, depois regerar o initramfs.
