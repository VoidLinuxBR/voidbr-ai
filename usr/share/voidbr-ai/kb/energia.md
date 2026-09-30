## Energia: acpid
fonte: https://docs.voidlinux.org/config/power-management.html
- Serviço `acpid` instalado; habilitado por padrão se instalado pela imagem live com fonte local.
- Eventos ACPI tratados por `/etc/acpi/handler.sh`, que usa `zzz` para suspender (suspend-to-RAM).

## Energia: elogind
fonte: https://docs.voidlinux.org/config/power-management.html
- Serviço `elogind` (pacote `elogind`) trata tampa e teclas power/suspend/hibernate por padrão.
- Conflita com `acpid` habilitado: desabilitar `acpid` ao habilitar `elogind`, ou configurar opções `Handle*` como `ignore` em logind.conf.
- `loginctl poweroff` / `loginctl reboot` sem root exigem `polkit` instalado.

## Energia: tlp
fonte: https://docs.voidlinux.org/config/power-management.html
- Para bateria de notebook: instalar `tlp` e habilitar o serviço `tlp`.
