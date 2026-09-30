## Data e hora: fuso horário e relógio de hardware
fonte: https://docs.voidlinux.org/config/date-time.html
- Ver/alterar data e hora: `date`.
- Fuso do sistema: `ln -sf /usr/share/zoneinfo/<fuso> /etc/localtime`.
- Se `TIMEZONE` estiver em `/etc/rc.conf`, remover/comentar (sobrescreve o link no reboot).
- Fuso por usuário: `export TZ=<fuso>` no profile do shell.
- Relógio de hardware padrão em UTC; dual boot com Windows: `export HARDWARECLOCK=localtime` em `/etc/rc.conf` (ou configurar o Windows para UTC).

## Data e hora: NTP
fonte: https://docs.voidlinux.org/config/date-time.html
- Daemons disponíveis: NTP, OpenNTPD, Chrony e ntpd-rs.
- Habilitar o serviço próprio do daemon ou o serviço `ntpd` gerenciado por `xbps-alternatives`.
- `ntp` fornece o serviço `isc-ntpd`; `openntpd` fornece o serviço `openntpd`; `chrony` fornece o serviço `chronyd`; `ntpd-rs` fornece o serviço `ntpd-rs`.
- Data/hora errada pode causar erro "Operation not permitted" ao sincronizar repositórios do xbps (https://docs.voidlinux.org/xbps/troubleshooting/common-issues.html).
