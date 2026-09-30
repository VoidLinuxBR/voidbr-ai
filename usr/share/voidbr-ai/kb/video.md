## Vídeo: AMD
fonte: https://docs.voidlinux.org/config/graphical-session/graphics-drivers/amd.html
- Requer `linux-firmware-amd` (dependência de `linux`/`linux-lts`; instalar manualmente com kernel de versão específica).
- OpenGL: `mesa-dri` (necessário em Wayland ou `xorg-minimal`).
- Vulkan: `vulkan-loader` + `mesa-vulkan-radeon` e/ou `amdvlk`.
- Xorg: `xf86-video-amdgpu` ou `xf86-video-ati` (hardware antigo).
- VA-API: `mesa-vaapi`, `LIBVA_DRIVER_NAME=radeonsi`. VDPAU: `libvdpau-va-gl`, `VDPAU_DRIVER=va_gl`.

## Vídeo: Intel
fonte: https://docs.voidlinux.org/config/graphical-session/graphics-drivers/intel.html
- Requer `linux-firmware-intel` (dependência de `linux`/`linux-lts`).
- OpenGL: `mesa-dri`. Vulkan: `vulkan-loader` + `mesa-vulkan-intel`.
- VA-API: metapacote `intel-video-accel`; padrão `intel-media-driver` (`LIBVA_DRIVER_NAME=iHD`, desde Broadwell); `libva-intel-driver` (`LIBVA_DRIVER_NAME=i965`, até Coffee Lake).
- Problemas gráficos (esperado em Broadwell): adicionar `intel_iommu=igfx_off` à cmdline do kernel.
- Em chipsets novos, drivers DDX podem atrapalhar: remover `xf86-video-*`; em alguns, `xf86-video-intel` é necessário.

## Vídeo: NVIDIA nouveau
fonte: https://docs.voidlinux.org/config/graphical-session/graphics-drivers/nvidia.html
- Driver do kernel; necessário para boa parte dos compositores Wayland.
- OpenGL: `mesa-dri`. Vulkan (Kepler+): `vulkan-loader` + `mesa-vulkan-nouveau`.
- VA-API: `mesa-vaapi`, `LIBVA_DRIVER_NAME=nouveau`. Xorg: `xf86-video-nouveau`.

## Vídeo: NVIDIA proprietário
fonte: https://docs.voidlinux.org/config/graphical-session/graphics-drivers/nvidia.html
- Pacotes no repositório nonfree, integrados ao kernel via DKMS.
- Identificar a GPU: `lspci -k -d ::03xx`.
- Turing e mais novas: `nvidia`; Maxwell a Volta: `nvidia580`; Kepler: `nvidia470`; Fermi: `nvidia390`; Tesla e anteriores: usar nouveau.
- 32-bit (glibc): `nvidia<x>-libs-32bit` (ou `mesa-dri-32bit` com nouveau); pacotes 32-bit vêm do repositório multilib (`void-repo-multilib`, ver https://docs.voidlinux.org/xbps/repositories/index.html).
- Voltar ao nouveau: remover o pacote nvidia correspondente; blacklist do nouveau fica em `/etc/modprobe.d/nouveau_blacklist.conf`, `/usr/lib/modprobe.d/nvidia.conf` ou `/usr/lib/modprobe.d/nvidia-dkms.conf`.
- Wayland: GNOME e KDE têm backend EGLStreams; a maioria dos outros compositores exige GBM.
