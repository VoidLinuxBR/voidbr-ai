## Bluetooth
fonte: https://docs.voidlinux.org/config/bluetooth.html
- Verificar bloqueio com `rfkill`; remover bloqueio de software: `rfkill unblock bluetooth`. Bloqueio de hardware: chave física ou opção na BIOS.
- Instalar o pacote `bluez` e habilitar os serviços `bluetoothd` e `dbus`.
- Adicionar o usuário ao grupo `bluetooth` e reiniciar o `dbus` (ou reiniciar o sistema); reiniciar o dbus pode matar processos que o usam.
- Áudio: ALSA precisa de `bluez-alsa`; PulseAudio não precisa de nada extra; PipeWire precisa de `libspa-bluetooth`.
- Gerenciar conexões e controladoras com `bluetoothctl`.
- Configuração principal: `/etc/bluetooth/main.conf`.
