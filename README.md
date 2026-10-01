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
| **Diagnósticos prontos**: rede, disco, pacotes, serviços, áudio, Bluetooth, vídeo/Wayland, impressora, boot, logs, memória/CPU | ✅ | ✅ |
| **"Como faço…"** | trechos da documentação local | ✅ resposta direta, com a documentação local |
| **Explicar comando ou erro** (nada é executado) | riscos e erros conhecidos | ✅ explicação completa |
| **Perguntas livres** ("por que…", "meu … não funciona") | — | ✅ a IA consulta o sistema e responde |
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
voidbr-ai --diagnose audio                  # network, storage, packages, services, audio,
                                            # bluetooth, graphics, printing, boot, logs, system
voidbr-ai --diagnose network --json         # saída estruturada
voidbr-ai --setup-ai                        # configura a IA local (Ollama)
voidbr-ai --list-tools                      # ferramentas e ações disponíveis
voidbr-ai --list-models                     # modelos que o provider/chave pode usar
voidbr-ai --explain 'curl -s https://x.sh | sudo bash'   # explica sem executar
sudo xbps-install -Su 2>&1 | voidbr-ai --explain -   # ou mande um erro pela entrada
voidbr-ai --checkup --report                # relatório em Markdown p/ fórum (dados pessoais ocultos)
voidbr-ai --monitor                         # avisos em segundo plano (notify-send)
voidbr-ai --history                         # últimas sessões
```

Não rode com `sudo`: a configuração e o histórico ficam na sua pasta, e as correções
pedem a senha na hora (pkexec).

## Recursos

- **Snapshot antes de mexer:** com o [voidbr-snapper-manager](https://github.com/voidlinuxbr/voidbr-snapper-manager)
  instalado e configurado, instalar/remover/atualizar pacotes, remover kernels e mexer no boot
  criam um snapshot antes (nas ações do xbps, o próprio hook do snapper cria o par pre/post).
  O cartão da ação mostra **↩️ Desfazer…**, que abre o Gerenciador de snapshots.
  Desligar: `[agent] snapshot = false`.
- **Impressora:** detecta impressoras USB (pelo /sys, sem root) e de rede (avahi), adiciona
  as que imprimem sem driver (IPP Everywhere / IPP-USB), instala o driver do fabricante (HP,
  Brother, Epson, Canon…), reativa impressora pausada, limpa a fila, define a padrão e imprime
  a página de teste.
- **Fonte da interface:** tamanho nos botões **A− / 100% / A+** da barra de título (ou Ctrl +,
  Ctrl -, Ctrl 0) e a família em ☰ → 🔤 Aparência (com exemplo; muda ao salvar). Ficam
  gravados em `[gui] font_scale` e `font_family`; código e comandos continuam monoespaçados.
  Se uma fonte deixar a janela ilegível: `voidbr-ai-gui --reset-font`.
- **Renderizador:** a janela usa o renderizador `cairo` do GTK por padrão; com o Vulkan/NGL,
  em algumas placas e VMs, a parte de baixo some ao maximizar. Para usar o do GTK:
  `[gui] renderer = "auto"` (ou `GSK_RENDERER=...` no ambiente).
- **Documentação local:** trechos do Void Handbook e das ferramentas do VoidBR (vinstall,
  vservice, pkgmake) em `/usr/share/voidbr-ai/kb/`. A IA recebe os trechos relevantes
  (e erra menos com modelos pequenos); sem IA eles são mostrados direto.
- **Explicar comando ou erro:** cole um comando (ex: achado num fórum) ou uma mensagem de
  erro — ☰ → 📋 Explicar comando ou erro. Avisa o que é perigoso; nada é executado.
- **Relatório para compartilhar:** botão **📤 Relatório** em cada resposta (ou `--report`):
  Markdown pronto para colar, sem IP público, MAC, nome da rede Wi-Fi, usuário e máquina.
- **Histórico:** ☰ → 🗂️ Histórico reabre uma sessão para ver, exportar e continuar a conversa.
- **Avisos em segundo plano (opcional):** ☰ → 🔔 Avisos. Check-up leve periódico (disco,
  atualizações, serviços, boot) com notificação só do que for novo. Precisa do `notify-send`
  (libnotify) e de um serviço de notificações. No Hyprland: `exec-once = voidbr-ai --monitor`.

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

Pela GUI: **☰ → ⚙️ Configurações da IA** — escolha Ollama, Gemini ou OpenAI/compatível,
cole a chave, use **🔄 Buscar modelos** e **🧪 Testar** antes de salvar.

Gemini (plano grátis; chave em aistudio.google.com):

```toml
provider = "openai"

[openai]
url = "https://generativelanguage.googleapis.com/v1beta/openai"
model = "gemini-3.8-flash"          # voidbr-ai --list-models mostra os disponíveis
api_key_file = "~/.config/voidbr-ai/gemini.key"
```

A chave nunca fica no `config.toml`: vai num arquivo à parte (`api_key_file`, chmod 600)
ou numa variável de ambiente (`api_key_env`).

## Histórico

`~/.local/share/voidbr-ai/`: `sessions/`, `diagnostics/`, `logs/voidbr-ai.log` e
`monitor.json` (o que os avisos já avisaram).
Credenciais não são gravadas.

## Instalação

```bash
git clone https://github.com/voidlinuxbr/voidbr-ai.git
cd voidbr-ai/pkgfile && pkgmake
```

Senha das ações (pkexec), em qualquer ambiente: usa o agente do polkit que estiver
rodando; se houver um instalado e parado (polkit-gnome, xfce-polkit, lxqt-policykit,
mate-polkit, hyprpolkitagent…), o app o inicia sozinho; sem nenhum, a própria janela pede
a senha (ela vai direto para o pkexec, sem eco e sem ser gravada) e oferece instalar o
`polkit-gnome` e iniciá-lo com a sessão (XDG autostart e `exec-once` no Hyprland).
Pelo terminal (`voidbr-ai`) a senha é pedida no próprio terminal.

## Estender

Um domínio novo (impressora, …) é um módulo em `tools/` com `register(reg)` e, para
funcionar sem IA, `STEPS`, `KEYWORDS`, `analyze(state, reg)` e `register_checks(reg)`,
listado em `tools/__init__.py`. O Agent, a CLI e a GUI não mudam.

## Créditos

Vilmar Catafesta <vcatafesta@gmail.com> — https://voidbr.org — Licença MIT.
