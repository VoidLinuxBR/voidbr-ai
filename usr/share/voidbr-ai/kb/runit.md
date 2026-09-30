## Serviços runit: diretórios e conceitos
fonte: https://docs.voidlinux.org/config/services/index.html
- Void usa o runit para supervisionar serviços e daemons.
- Cada serviço tem um diretório de serviço; só é obrigatório um executável `run` (processo em primeiro plano).
- Opcionais: `check` (disponível se sair com 0), `finish`, arquivo `conf` (variáveis usadas no `run`) e diretório `log`.
- O diretório `supervise` é criado automaticamente na primeira execução.
- Serviços fornecidos pelos pacotes ficam em `/etc/sv/`.
- Um runsvdir é um diretório em `/etc/runit/runsvdir` com symlinks para serviços habilitados; o runsvdir atual é acessível via symlink `/var/service`.
- O `runit-void` traz dois runsvdirs: `single` (só sulogin, resgate) e `default` (padrão).
- Para bootar outro runsvdir, colocar o nome dele na linha de comando do kernel (ex.: `single`).
- Para customizar, muitos serviços aceitam um `conf` (ex.: `OPTS="--value ..."`); para editar, copiar o diretório do serviço com outro nome (o xbps-install pode sobrescrever o original).

## Serviços runit: comandos sv
fonte: https://docs.voidlinux.org/config/services/index.html
- `sv up <serviços>` / `sv down <serviços>` / `sv restart <serviços>` / `sv status <serviços>`
- `<serviços>` pode ser nome do diretório em `/var/service/` ou caminho completo.
- Status de um serviço: `sv status dhcpcd`; de todos habilitados: `sv status /var/service/*`

## Serviços runit: habilitar, desabilitar, testar
fonte: https://docs.voidlinux.org/config/services/index.html
- Habilitar (sistema rodando): `ln -s /etc/sv/<serviço> /var/service/` — inicia automaticamente e passa a subir no boot.
- Habilitar com sistema não rodando (ex.: chroot): `ln -s /etc/sv/<serviço> /etc/runit/runsvdir/default/`
- Impedir início no boot mantendo gerenciado pelo runit: `touch /etc/sv/<serviço>/down` (também serve para desativar serviços habilitados por padrão, ex.: agetty).
- Desabilitar: `rm /var/service/<serviço>` (ou `rm /etc/runit/runsvdir/default/<serviço>` se o sistema não estiver rodando).
- Testar antes de habilitar: `touch /etc/sv/<serviço>/down`, `ln -s /etc/sv/<serviço> /var/service/`, `sv once <serviço>`; se funcionar, remover o arquivo `down`.

## Serviços por usuário (runsvdir e turnstile)
fonte: https://docs.voidlinux.org/config/services/user-services.html
- Forma básica: serviço de sistema `/etc/sv/runsvdir-<usuário>` cujo `run` executa `exec chpst -u "$USER:$groups" runsvdir "$svdir"` com `svdir="$HOME/service"`.
- Limitação: esses serviços sobem no boot e não têm acesso à sessão gráfica nem ao barramento D-Bus de sessão.
- Controle pelo usuário: `sv status ~/service/*` ou `SVDIR=~/service sv restart <serviço>`.
- turnstile: serviços de usuário que iniciam com a sessão; com backend runit ficam em `~/.config/service/`.
- Serviços a subir antes do login: `~/.config/service/turnstile-ready/conf` (ex.: `core_services="dbus foo"`).
- Variáveis de ambiente: `exec chpst -e "$TURNSTILE_ENV_DIR" foo`; atualizar com `turnstile-update-runit-env DISPLAY XAUTHORITY`.
- D-Bus de sessão via turnstile: `mkdir -p ~/.config/service/dbus` e symlinks de `/usr/share/examples/turnstile/dbus.run` e `dbus.check` para `run` e `check`.

## Arquivos rc e core-services
fonte: https://docs.voidlinux.org/config/rc-files.html
- `/etc/rc.conf`: lido nos estágios 1 e 3 do runit; variáveis como `KEYMAP`, `HARDWARECLOCK`, `FONT`.
- `/etc/rc.local`: lido no estágio 2, configuração antes do login.
- `/etc/rc.shutdown`: lido no estágio 3, tarefas no desligamento.
- `/etc/runit/core-services`: scripts executados em ordem alfabética no estágio 1, antes dos serviços.
