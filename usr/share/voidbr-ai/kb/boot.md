## Boot: instalar o GRUB
fonte: https://docs.voidlinux.org/installation/guides/chroot.html
- BIOS: instalar o pacote `grub` e rodar `grub-install /dev/sdX` (disco, não partição).
- UEFI x86_64: `xbps-install -S grub-x86_64-efi` e `grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id="Void"`.
- Outros UEFI: `grub-i386-efi` (`--target=i386-efi`) ou `grub-arm64-efi` (`--target=arm64-efi`).
- Se variáveis EFI não estiverem disponíveis: `mount -t efivarfs none /sys/firmware/efi/efivars`; persistindo, usar `--no-nvram`.
- Firmware UEFI não conforme ou mídia removível: adicionar `--removable`, ou copiar `/boot/efi/EFI/Void/grubx64.efi` para `/boot/efi/EFI/boot/bootx64.efi`.
- A localização do executável do GRUB pode ser vista com `efibootmgr`.
- Finalizar: `xbps-reconfigure -fa` (dracut gera initramfs e o GRUB gera configuração).

## Boot: atualizar configuração do GRUB
fonte: https://docs.voidlinux.org/config/kernel.html
- Parâmetros do kernel: editar `GRUB_CMDLINE_LINUX_DEFAULT` em `/etc/default/grub` e rodar `update-grub`.
- Os hooks em `/etc/kernel.d/` atualizam o menu do grub ao instalar/remover kernels.

## Boot: partições
fonte: https://docs.voidlinux.org/installation/live-images/partitions.html
- UEFI: recomendada tabela GPT e partição `EFI System` com `vfat` montada em `/boot/efi` (200MB a 1GB).
- BIOS com GPT: partição de 1MB tipo `BIOS boot`, sem sistema de arquivos.
- `/boot` separado é opcional; Void não remove kernels antigos por padrão, planejar o tamanho.
