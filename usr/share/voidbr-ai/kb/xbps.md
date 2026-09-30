## XBPS: ferramentas principais
fonte: https://docs.voidlinux.org/xbps/index.html
- `xbps-query`: busca/info de pacotes locais; com `-R`, nos repositórios.
- `xbps-install`: instala/atualiza pacotes e sincroniza índices.
- `xbps-remove`: remove pacotes, órfãos e arquivos em cache.
- `xbps-reconfigure`: roda passos de configuração; após mudar configs normalmente precisa de `--force` (`-f`).
- `xbps-alternatives`: lista/define alternativas; `xbps-pkgdb`: verifica/corrige o banco de pacotes; `xbps-rindex`: repositórios locais.

## XBPS: atualizar, buscar, consultar
fonte: https://docs.voidlinux.org/xbps/index.html
- Atualizar o sistema: `xbps-install -Su`. Se a atualização incluir o pacote `xbps`, rodar de novo para aplicar o resto.
- O XBPS não reinicia serviços atualizados; `xcheckrestart` (pacote `xtools`, rodar como usuário comum) lista processos com binário antigo.
- Kernel panic após atualização: provável `/boot` cheio (ver remoção de kernels antigos).
- Buscar nos repositórios: `xbps-query -Rs <padrão>` (sem `-R` busca nos instalados).
- Arquivos de um pacote: `xbps-query -f <pacote>`.
- Qual pacote tem um arquivo: `xlocate -S` (atualiza índice) e `xlocate <arquivo>` (xtools); `xbps-query -Ro <arquivo>` funciona mas é desaconselhado.
- Listar instalados: `xpkg` (xtools).

## XBPS: uso avançado
fonte: https://docs.voidlinux.org/xbps/advanced-usage.html
- Downgrade: `xdowngrade /var/cache/xbps/pkg-1.0_1.xbps` (xtools), ou `xbps-rindex -a /var/cache/xbps/pkg-1.0_1.xbps` e `xbps-install -R /var/cache/xbps/ -f pkg-1.0_1`.
- Segurar versão: `xbps-pkgdb -m hold <pacote>` / `xbps-pkgdb -m unhold <pacote>`.
- Travar no repositório de origem: `xbps-pkgdb -m repolock <pacote>` / `repounlock`.
- Ignorar pacote: linha `ignorepkg=<pacote>` num arquivo xbps.d(5) (ex.: para remover `sudo`).
- Pacote virtual: `virtualpkg=linux:linux5.6` num arquivo xbps.d.

## XBPS: repositórios oficiais
fonte: https://docs.voidlinux.org/xbps/repositories/index.html
- Principal (glibc): `/current` relativo ao mirror; musl: `/current/musl`; aarch64: `/current/aarch64`.
- Sub-repositórios (desabilitados por padrão), habilitados instalando: `void-repo-nonfree`, `void-repo-multilib` (32-bit, só x86_64 glibc), `void-repo-multilib-nonfree`, `void-repo-debug`.
- Esses pacotes só instalam um arquivo de repositório em `/usr/share/xbps.d`.
- Repositórios remotos precisam ser assinados.

## XBPS: mirrors
fonte: https://docs.voidlinux.org/xbps/repositories/mirrors/changing.html
- Padrão: `repo-default.voidlinux.org`. Arquivos em `/usr/share/xbps.d`; cópias em `/etc/xbps.d` têm prioridade.
- `xmirror` (pacote `xmirror`) troca o mirror selecionado.
- Manual: `cp /usr/share/xbps.d/*-repository-*.conf /etc/xbps.d/`, trocar a URL com sed, depois `xbps-install -S`.
- Verificar repositórios: `xbps-query -L`.

## XBPS: problemas comuns
fonte: https://docs.voidlinux.org/xbps/troubleshooting/common-issues.html
- Erros ao instalar/atualizar: sincronizar índice com `xbps-install -S`.
- "Operation not permitted" no reposync: data/hora do sistema pode estar errada.
- "Not Found" no reposync: xbps.d aponta para repositório errado para o sistema.
- "unresolvable shlib": atualizar o sistema; `xbps-remove -o` remove dependências órfãs.
- "Transaction aborted due to unresolved shlibs": repositório em estado staged; aguardar builds.
- Sistema quebrado: usar xbps estático.
