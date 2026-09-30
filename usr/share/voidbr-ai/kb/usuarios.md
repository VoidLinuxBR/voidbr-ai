## Usuários e grupos
fonte: https://docs.voidlinux.org/config/users-and-groups.html
- Usuários: `useradd`, `userdel`, `usermod`; senhas: `passwd`.
- Grupos: `groupadd`, `groupdel`, `groupmod`; listar grupos de um usuário: `groups`.
- Trocar shell padrão: `chsh -s <shell> <usuário>` (shell listado em `/etc/shells` ou `chsh -l`).
- Grupos relevantes: `wheel` (administração), `audio`, `video`, `input`, `storage`, `network` (NetworkManager/connman), `kvm`, `plugdev`, `dialout` (serial), `lp` (impressoras), `scanner`.
- Outros grupos citados em outras páginas: `socklog` (ler logs), `bluetooth`, `_seatd` (seatd).

## sudo e doas
fonte: https://docs.voidlinux.org/config/users-and-groups.html
- `sudo` vem instalado por padrão; editar o sudoers com `visudo` como root.
- Superusuário: descomentar `%wheel ALL=(ALL) ALL` e adicionar o usuário ao grupo `wheel`.
- Para usar `doas` no lugar do `sudo`, é preciso `ignorepkg=sudo` num arquivo xbps.d antes de remover o `sudo` (dependência do `base-system`) — ver https://docs.voidlinux.org/xbps/advanced-usage.html

## Locales
fonte: https://docs.voidlinux.org/config/locales.html
- glibc suporta locale do sistema; musl não.
- Listar locales ativos: `locale -a`.
- Ativar: descomentar/adicionar em `/etc/default/libc-locales` e rodar `xbps-reconfigure -f glibc-locales`.
- Idioma do sistema: `LANG=xxxx` em `/etc/locale.conf`.
- Traduções de alguns programas ficam em pacotes separados (ex.: `libreoffice-i18n-*`).
