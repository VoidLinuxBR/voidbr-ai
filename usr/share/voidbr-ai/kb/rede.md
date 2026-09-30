## Rede: visão geral e dhcpcd
fonte: https://docs.voidlinux.org/config/network/index.html
- A instalação padrão vem com o serviço `dhcpcd` habilitado.
- dhcpcd em todas as interfaces: habilitar o serviço `dhcpcd`.
- dhcpcd em uma interface só: `cp -R /etc/sv/dhcpcd-eth0 /etc/sv/dhcpcd-enp3s0`, ajustar o symlink `supervise` para `/run/runit/supervise.dhcpcd-enp3s0`, `sed -i 's/eth0/enp3s0/' /etc/sv/dhcpcd-enp3s0/run`, `ln -s /etc/sv/dhcpcd-enp3s0 /var/service/`.
- Nomes antigos de interface (eth0, wlan0): adicionar `net.ifnames=0` à cmdline do kernel.
- IP estático no boot: comandos `ip` em `/etc/rc.local` (ex.: `ip addr add 192.168.1.2/24 brd + dev eth0`, `ip route add default via 192.168.1.1`).
- Wi-Fi: verificar bloqueios com `rfkill` antes; opções: wpa_supplicant, iwd, NetworkManager, ConnMan.

## Rede: wpa_supplicant
fonte: https://docs.voidlinux.org/config/network/wpa_supplicant.html
- Pacote `wpa_supplicant` vem no sistema base; é preciso habilitar o serviço `wpa_supplicant`.
- WPA-PSK: `wpa_passphrase <SSID> <senha> >> /etc/wpa_supplicant/wpa_supplicant.conf`
- Opções do serviço em `/etc/sv/wpa_supplicant/conf`: `OPTS`, `CONF_FILE` (padrão `/etc/wpa_supplicant/wpa_supplicant.conf`), `WPA_INTERFACE`, `DRIVER`.
- Sem `conf`, procura `/etc/wpa_supplicant/wpa_supplicant-<interface>.conf` e `wpa_supplicant.conf`.
- `wpa_cli` deve ser usado com `-i <interface>` (ex.: `wpa_cli -i wlp2s0`).

## Rede: iwd
fonte: https://docs.voidlinux.org/config/network/iwd.html
- Instalar `iwd` e habilitar os serviços `dbus` e `iwd`.
- Cliente: `iwctl` (interativo ou com argumentos; `iwctl help`); por padrão só root e grupo `wheel` podem usar.
- Config do daemon: `/etc/iwd/main.conf`; redes conhecidas em `/var/lib/iwd` (ex.: `<ssid>.psk`).
- Conflito de renomeação com udev: `UseDefaultInterface=true` na seção `[General]` de `/etc/iwd/main.conf`, ou `net.ifnames=0`.

## Rede: NetworkManager
fonte: https://docs.voidlinux.org/config/network/networkmanager.html
- Instalar o pacote `NetworkManager`.
- Antes de habilitar, desabilitar outros gerenciadores de rede (`dhcpcd`, `wpa_supplicant`, `wicd`): eles interferem no NetworkManager.
- O serviço `dbus` precisa estar habilitado e rodando; sem ele o NetworkManager não inicia.
- Depois, habilitar o serviço `NetworkManager`.
- Usuários do NetworkManager devem pertencer ao grupo `network`.
- Ferramentas: `nmcli` e `nmtui`; front-ends: `nm-applet` (`network-manager-applet`), `nm-tray`, `plasma-nm`.
