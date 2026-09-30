## Impressão: CUPS
fonte: https://docs.voidlinux.org/config/print/index.html
- Instalar o pacote `cups` e habilitar o serviço `cupsd` (`ln -s /etc/sv/cupsd /var/service/`).
- `cups-filters` é necessário para a maioria das impressoras, inclusive na impressão sem driver.
- Configurar pelo navegador em `http://localhost:631` (Administration > Printers > Add Printer); o login exige que o usuário esteja no grupo `lpadmin`.
- Pela linha de comando: `lpadmin(8)`.
- Interface gráfica: `system-config-printer` (rodar como root); com `cups-pk-helper` usuários comuns podem usá-lo via PolicyKit.
- Achar o URI de uma impressora USB manualmente: `/usr/lib/cups/backend/usb`.

## Impressão: drivers por fabricante
fonte: https://docs.voidlinux.org/config/print/index.html
- Vários modelos: `gutenprint`.
- HP: `hplip`; configuração guiada com `hp-setup -i`.
- Brother: `foomatic-db`, `foomatic-db-nonfree` e `brother-brlaser`.
- Epson (jato de tinta): `epson-inkjet-printer-escpr`.
- Canon PIXMA/MAXIFY: `cnijfilter2` (repositório nonfree: `void-repo-nonfree`).

## Impressão: sem driver e impressoras de rede
fonte: https://docs.voidlinux.org/config/print/index.html
- Impressoras de rede modernas com IPP Everywhere imprimem sem driver (lista em https://www.pwg.org/printers/); `cups-filters` continua necessário.
- Achar impressoras na rede sozinho (ZeroConf): instalar `avahi` e `nss-mdns` e habilitar o serviço `avahi-daemon`.
- Impressora sem driver pela linha de comando: `lpadmin -p NOME -E -v ipp://ENDERECO/ipp/print -m everywhere` (ver lpadmin(8)).
- Impressoras USB com IPP-USB imprimem sem driver com o pacote `ipp-usb` (serviço `ipp-usb`).
