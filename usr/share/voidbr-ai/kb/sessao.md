## Sessão: D-Bus
fonte: https://docs.voidlinux.org/config/session-management.html
- Barramento de sistema: habilitar o serviço `dbus` (`ln -s /etc/sv/dbus /var/service/`); pode exigir reboot.
- Barramento de sessão: iniciar o programa (WM/compositor/shell) com `dbus-run-session`; DEs lançados por display manager adequado costumam iniciar a sessão D-Bus sozinhos.
- Sessão D-Bus ativa => variável `DBUS_SESSION_BUS_ADDRESS` definida.
- Pode ser preciso exportar `DISPLAY`/`WAYLAND_DISPLAY` ao ambiente de ativação com `dbus-update-activation-environment`.

## Sessão: elogind
fonte: https://docs.voidlinux.org/config/session-management.html
- elogind gerencia logins e energia (versão standalone do systemd-logind); atende a maioria dos DEs e compositores Wayland.
- Instalar `elogind` e garantir o D-Bus de sistema habilitado; pode ser preciso relogar.
- Se houver problemas, habilitar o serviço `elogind` (esperar ativação via D-Bus pode causar problemas).
- Conflita com `acpid` no tratamento de eventos ACPI (ver energia).

## Sessão: seatd
fonte: https://docs.voidlinux.org/config/session-management.html
- seatd é um gerenciador de seat mínimo, alternativa ao elogind principalmente para compositores wlroots.
- Instalar `seatd` e habilitar o serviço; usuários não-root precisam estar no grupo `_seatd`.
- Diferente do elogind, só gerencia seats.

## Sessão: turnstile
fonte: https://docs.voidlinux.org/config/session-management.html
- Gerenciador de sessão alternativo, com ou sem elogind; habilitar o serviço `turnstiled` e relogar.
- Com elogind: definir `manage_rundir` como `no` em `/etc/turnstile/turnstiled.conf`.
- Sem elogind: considerar `seatd` (seat) e `acpid` (energia).
- Pode gerenciar serviços de usuário, inclusive o D-Bus de sessão, dispensando `dbus-run-session`.

## Sessão: XDG_RUNTIME_DIR
fonte: https://docs.voidlinux.org/config/session-management.html
- elogind ou turnstile configuram `XDG_RUNTIME_DIR` automaticamente.
- Manualmente: criar diretório do usuário com permissão `700`; local padrão sugerido `/run/user/$(id -u)`.

## Wayland
fonte: https://docs.voidlinux.org/config/graphical-session/wayland.html
- Compositores Wayland exigem gerenciador de seat: elogind ou seatd.
- A maioria dos compositores precisa de driver com GBM, fornecido pelo `mesa-dri`.
- A biblioteca Wayland usa `XDG_RUNTIME_DIR` para o socket; alguns apps usam `XDG_SESSION_TYPE=wayland`.
- Qt: pacotes `qt5-wayland`/`qt6-wayland` e `QT_QPA_PLATFORM=wayland`; SDL: `SDL_VIDEODRIVER=wayland`; EFL: `ELM_DISPLAY=wl`.
- XWayland: pacote `xorg-server-xwayland`.
- Alguns compositores não dependem de fontes; instalar um pacote de fontes se apps falharem.

## Portais XDG
fonte: https://docs.voidlinux.org/config/graphical-session/portals.html
- Exigem D-Bus de sessão do usuário. Instalar `xdg-desktop-portal` e um ou mais backends.
- Backends: `xdg-desktop-portal-gtk` (bom padrão), `-gnome`, `-kde`, `-lxqt`, `-wlr` (só screenshot/screencast em wlroots).
- Config padrão: `/usr/share/xdg-desktop-portal/portals.conf`; sobrescrever com `$XDG_CURRENT_DESKTOP-portals.conf` ou `portals.conf`.
