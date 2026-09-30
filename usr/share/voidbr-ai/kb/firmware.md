## Firmware
fonte: https://docs.voidlinux.org/config/firmware.html
- Vários pacotes de firmware nos repositórios; alguns só no repositório nonfree.
- Pacotes `linuxX.Y` e `base-system` instalam firmwares por padrão; para remover os não usados, pôr em `ignorepkg` e remover.

## Microcódigo
fonte: https://docs.voidlinux.org/config/firmware.html
- Intel: pacote `intel-ucode`, no repositório nonfree (instalar `void-repo-nonfree`); depois regerar o initramfs (`xbps-reconfigure -f linux<x>.<y>`); atualizações seguintes entram no initramfs automaticamente.
- AMD: pacote `linux-firmware-amd` (CPU e GPU), carregado automaticamente.
- Verificação: campo `microcode` em `/proc/cpuinfo`.

## Firmware de GPU
fonte: https://docs.voidlinux.org/config/graphical-session/graphics-drivers/index.html
- AMD requer `linux-firmware-amd`; Intel requer `linux-firmware-intel`; ambos vêm como dependência de `linux`/`linux-lts`, mas podem precisar ser instalados à mão com kernel `linuxX.Y` específico.
