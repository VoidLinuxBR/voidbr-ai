<div align="center">

# 🔵 voidbr-ai

**VoidBR AI - assistente do sistema: investiga a máquina real, explica e corrige com confirmação (GTK4 + CLI)**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

</div>

---

**VoidBR AI** — ajuda para o seu VoidBR, integrada ao sistema.

Pergunte com as suas palavras — *"meu som não sai"*, *"como instalo o Steam?"*,
*"o disco está cheio"*, *"o Wi-Fi caiu"* — e ele **investiga a máquina real**, explica
o que encontrou e propõe a correção, que **só roda depois da sua confirmação**.
Depois, verifica se resolveu de verdade.

## Dois modos

| | Sem IA | Com IA (Ollama local ou OpenAI) |
|---|---|---|
| **Check-up geral** | ✅ | ✅ (+ interpretação) |
| **Diagnósticos prontos**: rede, disco, pacotes, serviços, áudio, Bluetooth, memória/CPU | ✅ | ✅ |
| **Perguntas livres** ("como faço…", "por que…") | — | ✅ a IA consulta o sistema e responde |
| **Ações** (sempre com confirmação) | propostas pelas regras | propostas pela IA, validadas na lista branca |

A **IA local** roda no seu computador com o [voidbr-ollama](https://github.com/voidlinuxbr/voidbr-ollama):
nada sai da máquina e funciona offline. Na primeira vez o app oferece o assistente,
que sugere o modelo pela memória da máquina, instala, baixa com barra de progresso e testa.
Ele também instala a aceleração da placa de vídeo: NVIDIA → `voidbr-ollama-cuda` (CUDA, ~2,1 GB);
AMD/Intel → `vulkan-loader` + `mesa-vulkan-radeon`/`-intel` (o Vulkan do Ollama vem ligado por padrão).

## Uso

```bash
voidbr-ai-gui                               # interface gráfica (GTK4)
voidbr-ai                                   # conversa no terminal
voidbr-ai "como instalo o steam?"
voidbr-ai "faça um script que faça backup da pasta ~/Documentos"
voidbr-ai --checkup                         # check-up geral
voidbr-ai --diagnose audio                  # network, storage, packages, services,
                                            # audio, bluetooth, system
voidbr-ai --diagnose network --json         # saída estruturada
voidbr-ai --setup-ai                        # configura a IA local (Ollama)
voidbr-ai --list-tools                      # ferramentas e ações disponíveis
voidbr-ai --list-models                     # modelos que o provider/chave pode usar
voidbr-ai --history                         # últimas sessões
```

## Como funciona

```text
OBSERVAR → DIAGNOSTICAR → EXPLICAR → PROPOR → CONFIRMAR → EXECUTAR → VERIFICAR
```

Com IA, o modelo recebe um **catálogo de ferramentas de leitura** (chamada de ferramentas
nativa do Ollama/OpenAI) e decide o que consultar, em vários passos, até entender o
problema. Termina chamando `responder` com o diagnóstico, separando **fatos** (vistos nas
ferramentas) de **hipóteses**, e as ações que propõe.

| Camada | O que faz |
|---|---|
| `agent/` | investiga com a IA ou pelas regras, propõe, executa e verifica |
| `tools/` | ferramentas (leitura e ações) + **Tool Registry** com validação de argumentos |
| `providers/` | Ollama e OpenAI/compatíveis (via `urllib`, sem dependências extras) |
| `context/` | distro, kernel, init, desktop… coletados sob demanda |
| `setup.py` | assistente da IA local |
| `cli/`, `gui/` | `voidbr-ai` e `voidbr-ai-gui` — usam o mesmo Agent |

### Ferramentas de leitura (a IA pode chamar)

`system.info`, `system.memory`, `system.processes`, `system.dmesg`, `system.log`,
`system.read_config` (só `/etc`, `~/.config` e bootloader; arquivos com senhas/chaves bloqueados
e linhas de senha ocultadas), `system.boot`, `system.command`, `hardware.pci`, `hardware.usb`,
`service.status|list|log`, `pkg.search|info|files|owner|installed|updates|orphans|repos|cache`,
`kernel.list`, `disk.usage|devices|largest`, `network.diagnose`, `audio.status`, `bluetooth.status`.

### Ações (só com confirmação)

| Ação | Comando | Roda como |
|---|---|---|
| `service.start/stop/restart` | `sv … <serviço>` | root |
| `service.enable/disable` | `ln -s /etc/sv/<s> /var/service/` / `rm` | root |
| `pkg.install` / `pkg.remove` | `xbps-install -Sy …` / `xbps-remove -y …` | root |
| `system.update` | `xbps-install -Syu xbps && xbps-install -yu` | root |
| `pkg.clean_cache` / `pkg.remove_orphans` | `xbps-remove -yO` / `-yo` | root |
| `kernel.purge` | `vkpurge rm all` | root |
| `network.link_up`, `network.rfkill_unblock`, `network.nm_*` | `ip link set … up`, rfkill, `nmcli …` | root |
| `audio.enable_conf` | link do WirePlumber/pipewire-pulse em `/etc/pipewire/pipewire.conf.d` | root |
| `bluetooth.unblock` | rfkill | root |
| `audio.unmute`, `audio.volume`, `audio.start`, `bluetooth.power_on` | `wpctl …`, `pipewire`, `bluetoothctl power on` | você |

### Segurança

- A IA **não tem shell**: só chama ferramentas do catálogo, com argumentos validados
  (tipo, lista de valores, padrão do nome). Ferramenta ou ação fora da lista é descartada.
- Ações só rodam com `confirmed=True`, depois que você confirma na GUI/CLI; a confirmação
  mostra o comando, quem executa (root ou você) e avisos de risco.
- As ações root passam pelo `/usr/lib/voidbr-ai/voidbr-ai-helper` via `pkexec`
  (polkit `org.voidbr.ai.helper`), que tem **a sua própria lista branca** e valida tudo de novo.
  Pacotes essenciais (base-system, xbps, glibc, runit…) não podem ser removidos por ele.
- O instalador do xbps é chamado direto (o `vinstall` é interativo e chama `sudo`).

## Configuração

- global: `/etc/voidbr-ai/config.toml`
- usuário: `~/.config/voidbr-ai/config.toml` (a GUI grava aqui)

```toml
provider = "ollama"

[ollama]
model = "qwen3:4b"
num_ctx = 8192      # contexto (tokens); maior = mais memória
keep_alive = "30m"  # modelo fica carregado entre as perguntas
think = false       # qwen3 sem o modo "pensando" (bem mais rápido)

[agent]
max_steps = 8       # consultas ao sistema antes de responder
```

A chave da OpenAI nunca fica no arquivo: `api_key_env` (nome da variável) ou `api_key_file`.

## Histórico

`~/.local/share/voidbr-ai/`: `sessions/`, `diagnostics/` e `logs/voidbr-ai.log`.
Credenciais não são gravadas.

## Instalação

```bash
git clone https://github.com/voidlinuxbr/voidbr-ai.git
cd voidbr-ai/pkgfile && pkgmake
```

Para as ações, tenha um agente polkit rodando (no Hyprland: `hyprpolkitagent`).

## Estender

Um domínio novo (vídeo, impressora…) é um módulo em `tools/` com `register(reg)` e, para
funcionar sem IA, `STEPS`, `KEYWORDS`, `analyze(state, reg)` e `register_checks(reg)`,
listado em `tools/__init__.py`. O Agent, a CLI e a GUI não mudam.

## Créditos

Vilmar Catafesta <vcatafesta@gmail.com> — https://voidbr.org — Licença MIT.
