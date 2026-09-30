## vinstall (wrapper do xbps-install)
fonte: https://github.com/voidlinuxbr/voidbr-vinstall (README e src/vinstall-v1.6.5.go)
- Wrapper em Go para `xbps-install`/`xbps-query`, mantido pela comunidade Void Linux Brasil (autor: Vilmar Catafesta).
- Pacote: `voidbr-vinstall` (`sudo xbps-install -S voidbr-vinstall`, no repositório voidlinuxbr/Chili Linux).
- Aceita as flags nativas do `xbps-install`; roda como usuário comum e pede sudo só na escrita.
- Se o pacote não existe, busca sugestões com `xbps-query -Rs` e mostra menu interativo ([*] instalado, [-] disponível).
- Exemplos: `vinstall telegram`, `vinstall -Syu`, `vinstall -f <pacote>` (reinstalar/downgrade).
- Remoção: `vinstall -X <pacote>`; `vinstall -XR <pacote>` (com dependências órfãs); sufixos após -X são repassados ao `xbps-remove`.
- Busca de arquivo: `vinstall -F <arquivo>` (local), `vinstall -FR <arquivo>` (remoto).
- Consultas: `-Li` (instalados), `-Lo` (órfãos), `-Ss <termo>` (repositórios), `-Sss` (busca detalhada), `-Ssi` (só instalados), `-Ssu` (só não instalados).
- `-Sy` sincroniza e lista atualizações; `-Syy` força resync; `-Sf` mostra todas as diferenças, inclusive downgrades.
- Manutenção: `-Scc` limpa cache e órfãos; `--history` mostra histórico de transações.

## vservice (gerenciador de serviços runit)
fonte: https://github.com/voidlinuxbr/voidbr-vinstall (src/vservice-v1.1.0.go)
- Uso: `vservice {comando} [serviço...]`; trabalha com `/etc/sv` e `/var/service` (enable cria symlink de `/etc/sv/<s>` em `/var/service`).
- Comandos: `enable|add`, `disable`, `remove|rm`, `start|st|up`, `stop|down`, `restart`, `status`, `list`, `archive-logs`, `monitor` (checa com `sv status` se cada serviço em `/var/service` está `run:`).
- Opções: `--dry-run`, `--install-completion`. Log em `/var/log/vservice.log`.
- O mesmo repositório tem também fontes de `voidbr-dmesg`, `voidbr-vkpurge` ("Remove kernels órfãos do Void Linux com segurança") e `voidbr-vpm` (wrapper do xbps-query), sem documentação no README.

## pkgmake (build de pacotes XBPS estilo makepkg)
fonte: https://github.com/voidlinuxbr/voidbr-pkgmake (README.md)
- Ferramenta estilo makepkg para Void/XBPS: resolve dependências, compila e empacota a partir de um `PKGFILE`, gera `.xbps`, instala (opcional), assina e mantém repositório local.
- Pacote: `voidbr-pkgmake`, via repositório `repository=https://void.chililinux.com/voidlinux/current` em `/etc/xbps.d/chililinux.conf`.
- Instala `/usr/bin/pkgmake`, `/usr/share/pkgmake` e `/etc/pkgmake.conf` (config; flags da linha de comando têm prioridade).
- Deve rodar como usuário comum; só a instalação de dependências precisa de privilégio. Usa `xbps-install`, `xbps-create`, `xbps-rindex`.
- Opções: `-s` (instalar depends/makedepends), `-i` (instalar após build), `-f`, `-q`, `-v`, `-c` (limpar), `-p` (mostrar config), `-k <dir>` (destino dos pacotes/repodata).
- Assinatura/repositório: `--gen-key`, `--privkey <pem>`, `--sign`, `--sign-only`, `--reindex`, `--reindex-only`, `--reindex-all`.
- Criar receita: `pkgmake new <pacote>`; importar: `new --from-arch`, `--from-void`, `--from-voidlinuxbr`, `--from-venom` (exigem revisão manual).
- PKGFILE: shell script inspirado no PKGBUILD e compatível com template do Void; funções `prepare()` (opcional), `build()` e `package()`.
- Exemplos: `pkgmake`, `pkgmake -s -i`, `pkgmake --sign`, `pkgmake new nano`.
