## Áudio: PipeWire pré-requisitos
fonte: https://docs.voidlinux.org/config/media/pipewire.html
- Requer barramento D-Bus de sessão do usuário (ou lançar o DE/WM com `dbus-run-session`).
- Requer `XDG_RUNTIME_DIR` definido.
- Sem elogind, o usuário precisa estar nos grupos `audio` e `video`.

## Áudio: PipeWire configuração
fonte: https://docs.voidlinux.org/config/media/pipewire.html
- Instalar `pipewire` (traz o gerenciador de sessão `wireplumber`).
- WirePlumber (sistema): `mkdir -p /etc/pipewire/pipewire.conf.d` e `ln -s /usr/share/examples/wireplumber/10-wireplumber.conf /etc/pipewire/pipewire.conf.d/`
- WirePlumber (usuário): mesmo link em `${XDG_CONFIG_HOME}/pipewire/pipewire.conf.d/`.
- Interface PulseAudio: remover/parar `pulseaudio` e `ln -s /usr/share/examples/pipewire/20-pipewire-pulse.conf /etc/pipewire/pipewire.conf.d/`
- `pipewire` roda como usuário (não é serviço de sistema); iniciar pelo autostart do DE, XDG autostart (`/etc/xdg/autostart` ou `~/.config/autostart`, com `dex` se necessário) ou script do compositor.
- Testar: `pipewire`; status: `wpctl status`; PulseAudio: `pactl info` (pacote `pulseaudio-utils`).
- Bluetooth: `libspa-bluetooth`. JACK: `libjack-pipewire` e `pw-jack <app>`.
- ALSA via PipeWire: instalar `alsa-pipewire`, `mkdir -p /etc/alsa/conf.d`, linkar `/usr/share/alsa/alsa.conf.d/50-pipewire.conf` e `99-pipewire-default.conf` em `/etc/alsa/conf.d`.

## Áudio: PipeWire problemas
fonte: https://docs.voidlinux.org/config/media/pipewire.html
- "Failed to connect to system bus ... /run/dbus/system_bus_socket": habilitar o serviço `dbus`.
- "Failed to connect to session bus ... machine-id": D-Bus de sessão não está rodando.
- "no runtime dir found": `XDG_RUNTIME_DIR` mal configurado.
- Só saída "dummy": wireplumber não está rodando (configurar e reiniciar pipewire) ou usuário fora dos grupos `audio`/`video` sem elogind.

## Áudio: ALSA
fonte: https://docs.voidlinux.org/config/media/alsa.html
- Instalar `alsa-utils`; usuário no grupo `audio`.
- Serviço `alsa` salva/restaura estado (volume) no desligamento/boot.
- Ordem das placas: `cat /proc/asound/modules`.
- Placa padrão: `/etc/asound.conf` ou `~/.asoundrc` (`defaults.ctl.card 2;` `defaults.pcm.card 2;`), ou `options snd_usb_audio index=0` em `/etc/modprobe.d/alsa.conf`.
