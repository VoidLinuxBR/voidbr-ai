## Logs: syslog com socklog
fonte: https://docs.voidlinux.org/config/services/logging.html
- A instalação padrão não traz daemon de syslog.
- socklog (do autor do runit) é o recomendado se não souber qual usar.
- Instalar o pacote `socklog-void` e habilitar os serviços `socklog-unix` e `nanoklogd`: `ln -s /etc/sv/socklog-unix /var/service/` e `ln -s /etc/sv/nanoklogd /var/service/`.
- Garantir que nenhum outro syslog esteja rodando.
- Logs ficam em subdiretórios de `/var/log/socklog/`; `svlogtail` facilita a leitura.
- Só `root` e membros do grupo `socklog` podem ler os logs.
- Alternativas nos repositórios: `rsyslog` e `metalog`.

## Logs: serviços runit
fonte: https://docs.voidlinux.org/config/services/index.html
- Um serviço pode ter um diretório `log`; a saída do `run` do serviço é enviada por pipe ao `run` do `log`.

## Logs: outros locais citados no handbook
fonte: https://docs.voidlinux.org/config/kernel.html
- Logs de build de módulos DKMS: `/var/lib/dkms/`.
