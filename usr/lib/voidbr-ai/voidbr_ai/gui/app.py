# -*- coding: utf-8 -*-
#
#   voidbr_ai/gui/app.py - interface gráfica (GTK4 + PyGObject)
#
#   Copyright (c) 2026, Vilmar Catafesta <vcatafesta@gmail.com>
#   Copyright (c) 2026, ChiliLinux Development Team <https://chililinux.com> <https://github.com/chililinux>
#   Assembled By Vilmar Catafesta for the VoidBR project.
#   All rights reserved.
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#   THE SOFTWARE.
##############################################################################
"""
voidbr-ai-gui - Interface gráfica do VoidBR AI.

A GUI é só uma casca sobre o Agent (o mesmo da CLI):
  - não executa comandos: pede ao Agent;
  - o Agent roda numa thread e manda eventos (passos) para a GUI;
  - ações só rodam depois do "▶ Executar" + confirmação + pkexec.

Mesmo visual do voidbr-iso-writer e do voidbr-snapper-manager-gui.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

from .. import APP_NAME, APP_VERSION, config, history, setup, tools  # noqa: E402
from ..agent import Agent  # noqa: E402

APP_ID = "br.voidbr.ai"

PROVIDERS = [("Automático (Ollama local, se houver)", "auto"), ("Nenhum (só regras)", "none"),
             ("Ollama (local)", "ollama"), ("Gemini (Google)", "gemini"),
             ("OpenAI / API compatível", "openai")]

# "Gemini" é o provider openai apontando para a API compatível do Google
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
OPENAI_URL = "https://api.openai.com/v1"

ESCALA_MIN, ESCALA_MAX = 0.7, 2.0     # tamanho da fonte: 70% a 200%


def _familia_segura(nome):
    """Nome de fonte para o CSS (sem aspas/chaves que quebrem a regra)."""
    return re.sub(r'[^\w .,+-]', "", str(nome or "")).strip()[:80]

ICONE_PASSO = {"ok": "✅", "warn": "⚠️", "fail": "❌", "info": "•", "running": "⏳"}
ICONE_ACHADO = {"erro": "❌", "aviso": "⚠️", "info": "ℹ️", "ok": "✅"}

CSS = """
window {
    background-color: #1e1f29;
}

label {
    color: #f1f1f1;
}

.titulo-app {
    font-size: 20px;
    font-weight: 800;
    color: #7dd3fc;
}

.subtitulo {
    font-weight: bold;
    color: #cbd5e1;
}

.botao-azul {
    background: linear-gradient(180deg, #3b82f6, #2563eb);
    color: white;
    font-weight: bold;
    border-radius: 10px;
    padding: 8px 14px;
}
.botao-azul:hover { background: #3b82f6; }

.botao-verde {
    background: linear-gradient(180deg, #34d399, #059669);
    color: white;
    font-weight: bold;
    border-radius: 10px;
    padding: 8px 14px;
}
.botao-verde:hover { background: #34d399; }

.botao-vermelho {
    background: linear-gradient(180deg, #f87171, #dc2626);
    color: white;
    font-weight: bold;
    border-radius: 10px;
    padding: 8px 14px;
}
.botao-vermelho:hover { background: #f87171; }

.botao-cinza {
    background: linear-gradient(180deg, #9ca3af, #6b7280);
    color: white;
    font-weight: bold;
    border-radius: 10px;
    padding: 8px 14px;
}
.botao-cinza:hover { background: #9ca3af; }

.botao-laranja {
    background: linear-gradient(180deg, #fbbf24, #d97706);
    color: white;
    font-weight: bold;
    border-radius: 10px;
    padding: 8px 14px;
}
.botao-laranja:hover { background: #fbbf24; }

button:disabled {
    opacity: 0.45;
}

.caixa-status {
    background-color: #2a2b3a;
    border-radius: 10px;
    padding: 8px;
}

.caixa-alerta {
    background-color: #3b2f1a;
    border: 1px solid #d97706;
    border-radius: 10px;
    padding: 8px;
}

.cabecalho-app,
.cabecalho-app:backdrop {
    background: #1a1b26;
    color: #f1f1f1;
    box-shadow: none;
}

.botao-fonte {
    font-weight: bold;
    padding: 2px 10px;
    min-height: 24px;
    background: #3b3d52;
    color: #f1f1f1;
    border: 1px solid #4b4e66;
}
.botao-fonte label { color: #f1f1f1; }
.botao-fonte:hover { background: #4b4e66; }
.botao-fonte:disabled { background: #2a2b3a; }
.botao-fonte:disabled label { color: #6b7280; }

.botao-menu {
    border-radius: 8px;
}

.conversa {
    background-color: #1e1f29;
}

.cartao {
    background-color: #2a2b3a;
    border-radius: 10px;
    padding: 12px;
}
.cartao-erro  { border-left: 4px solid #dc2626; }
.cartao-aviso { border-left: 4px solid #d97706; }
.cartao-ok    { border-left: 4px solid #059669; }
.cartao-llm   { border-left: 4px solid #7dd3fc; }

.bolha-usuario {
    background-color: #2563eb;
    border-radius: 10px;
    padding: 10px 14px;
}

.passo-rodando { color: #9ca3af; }
.passo-grupo   { color: #7dd3fc; font-weight: bold; margin-top: 6px; }
.saida         { font-family: monospace; font-size: 11px; color: #9ca3af; }

.botao-chip {
    background: #33354a;
    color: #f1f1f1;
    border-radius: 16px;
    padding: 4px 12px;
}
.botao-chip:hover { background: #3b82f6; }

progressbar > trough { background-color: #1a1b26; min-height: 8px; border-radius: 4px; }
progressbar > trough > progress { background-color: #34d399; min-height: 8px; border-radius: 4px; }
.detalhe       { color: #9ca3af; }
.codigo        { font-family: monospace; background: #0b1220; padding: 8px 10px;
                 border-radius: 6px; }
.hipotese      { color: #fbbf24; font-style: italic; }

.comando {
    font-family: monospace;
    color: #7dd3fc;
    background-color: #1a1b26;
    border-radius: 6px;
    padding: 4px 8px;
}

textview, textview text {
    background-color: #2a2b3a;
    color: #f1f1f1;
}

entry {
    background-color: #2a2b3a;
    color: #f1f1f1;
    border-radius: 8px;
    min-height: 34px;
}

dropdown > button {
    background: #2a2b3a;
    color: #f1f1f1;
}

popover > contents {
    background-color: #2a2b3a;
    color: #f1f1f1;
}
"""


def esc(texto):
    return GLib.markup_escape_text(str(texto or ""))


def texto_com_codigo(texto):
    """Separa os blocos ``` da resposta: [markup do texto, "<tt>código</tt>", ...]."""
    partes = []
    for n, pedaco in enumerate(texto.split("```")):
        if n % 2:           # dentro de ``` … ```: tira a linha da linguagem (```bash)
            linhas = pedaco.split("\n")
            if linhas and linhas[0].strip() and " " not in linhas[0].strip():
                linhas = linhas[1:]
            codigo = "\n".join(linhas).strip("\n")
            if codigo:
                partes.append(f"<tt>{esc(codigo)}</tt>")
        elif pedaco.strip():
            partes.append(esc(pedaco.strip()))
    return partes or [esc(texto)]


# ---------------------------------------------------------------------------
# cartões da conversa
# ---------------------------------------------------------------------------

class CartaoPassos(Gtk.Box):
    """Lista de passos do Agent: ● Verificando… → ✅ Verificando — resumo."""

    def __init__(self, titulo):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("cartao")
        rot = Gtk.Label(label=titulo, xalign=0)
        rot.add_css_class("subtitulo")
        self.append(rot)
        self.linhas = {}

    def progresso(self, texto, frac):
        if not hasattr(self, "barra"):
            self.barra = Gtk.ProgressBar(show_text=True)
            self.append(self.barra)
        if frac is None:
            self.barra.pulse()
        else:
            self.barra.set_fraction(frac)
        self.barra.set_text(f"{texto}  {frac * 100:.1f}%" if frac is not None else texto)

    def remover_fluxo(self):
        """Tira o texto ao vivo (a resposta completa aparece no cartão da IA)."""
        lbl = self.linhas.pop("__fluxo", None)
        if lbl is not None:
            self.remove(lbl)

    def evento(self, ev):
        if ev.kind == "stream":
            lbl = self.linhas.get("__fluxo")
            if lbl is None:
                lbl = Gtk.Label(xalign=0, wrap=True, selectable=True)
                lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                self.linhas["__fluxo"] = lbl
                self.append(lbl)
            lbl.set_text(lbl.get_text() + ev.label)
            return
        if ev.kind == "output":
            lbl = self.linhas.get("__saida")
            if lbl is None:
                lbl = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
                lbl.add_css_class("saida")
                self.linhas["__saida"] = lbl
                self.append(lbl)
            lbl.set_text(ev.label)
            return
        if ev.kind == "info" and ev.id.startswith("hdr-"):
            lbl = Gtk.Label(label=ev.label, xalign=0)
            lbl.add_css_class("passo-grupo")
            self.append(lbl)
            return
        lbl = self.linhas.get(ev.id)
        if lbl is None:
            lbl = Gtk.Label(xalign=0, wrap=True, selectable=True)
            self.linhas[ev.id] = lbl
            self.append(lbl)
        if ev.status == "running":
            lbl.add_css_class("passo-rodando")
            lbl.set_markup(f"●  {esc(ev.label)}")
        else:
            lbl.remove_css_class("passo-rodando")
            resumo = f"  <span foreground='#9ca3af'>— {esc(ev.summary)}</span>" if ev.summary else ""
            lbl.set_markup(f"{ICONE_PASSO.get(ev.status, '•')}  {esc(ev.label)}{resumo}")


# ---------------------------------------------------------------------------
# janela principal
# ---------------------------------------------------------------------------

class JanelaVoidbrAI(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="VoidBR AI")
        self.cfg = config.load()
        g = self.cfg.get("gui", {})
        self.set_default_size(int(g.get("width", 900)), int(g.get("height", 700)))
        self.agent = Agent(self.cfg)
        self.ocupado = False
        self.passos = None          # CartaoPassos que recebe os eventos agora

        # --- CSS ---
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # tamanho da fonte (A− / A+ / Ctrl+ Ctrl- Ctrl0), vale para todas as janelas do app
        self.css_fonte = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), self.css_fonte, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        try:
            self.escala = min(ESCALA_MAX, max(ESCALA_MIN, float(g.get("font_scale", 1.0))))
        except (TypeError, ValueError):
            self.escala = 1.0
        self.familia = _familia_segura(g.get("font_family", ""))

        # --- Barra de título com menu ---
        cabecalho = Gtk.HeaderBar()
        cabecalho.add_css_class("cabecalho-app")
        self.set_titlebar(cabecalho)

        fonte = Gtk.Box(spacing=0)
        fonte.add_css_class("linked")
        self.b_menor = Gtk.Button(label="A−", tooltip_text="Diminuir a fonte (Ctrl -)")
        self.b_escala = Gtk.Button(label="100%", tooltip_text="Tamanho normal (Ctrl 0)")
        self.b_maior = Gtk.Button(label="A+", tooltip_text="Aumentar a fonte (Ctrl +)")
        for b, passo in ((self.b_menor, -1), (self.b_escala, 0), (self.b_maior, 1)):
            b.add_css_class("botao-fonte")
            b.connect("clicked", lambda _b, p=passo: self.mudar_fonte(p))
            fonte.append(b)
        cabecalho.pack_start(fonte)

        menu = Gio.Menu()
        menu.append("🦙 Configurar IA local (Ollama)", "win.ia")
        menu.append("⚙️ Configurações da IA", "win.configuracoes")
        menu.append("📋 Explicar comando ou erro…", "win.explicar")
        menu.append("🗂️ Histórico", "win.historico")
        menu.append("🔔 Avisos em segundo plano…", "win.avisos")
        menu.append("🔤 Aparência (fonte)…", "win.aparencia")
        menu.append("🧰 Ferramentas disponíveis", "win.ferramentas")
        menu.append("ℹ️ Sobre / Créditos", "win.sobre")
        botao_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        botao_menu.add_css_class("botao-menu")
        cabecalho.pack_end(botao_menu)

        self.spinner = Gtk.Spinner()
        cabecalho.pack_end(self.spinner)

        for nome, cb in (("ia", self.ao_clicar_ia),
                         ("configuracoes", self.ao_clicar_configuracoes),
                         ("historico", self.ao_clicar_historico),
                         ("explicar", self.ao_clicar_explicar),
                         ("avisos", self.ao_clicar_avisos),
                         ("aparencia", self.ao_clicar_aparencia),
                         ("ferramentas", self.ao_clicar_ferramentas),
                         ("sobre", self.ao_clicar_sobre),
                         ("fonte_mais", lambda *_: self.mudar_fonte(1)),
                         ("fonte_menos", lambda *_: self.mudar_fonte(-1)),
                         ("fonte_normal", lambda *_: self.mudar_fonte(0))):
            acao = Gio.SimpleAction.new(nome, None)
            acao.connect("activate", cb)
            self.add_action(acao)
        app.set_accels_for_action("win.fonte_mais", ["<Control>plus", "<Control>equal",
                                                     "<Control>KP_Add"])
        app.set_accels_for_action("win.fonte_menos", ["<Control>minus", "<Control>KP_Subtract"])
        app.set_accels_for_action("win.fonte_normal", ["<Control>0", "<Control>KP_0"])
        self.aplicar_fonte()

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.set_child(caixa)

        # --- Título ---
        titulo = Gtk.Label(label="🤖 VoidBR AI", xalign=0)
        titulo.add_css_class("titulo-app")
        caixa.append(titulo)
        sub = Gtk.Label(xalign=0, wrap=True, label=(
            "Ajuda para o seu VoidBR: pergunte o que quiser — ele investiga a máquina real, "
            "explica e só muda algo com a sua confirmação."))
        sub.add_css_class("detalhe")
        caixa.append(sub)

        # --- Aviso (ambiente) ---
        self.caixa_alerta = Gtk.Box(spacing=10)
        self.caixa_alerta.add_css_class("caixa-alerta")
        self.label_alerta = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.caixa_alerta.append(self.label_alerta)
        self.caixa_alerta.set_visible(False)
        caixa.append(self.caixa_alerta)

        # --- Conversa ---
        self.conversa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                                margin_top=4, margin_bottom=4, margin_start=2, margin_end=8)
        self.rolagem = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.rolagem.add_css_class("conversa")
        self.rolagem.set_child(self.conversa)
        caixa.append(self.rolagem)
        self.boas_vindas()

        # --- Pergunta ---
        linha_entrada = Gtk.Box(spacing=8)
        self.entrada = Gtk.Entry(hexpand=True, placeholder_text="Pergunte ou descreva o problema… "
                                 "(ex: meu som não sai, como instalo o steam?)")
        self.entrada.connect("activate", self.ao_enviar)
        linha_entrada.append(self.entrada)
        self.botao_enviar = self._botao("➤ Enviar", "botao-azul", self.ao_enviar)
        linha_entrada.append(self.botao_enviar)
        caixa.append(linha_entrada)

        # --- Status ---
        caixa_status = Gtk.Box()
        caixa_status.add_css_class("caixa-status")
        self.label_status = Gtk.Label(label="⏳ Carregando…", xalign=0, hexpand=True, wrap=True)
        caixa_status.append(self.label_status)
        caixa.append(caixa_status)

        # --- Ações ---
        linha_acoes = Gtk.Box(spacing=8, homogeneous=True)
        self.botao_checkup = self._botao("🩺 Check-up geral", "botao-laranja",
                                         lambda *_: self.perguntar_agent("Check-up geral",
                                                                         checkup=True))
        linha_acoes.append(self.botao_checkup)
        linha_acoes.append(self._botao("🧹 Limpar conversa", "botao-cinza", self.ao_limpar))
        linha_acoes.append(self._botao("🚪 Fechar", "botao-cinza", lambda *_: self.close()))
        caixa.append(linha_acoes)

        self.atualizar_status()
        self.entrada.grab_focus()

    # -- tamanho da fonte ---------------------------------------------------

    def aplicar_fonte(self):
        """Aplica a escala da fonte em todas as janelas do app (CSS de maior prioridade)."""
        nome = Gtk.Settings.get_default().props.gtk_font_name or ""
        m = re.search(r"(\d+(?:\.\d+)?)\s*$", nome)
        base = float(m.group(1)) if m else 11.0
        s = self.escala
        fam = f' font-family: "{self.familia}";' if self.familia else ""
        self.css_fonte.load_from_data((
            f"window, window * {{ font-size: {base * s:.1f}pt;{fam} }}\n"
            f".titulo-app {{ font-size: {20 * s:.0f}px; }}\n"
            f".saida {{ font-size: {11 * s:.0f}px; }}\n"
            # código, comandos e saída continuam monoespaçados
            ".saida, .codigo, .monospace, .monospace text, textview.monospace, "
            "textview.monospace text { font-family: monospace; }\n"
            # a janela Aparência fica sempre na fonte do sistema (para dar para desfazer)
            f"window.aparencia, window.aparencia * {{ font-family: \"{_familia_segura(re.sub(r'[ ,]*[0-9.]+$', '', nome)) or 'sans-serif'}\"; "
            f"font-size: {base:.1f}pt; }}\n"
            "window.aparencia .titulo-app { font-size: 20px; }\n").encode("utf-8"))
        # força o GTK a remedir e redesenhar todas as janelas com a fonte nova
        # (no Hyprland a janela podia ficar meio desenhada, sem a parte de baixo)
        for w in Gtk.Window.list_toplevels():
            w.queue_resize()
            w.queue_draw()
        self.b_escala.set_label(f"{round(s * 100)}%")
        self.b_menor.set_sensitive(s > ESCALA_MIN + 0.001)
        self.b_maior.set_sensitive(s < ESCALA_MAX - 0.001)

    def ao_clicar_aparencia(self, *_):
        """Escolhe a família da fonte da interface (o tamanho fica no A− / A+).

        A escolha só aparece na frase de exemplo; a interface muda quando você salva
        (assim a janela não se desmonta enquanto você escolhe)."""
        sistema = Gtk.Settings.get_default().props.gtk_font_name or "Sans 11"
        familias = sorted({f.get_name() for f in self.get_pango_context().list_families()},
                          key=str.lower)
        opcoes = ["Padrão do sistema"] + familias
        escolha = [self.familia]

        dlg = Gtk.Window(title="Aparência", transient_for=self, modal=True,
                         default_width=560, resizable=False)
        dlg.add_css_class("aparencia")
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        titulo = Gtk.Label(label="🔤 Aparência", xalign=0)
        titulo.add_css_class("titulo-app")
        caixa.append(titulo)
        caixa.append(self._label("Fonte da interface (o tamanho continua nos botões A− / A+). "
                                 "Escolha olhando o exemplo e clique em Salvar. Código e "
                                 "comandos ficam em fonte monoespaçada.", "detalhe", False))

        lista = Gtk.DropDown.new_from_strings(opcoes)
        lista.set_enable_search(True)
        lista.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        lista.set_hexpand(True)
        lista.set_selected(opcoes.index(self.familia) if self.familia in opcoes else 0)
        linha = Gtk.Box(spacing=8)
        linha.append(Gtk.Label(label="Fonte:", xalign=0))
        linha.append(lista)
        caixa.append(linha)

        # exemplo com a fonte escolhida (só este rótulo muda)
        previa = Gtk.Label(label="Minha rede não funciona. O gateway responde, mas o DNS falha.\n"
                                 "0123456789  áéíóú çãõ  ABC abc", xalign=0, wrap=True,
                           max_width_chars=60, height_request=64, hexpand=True)
        previa.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        quadro = Gtk.Box()
        quadro.add_css_class("cartao")
        quadro.append(previa)
        caixa.append(quadro)
        info = self._label("", "detalhe", False)
        caixa.append(info)

        def ao_mudar(*_):
            i = lista.get_selected()
            fam = "" if i in (0, Gtk.INVALID_LIST_POSITION) else _familia_segura(opcoes[i])
            escolha[0] = fam
            attrs = Pango.AttrList()
            if fam:
                attrs.insert(Pango.attr_family_new(fam))
            previa.set_attributes(attrs)
            info.set_markup(f"Em uso agora: <b>{esc(self.familia or 'padrão do sistema')}</b>"
                            + ("" if self.familia else f" ({esc(sistema)})"))
        lista.connect("notify::selected", ao_mudar)
        ao_mudar()

        def salvar(*_):
            try:
                config.save_user({"gui": {"font_family": escolha[0]}})
            except OSError as e:
                self.erro("Não foi possível salvar", str(e))
                return
            self.familia = escolha[0]
            self.aplicar_fonte()
            dlg.close()

        botoes = Gtk.Box(spacing=8, homogeneous=True)
        botoes.append(self._botao("❌ Cancelar", "botao-cinza", lambda *_: dlg.close()))
        botoes.append(self._botao("💾 Salvar", "botao-verde", salvar))
        caixa.append(botoes)
        dlg.set_child(caixa)
        dlg.present()

    def mudar_fonte(self, passo):
        """passo: +1 aumenta, -1 diminui, 0 volta ao normal. Fica gravado na configuração."""
        nova = 1.0 if passo == 0 else round(self.escala + 0.1 * passo, 2)
        nova = min(ESCALA_MAX, max(ESCALA_MIN, nova))
        if nova == self.escala and passo:
            return
        self.escala = nova
        self.aplicar_fonte()
        try:
            config.save_user({"gui": {"font_scale": nova}})
        except OSError as e:
            history.log.warning("não foi possível gravar a escala da fonte: %s", e)

    # -- helpers de construção ---------------------------------------------

    def _botao(self, texto, classe, cb):
        b = Gtk.Button(label=texto)
        b.add_css_class(classe)
        b.connect("clicked", cb)
        return b

    def _label(self, markup, classe=None, selecionavel=True):
        l = Gtk.Label(xalign=0, wrap=True, selectable=selecionavel)
        l.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        l.set_markup(markup)
        if classe:
            l.add_css_class(classe)
        return l

    def adicionar(self, widget):
        self.conversa.append(widget)
        GLib.timeout_add(60, self._rolar_fim)

    def _rolar_fim(self):
        adj = self.rolagem.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def boas_vindas(self):
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c.add_css_class("cartao")
        c.add_css_class("cartao-llm")
        c.append(self._label("<b>👋 Olá! Em que posso ajudar?</b>", selecionavel=False))
        c.append(self._label(
            "Pergunte com as suas palavras: um problema (\"meu som não sai\"), uma dúvida "
            "(\"como instalo o Steam?\") ou peça um check-up. Nada é alterado sem você "
            "confirmar.", "detalhe", False))
        c.append(self._label("<small>Diagnósticos prontos (funcionam mesmo sem IA):</small>",
                             "detalhe", False))
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=7,
                            column_spacing=6, row_spacing=6)
        self._chips = []
        for dom, rotulo in tools.LABELS.items():
            b = self._botao(rotulo, "botao-chip",
                            lambda _b, d=dom, r=rotulo: self.perguntar_agent(f"Diagnosticar: {r}",
                                                                             domain=d))
            self._chips.append(b)
            chips.append(b)
        c.append(chips)
        self.conversa.append(c)
        if self.agent.provider.name == "none" and not self.cfg.get("gui", {}).get("ai_setup"):
            self.cartao_config_ia()

    def cartao_config_ia(self):
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c.add_css_class("cartao")
        c.add_css_class("cartao-aviso")
        c.append(self._label("<b>🧠 Quer ativar a inteligência artificial?</b>", selecionavel=False))
        c.append(self._label(
            "Sem IA eu faço o check-up e os diagnósticos prontos. Com IA eu respondo "
            "<b>qualquer pergunta</b> sobre o sistema, investigando a máquina de verdade. "
            "A IA local (Ollama) roda no seu computador: nada sai da máquina e funciona offline.",
            "detalhe", False))
        linha = Gtk.Box(spacing=8, homogeneous=True)
        linha.append(self._botao("🦙 IA local (recomendado)", "botao-verde",
                                 lambda *_: self.ao_clicar_ia()))
        linha.append(self._botao("🌐 Usar uma API", "botao-azul",
                                 lambda *_: self.ao_clicar_configuracoes(provider="openai")))

        def dispensar(*_):
            try:
                config.save_user({"gui": {"ai_setup": "dispensado"}})
            except OSError:
                pass
            self.cfg = config.load()
            c.set_visible(False)
        linha.append(self._botao("Agora não", "botao-cinza", dispensar))
        c.append(linha)
        self._cartao_ia = c
        self.conversa.append(c)

    # -- estado ------------------------------------------------------------

    def set_ocupado(self, ocupado):
        self.ocupado = ocupado
        if ocupado:
            self.spinner.start()
        else:
            self.spinner.stop()
        for w in (self.botao_enviar, self.botao_checkup, self.entrada, *getattr(self, "_chips", [])):
            w.set_sensitive(not ocupado)
        for w in getattr(self, "_botoes_acao", []):
            w.set_sensitive(not ocupado)

    def atualizar_status(self):
        """Rodapé: LLM, distro, init. A checagem do LLM roda numa thread."""
        self.label_status.set_markup("⏳ Verificando o LLM…")

        def trabalho():
            from .. import context
            ok, msg = self.agent.llm_status()
            ctx = context.collect(["distro", "init", "kernel"])
            GLib.idle_add(self._ao_status, ok, msg, ctx)
        threading.Thread(target=trabalho, daemon=True).start()

    def _ao_status(self, ok, msg, ctx):
        prov = self.agent.provider
        if prov.name == "none":
            llm = "<span foreground='#9ca3af'>○ sem IA (só diagnósticos prontos)</span>"
        elif ok:
            llm = f"<span foreground='#34d399' weight='bold'>✅ {esc(msg)}</span>"
        else:
            llm = f"<span foreground='#f87171'>❌ {esc(prov.describe())}: {esc(msg)}</span>"
        init = ctx.get("init", {}).get("service_manager", "?")
        partes = [f"🧠 {llm}",
                  esc(f"🐧 {ctx.get('distro', {}).get('name', '?')}"),
                  esc(f"⚙️ {init}"),
                  esc(f"🧩 kernel {ctx.get('kernel', '?')}")]
        self.label_status.set_markup("   •   ".join(partes))
        if init != "runit":
            self.label_alerta.set_markup(
                f"⚠️ Este sistema usa <b>{esc(init)}</b>, não runit. O VoidBR AI foi feito para o "
                "VoidBR: o diagnóstico funciona, mas as ações de serviço (sv) não se aplicam.")
            self.caixa_alerta.set_visible(True)
        else:
            self.caixa_alerta.set_visible(False)
        return False

    # -- diálogos (iguais ao snapper-manager-gui) ---------------------------

    def erro(self, titulo, detalhe=""):
        d = Gtk.AlertDialog(message=f"❌ {titulo}", detail=detalhe, modal=True)
        d.show(self)

    def perguntar(self, titulo, detalhe, botao_ok, callback):
        d = Gtk.AlertDialog(message=titulo, detail=detalhe, modal=True,
                            buttons=["❌ Cancelar", botao_ok],
                            cancel_button=0, default_button=0)

        def resposta(dlg, res):
            try:
                if dlg.choose_finish(res) == 1:
                    callback()
            except GLib.Error:
                pass
        d.choose(self, None, resposta)

    def mostrar_texto(self, titulo, texto):
        janela = Gtk.Window(title=titulo, transient_for=self,
                            default_width=760, default_height=520)
        tv = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                          left_margin=10, right_margin=10, top_margin=10, bottom_margin=10)
        tv.get_buffer().set_text(texto)
        rolagem = Gtk.ScrolledWindow()
        rolagem.set_child(tv)
        janela.set_child(rolagem)
        janela.present()

    # -- conversa com o Agent ------------------------------------------------

    def _ao_evento(self, ev):
        # chamado na thread do Agent -> repassa para a thread da GUI
        GLib.idle_add(self._evento_gui, ev)

    def _evento_gui(self, ev):
        if self.passos is not None:
            self.passos.evento(ev)
            GLib.timeout_add(60, self._rolar_fim)
        return False

    def ao_enviar(self, *_):
        texto = self.entrada.get_text().strip()
        if texto and not self.ocupado:
            self.entrada.set_text("")
            self.perguntar_agent(texto)

    def ao_clicar_avisos(self, *_):
        """Liga/desliga o monitor (check-up leve periódico com notificação)."""
        from .. import monitor
        m = self.cfg.get("monitor", {})
        dlg = Gtk.Window(title="Avisos em segundo plano", transient_for=self, modal=True,
                         default_width=560)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        titulo = Gtk.Label(label="🔔 Avisos em segundo plano", xalign=0)
        titulo.add_css_class("titulo-app")
        caixa.append(titulo)
        caixa.append(self._label(
            "De tempos em tempos o VoidBR AI faz um check-up leve (disco, atualizações, serviços "
            "parados, boot) e avisa com uma notificação se aparecer um problema novo. Só lê o "
            "sistema: nada é alterado sem você. A busca por atualizações consulta os "
            "repositórios (internet).", "detalhe", False))
        grade = Gtk.Grid(column_spacing=12, row_spacing=10)
        ligado = Gtk.Switch(active=bool(m.get("enabled")), halign=Gtk.Align.START)
        grade.attach(Gtk.Label(label="Ativar os avisos:", xalign=0), 0, 0, 1, 1)
        grade.attach(ligado, 1, 0, 1, 1)
        horas = Gtk.SpinButton.new_with_range(1, 48, 1)
        horas.set_value(float(m.get("interval_hours", 6)))
        grade.attach(Gtk.Label(label="Checar a cada (horas):", xalign=0), 0, 1, 1, 1)
        grade.attach(horas, 1, 1, 1, 1)
        caixa.append(grade)
        desk = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
        if "hyprland" in desk or not shutil.which("notify-send"):
            nota = []
            if "hyprland" in desk:
                nota.append("No Hyprland, para iniciar junto com a sessão, adicione ao "
                            "<tt>~/.config/hypr/hyprland.conf</tt>:\n<tt>exec-once = voidbr-ai --monitor</tt>")
            if not shutil.which("notify-send"):
                nota.append("⚠️ Falta o <tt>notify-send</tt> (pacote <b>libnotify</b>) e um serviço de "
                            "notificações (mako, dunst, swaync…).")
            caixa.append(self._label("\n\n".join(nota), "detalhe"))
        resultado = self._label("", "detalhe")
        caixa.append(resultado)

        def testar(b):
            b.set_sensitive(False)
            resultado.set_markup("⏳ Checando…")

            def trabalho():
                ag = Agent(self.cfg)
                try:
                    novos = monitor.uma_vez(ag, forcar=True)
                    msg = (f"✅ {len(novos)} problema(s) — veja a notificação." if novos
                           else "✅ Nenhum problema agora (nenhuma notificação).")
                except Exception as e:
                    msg = f"❌ {e}"
                GLib.idle_add(lambda: (resultado.set_markup(esc(msg)), b.set_sensitive(True)) and False)
            threading.Thread(target=trabalho, daemon=True).start()

        def salvar(*_):
            on = ligado.get_active()
            try:
                config.save_user({"monitor": {"enabled": on, "interval_hours": int(horas.get_value())}})
                monitor.autostart(on)
                if on:
                    monitor.parar()     # reinicia com o intervalo novo
                    monitor.iniciar()
                else:
                    monitor.parar()
            except OSError as e:
                self.erro("Não foi possível salvar", str(e))
                return
            self.cfg = config.load()
            dlg.close()

        linha = Gtk.Box(spacing=8, homogeneous=True)
        linha.append(self._botao("🧪 Checar agora", "botao-azul", testar))
        linha.append(self._botao("❌ Cancelar", "botao-cinza", lambda *_: dlg.close()))
        linha.append(self._botao("💾 Salvar", "botao-verde", salvar))
        caixa.append(linha)
        dlg.set_child(caixa)
        dlg.present()

    def ao_clicar_explicar(self, *_):
        """Cola um comando ou uma mensagem de erro: explica sem executar nada."""
        if self.ocupado:
            return
        dlg = Gtk.Window(title="Explicar comando ou erro", transient_for=self, modal=True,
                         default_width=640, default_height=360)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                        margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        caixa.append(self._label("📋 Cole um <b>comando</b> (ex: achado num fórum) ou uma "
                                 "<b>mensagem de erro</b>. Nada é executado: o VoidBR AI só lê, "
                                 "explica e avisa se é perigoso.", "detalhe", False))
        tv = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=8,
                          right_margin=8, top_margin=8, bottom_margin=8)
        rol = Gtk.ScrolledWindow(vexpand=True)
        rol.set_child(tv)
        rol.add_css_class("cartao")
        caixa.append(rol)
        linha = Gtk.Box(spacing=8, homogeneous=True)
        linha.append(self._botao("❌ Cancelar", "botao-cinza", lambda *_: dlg.close()))

        def ir(*_):
            buf = tv.get_buffer()
            texto = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            if texto:
                dlg.close()
                self.perguntar_agent(texto, explicar=True)
        linha.append(self._botao("🔍 Explicar", "botao-azul", ir))
        caixa.append(linha)
        dlg.set_child(caixa)
        dlg.present()
        tv.grab_focus()

    def perguntar_agent(self, texto, domain=None, checkup=False, explicar=False):
        bolha = Gtk.Box(halign=Gtk.Align.END)
        bolha.add_css_class("bolha-usuario")
        bolha.append(self._label(f"🧑 {esc(texto)}"))
        self.adicionar(bolha)

        self.passos = CartaoPassos("🩺 Check-up do sistema" if checkup else
                                   "🔍 Analisando (nada é executado)" if explicar else
                                   "🔎 Investigando a máquina")
        self.adicionar(self.passos)
        self.set_ocupado(True)
        self.agent.on_event = self._ao_evento

        def trabalho():
            try:
                if explicar:
                    rep = self.agent.explain(texto)
                elif checkup:
                    rep = self.agent.checkup()
                elif domain:
                    rep = self.agent.diagnose(domain, question=texto)
                else:
                    rep = self.agent.ask(texto)
                GLib.idle_add(self._ao_relatorio, rep, None)
            except Exception as e:  # nunca deixa a GUI travada em "ocupado"
                GLib.idle_add(self._ao_relatorio, None, e)
        threading.Thread(target=trabalho, daemon=True).start()

    def _ao_relatorio(self, rep, falha):
        self.set_ocupado(False)
        if falha is not None:
            self.erro("O diagnóstico falhou", str(falha))
            return False
        if rep.streamed and self.passos is not None:
            self.passos.remover_fluxo()
        if rep.mode == "llm":
            self.cartao_ia(rep)
        elif not rep.domain:
            self.cartao_resposta(rep)
        else:
            self.cartao_diagnostico(rep, "🩺 Check-up geral" if rep.mode == "checkup" else
                                    "📖 O que o sistema sabe" if rep.domain == "info" else
                                    "🔍 Análise (nada foi executado)" if rep.domain == "explain" else
                                    "🩺 Diagnóstico")
        if rep.needs_ai:
            self.dica_ia()
        return False

    def dica_ia(self):
        linha = Gtk.Box(spacing=10)
        linha.add_css_class("caixa-status")
        linha.append(self._label("💡 Com a IA configurada eu respondo perguntas livres, sob medida.",
                                 "detalhe", False))
        linha.get_first_child().set_hexpand(True)
        linha.append(self._botao("🧠 Configurar IA", "botao-azul", lambda *_: self.ao_clicar_ia()))
        self.adicionar(linha)

    def cartao_resposta(self, rep):
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        c.add_css_class("cartao")
        c.add_css_class("cartao-llm")
        quem = f"🤖 {esc(rep.provider)}" if rep.llm else "🤖 VoidBR AI"
        c.append(self._label(f"<b>{quem}</b>"))
        c.append(self._label(esc(rep.summary)))
        for s in (rep.llm or {}).get("sugestoes", []):
            c.append(self._label(f"→ {esc(s)}", "detalhe"))
        if rep.llm_error and not rep.llm:
            c.append(self._label(f"<small>{esc(rep.llm_error)}</small>", "detalhe"))
        self.adicionar(c)

    def cartao_ia(self, rep):
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c.add_css_class("cartao")
        c.add_css_class("cartao-erro" if rep.llm_error and not rep.llm else "cartao-llm")
        l = rep.llm or {}
        c.append(self._label(f"<span weight='bold'>🤖 {esc(rep.provider)}</span>  <span "
                             f"foreground='#9ca3af'><small>{len(rep.tool_calls)} consulta(s) ao "
                             "sistema</small></span>", selecionavel=False))
        if rep.streamed or "\n" in rep.summary or len(rep.summary) > 240:
            # resposta direta/script: texto normal, código em monoespaçado
            for parte in texto_com_codigo(rep.summary):
                c.append(self._label(parte, "codigo" if parte.startswith("<tt>") else None))
        else:
            c.append(self._label(f"<span size='large' weight='bold'>{esc(rep.summary)}</span>"))
        if l.get("explicacao"):
            c.append(self._label(esc(l["explicacao"])))
        fatos = [f for f in rep.findings if f.get("confirmed", True)]
        hips = [f for f in rep.findings if not f.get("confirmed", True)]
        if fatos:
            c.append(self._label("<b>🔍 Análise automática (nada foi executado)</b>"
                                 if rep.domain == "explain" else
                                 "<b>🔎 Encontrado nos dados da máquina</b>", "subtitulo"))
            for f in fatos:
                c.append(self._label(f"•  {esc(f['title'])}"))
        if hips:
            c.append(self._label("<b>🤔 Hipóteses (não confirmadas)</b>", "subtitulo"))
            for f in hips:
                c.append(self._label(f"?  {esc(f['title'])}", "hipotese"))
        if l.get("sugestoes"):
            c.append(self._label("<b>📝 Você também pode</b>", "subtitulo"))
            for x in l["sugestoes"]:
                c.append(self._label(f"→  <tt>{esc(x)}</tt>", "detalhe"))
        if rep.llm_error and not l:
            c.append(self._label(esc(rep.llm_error), "detalhe"))
        self._acoes(c, rep)
        if l.get("ignoradas"):
            c.append(self._label(f"<small>🛡️ {len(l['ignoradas'])} sugestão(ões) da IA fora da lista "
                                 "permitida foram descartadas.</small>", "detalhe", False))
        self._detalhes(c, rep)
        self.adicionar(c)

    def _acoes(self, c, rep):
        self._botoes_acao = getattr(self, "_botoes_acao", [])
        rep._botoes = []
        if not rep.actions:
            return
        c.append(self._label("<b>🛠️ Correções propostas</b>", "subtitulo"))
        for a in rep.actions:
            linha = Gtk.Box(spacing=10)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
            motivo = a.reason or ("sugerida pela IA" if a.source == "llm" else "")
            col.append(self._label(f"<b>{esc(a.title)}</b>  "
                                   f"<span foreground='#9ca3af'>({esc(motivo)})</span>"))
            cmd = self._label(esc(a.command), "comando")
            cmd.set_halign(Gtk.Align.START)
            col.append(cmd)
            if a.risk:
                col.append(self._label(f"<span foreground='#fbbf24'>⚠️ {esc(a.risk)}</span>"))
            linha.append(col)
            b = self._botao("▶ Executar", "botao-verde",
                            lambda _b, a=a: self.ao_clicar_executar(rep, a))
            b.set_valign(Gtk.Align.CENTER)
            b.acao_id = a.id
            self._botoes_acao.append(b)
            rep._botoes.append(b)
            linha.append(b)
            c.append(linha)

    def _detalhes(self, c, rep):
        linha = Gtk.Box(spacing=8, halign=Gtk.Align.START)
        linha.append(self._botao("🔍 Ver detalhes", "botao-laranja",
                                 lambda *_: self.mostrar_texto(
                                     "🔍 Dados coletados",
                                     json.dumps(rep.to_dict(), ensure_ascii=False, indent=2,
                                                default=str))))
        linha.append(self._botao("📤 Relatório", "botao-cinza", lambda *_: self.exportar(rep)))
        c.append(linha)

    def exportar(self, rep):
        """Relatório em Markdown para colar num fórum/grupo (dados pessoais ocultos)."""
        texto = self.agent.report_markdown(rep)
        dlg = Gtk.Window(title="Relatório para compartilhar", transient_for=self,
                         default_width=760, default_height=560)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                        margin_top=14, margin_bottom=14, margin_start=14, margin_end=14)
        caixa.append(self._label("📤 Pronto para colar num fórum, grupo ou issue. IP público, MAC, "
                                 "nome da rede Wi-Fi, do usuário e da máquina foram ocultados. "
                                 "Confira antes de enviar.", "detalhe", False))
        tv = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=8,
                          right_margin=8, top_margin=8, bottom_margin=8)
        tv.get_buffer().set_text(texto)
        rol = Gtk.ScrolledWindow(vexpand=True)
        rol.set_child(tv)
        caixa.append(rol)
        aviso = self._label("", "detalhe", False)
        caixa.append(aviso)

        def atual():
            b = tv.get_buffer()
            return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

        def copiar(*_):
            self.get_clipboard().set(atual())
            aviso.set_markup("✅ Copiado para a área de transferência.")

        def salvar(*_):
            fd = Gtk.FileDialog(title="Salvar relatório",
                                initial_name=f"voidbr-ai-relatorio-{time.strftime('%Y%m%d-%H%M%S')}.md")

            def fim(d, res):
                try:
                    arq = d.save_finish(res)
                except GLib.Error:
                    return          # cancelado
                try:
                    with open(arq.get_path(), "w", encoding="utf-8") as f:
                        f.write(atual())
                    aviso.set_markup(f"✅ Salvo em {esc(arq.get_path())}")
                except OSError as e:
                    aviso.set_markup(f"❌ {esc(str(e))}")
            fd.save(dlg, None, fim)

        linha = Gtk.Box(spacing=8, homogeneous=True)
        linha.append(self._botao("❌ Fechar", "botao-cinza", lambda *_: dlg.close()))
        linha.append(self._botao("💾 Salvar…", "botao-azul", salvar))
        linha.append(self._botao("📋 Copiar", "botao-verde", copiar))
        caixa.append(linha)
        dlg.set_child(caixa)
        dlg.present()

    def cartao_diagnostico(self, rep, titulo="🩺 Diagnóstico"):
        sev = {f["severity"] for f in rep.findings}
        classe = "cartao-erro" if "erro" in sev else "cartao-aviso" if "aviso" in sev else "cartao-ok"
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c.add_css_class("cartao")
        c.add_css_class(classe)
        c.append(self._label(f"<span size='large' weight='bold'>{titulo}</span>"))
        c.append(self._label(f"<b>{esc(rep.summary)}</b>"))

        # o que foi encontrado: fatos confirmados pelos dados
        confirmados = [f for f in rep.findings if f.get("confirmed", True)]
        hipoteses = [f for f in rep.findings if not f.get("confirmed", True)]
        if confirmados:
            c.append(self._label("<b>🔎 Encontrado (confirmado pelos dados)</b>", "subtitulo"))
            for f in confirmados:
                self._achado(c, f, grupo=rep.mode == "checkup")

        # hipóteses: das regras e do LLM
        hip_llm = (rep.llm or {}).get("hipoteses", [])
        if hipoteses or hip_llm:
            c.append(self._label("<b>🤔 Hipóteses (não confirmadas)</b>", "subtitulo"))
            for f in hipoteses:
                self._achado(c, f, hipotese=True)
            for h in hip_llm:
                c.append(self._label(f"?  {esc(h)}", "hipotese"))

        # interpretação do LLM
        if rep.llm:
            l = rep.llm
            c.append(self._label(f"<b>🤖 Interpretação ({esc(rep.provider)})</b>", "subtitulo"))
            if l.get("diagnostico"):
                c.append(self._label(esc(l["diagnostico"])))
            if l.get("explicacao"):
                c.append(self._label(esc(l["explicacao"]), "detalhe"))
            for s in l.get("sugestoes", []):
                c.append(self._label(f"→ {esc(s)}", "detalhe"))
        elif rep.llm_error:
            c.append(self._label(f"<small>🤖 IA: {esc(rep.llm_error)} — diagnóstico feito só "
                                 "pelas regras.</small>", "detalhe"))

        self._acoes(c, rep)
        self._detalhes(c, rep)
        self.adicionar(c)

    def _achado(self, caixa, f, hipotese=False, grupo=False):
        icone = "🤔" if hipotese else ICONE_ACHADO.get(f["severity"], "•")
        dom = f"<span foreground='#7dd3fc'>{esc(tools.LABELS.get(f.get('domain'), ''))}</span>  " \
            if grupo and f.get("domain") else ""
        caixa.append(self._label(f"{icone}  {dom}<b>{esc(f['title'])}</b>"))
        if f.get("detail"):
            caixa.append(self._label(f"      {esc(f['detail'])}", "detalhe"))
        for s in f.get("suggestions", []):
            caixa.append(self._label(f"      → <tt>{esc(s)}</tt>", "detalhe"))

    # -- ações -------------------------------------------------------------

    def ao_clicar_executar(self, rep, acao):
        if self.ocupado:
            return
        como = "como root (pkexec)" if acao.root else "como o seu usuário"
        risco = f"\n\n⚠️ {acao.risk}" if acao.risk else ""
        origem = "\n\n🤖 Proposta pela IA (validada na lista de ações permitidas)." \
            if acao.source == "llm" else ""
        self.perguntar(f"🛠️ {acao.title}?",
                       f"Será executado {como}:\n\n    {acao.command}\n\n"
                       f"Motivo: {acao.reason or '-'}{risco}{origem}\n\nDepois o VoidBR AI "
                       "verifica se deu certo.",
                       "▶ Executar", lambda: self.executar(rep, acao))

    def executar(self, rep, acao):
        self._rep_exec = rep
        self.passos = CartaoPassos(f"🛠️ {acao.title}")
        self.adicionar(self.passos)
        self.set_ocupado(True)
        self.agent.on_event = self._ao_evento

        def trabalho():
            try:
                r = self.agent.execute(acao, rep, confirmed=True)
                GLib.idle_add(self._ao_executar, r, None)
            except Exception as e:
                GLib.idle_add(self._ao_executar, None, e)
        threading.Thread(target=trabalho, daemon=True).start()

    def _ao_executar(self, r, falha):
        self.set_ocupado(False)
        if falha is not None:
            self.erro("Falha ao executar", str(falha))
            return False
        if r.cancelled:
            return False
        # a ação executada (ou todas, se resolveu) não fica mais disponível naquele cartão
        for b in getattr(self._rep_exec, "_botoes", []):
            if r.resolved or b.acao_id == r.action.id:
                b.set_sensitive(False)
                if b in self._botoes_acao:
                    self._botoes_acao.remove(b)
        if r.snapshot:
            self.cartao_snapshot(r.snapshot)
        if not r.ok:
            self.erro("O comando falhou", r.output or "sem saída")
            return False
        if r.after is not None:
            titulo = "✅ Verificação: resolvido" if r.resolved else "❌ Verificação: o problema continua"
            self.cartao_diagnostico(r.after, titulo)
        elif r.check:
            linha = Gtk.Box()
            linha.add_css_class("cartao")
            linha.add_css_class("cartao-ok" if r.resolved else "cartao-aviso")
            icone = "✅" if r.resolved else ("❌" if r.resolved is False else "ℹ️")
            linha.append(self._label(f"{icone}  <b>{esc(r.check)}</b>"))
            self.adicionar(linha)
        return False

    def cartao_snapshot(self, num):
        """Snapshot criado antes da ação: oferece desfazer pelo voidbr-snapper-manager."""
        c = Gtk.Box(spacing=12)
        c.add_css_class("cartao")
        c.append(self._label(f"📸  <b>Snapshot {num}</b> do sistema criado antes da mudança.\n"
                             "<small>Se algo der errado, dá para voltar a como estava.</small>"))
        b = self._botao("↩️ Desfazer…", "botao-laranja", lambda *_: self.desfazer(num))
        b.set_valign(Gtk.Align.CENTER)
        b.set_hexpand(False)
        c.append(b)
        self.adicionar(c)

    def desfazer(self, num):
        gui = shutil.which("voidbr-snapper-manager-gui")
        texto = (f"Para voltar o sistema ao snapshot {num}, restaure-o no Gerenciador de "
                 "snapshots. A restauração troca o sistema inteiro pelo do snapshot e pede "
                 "reinício; o que foi alterado no / depois dele se perde (a /home não muda).")
        if gui:
            self.perguntar("↩️ Desfazer a mudança?", texto + "\n\nAbrir o Gerenciador de snapshots?",
                           "📸 Abrir", lambda: subprocess.Popen([gui], start_new_session=True))
        else:
            self.mostrar_texto("↩️ Desfazer a mudança",
                               texto + f"\n\nNo terminal:\n\n    sudo voidbr-snapper-manager restore {num}\n")

    def ao_limpar(self, *_):
        if self.ocupado:
            return
        filho = self.conversa.get_first_child()
        while filho:
            prox = filho.get_next_sibling()
            self.conversa.remove(filho)
            filho = prox
        self._botoes_acao = []
        self.agent.reset()
        self.boas_vindas()

    # -- menu ----------------------------------------------------------------

    def ao_clicar_historico(self, *_):
        """Sessões anteriores: abrir (ver, exportar e continuar a conversa)."""
        itens = history.list_sessions(200)
        if not itens:
            self.erro("Nenhuma sessão no histórico ainda")
            return
        dlg = Gtk.Window(title="Histórico", transient_for=self, modal=True,
                         default_width=720, default_height=560)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                        margin_top=14, margin_bottom=14, margin_start=14, margin_end=14)
        titulo = Gtk.Label(label="🗂️ Histórico", xalign=0)
        titulo.add_css_class("titulo-app")
        caixa.append(titulo)
        busca = Gtk.SearchEntry(placeholder_text="Filtrar…")
        caixa.append(busca)
        lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        lista.add_css_class("cartao")
        for s in itens:
            row = Gtk.ListBoxRow()
            row.path = s["path"]
            row.texto = f"{s['question']} {s['summary']}".lower()
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6,
                        margin_bottom=6, margin_start=6, margin_end=6)
            b.append(self._label(f"<small>{esc(s['time'])}</small>  <b>{esc(s['question'][:90])}</b>",
                                 selecionavel=False))
            b.append(self._label(f"<small>→ {esc(s['summary'][:140])}</small>", "detalhe", False))
            row.set_child(b)
            lista.append(row)
        lista.set_filter_func(lambda r: busca.get_text().lower() in r.texto)
        busca.connect("search-changed", lambda *_: lista.invalidate_filter())
        rol = Gtk.ScrolledWindow(vexpand=True)
        rol.set_child(lista)
        caixa.append(rol)

        def abrir(*_):
            row = lista.get_selected_row()
            if row is None:
                return
            try:
                rep = self.agent.load_session(row.path)
            except (OSError, ValueError) as e:
                self.erro("Não foi possível abrir a sessão", str(e))
                return
            dlg.close()
            aviso = Gtk.Box()
            aviso.add_css_class("cartao")
            aviso.append(self._label(f"🗂️ <b>Sessão de {esc(rep.time)}</b> reaberta do histórico. "
                                     "<small>Pode continuar a conversa; as correções foram "
                                     "conferidas de novo.</small>"))
            self.adicionar(aviso)
            self._ao_relatorio(rep, None)
        lista.connect("row-activated", abrir)
        linha = Gtk.Box(spacing=8, homogeneous=True)
        linha.append(self._botao("❌ Fechar", "botao-cinza", lambda *_: dlg.close()))
        linha.append(self._botao("📂 Abrir", "botao-azul", abrir))
        caixa.append(linha)
        dlg.set_child(caixa)
        dlg.present()

    def ao_clicar_ferramentas(self, *_):
        reg = self.agent.registry
        linhas = []
        for t in sorted(reg.list(), key=lambda t: (t.kind, t.name)):
            tipo = "AÇÃO    " if t.kind == "action" else "leitura "
            off = "  (desativada)" if t.name in reg.disabled else ""
            linhas.append(f"{tipo} {t.name}{off}\n          {t.description}")
        self.mostrar_texto("🧰 Ferramentas (Tool Registry)",
                           "Ações só rodam com a sua confirmação, via pkexec.\n\n" + "\n".join(linhas))

    def ao_clicar_configuracoes(self, *_, provider=None):
        """Configurações da IA. Grava em ~/.config/voidbr-ai/config.toml; a chave
        da API vai para um arquivo à parte (chmod 600), nunca para o .toml."""
        from .. import providers
        cfg = self.cfg
        oc, ac = cfg["ollama"], cfg["openai"]
        dlg = Gtk.Window(title="Configurações da IA", transient_for=self, modal=True,
                         default_width=620)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        titulo = Gtk.Label(label="🧠 Inteligência artificial", xalign=0)
        titulo.add_css_class("titulo-app")
        caixa.append(titulo)
        caixa.append(self._label(
            "A IA é opcional: sem ela o check-up e os diagnósticos prontos continuam "
            "funcionando. <b>Ollama</b> roda na sua máquina (nada sai dela). <b>Gemini</b> e "
            "<b>OpenAI</b> rodam na internet e precisam de uma chave da API.", "detalhe", False))

        def grade_nova():
            g = Gtk.Grid(column_spacing=12, row_spacing=8)
            g.linha = 0
            return g

        def campo(g, rotulo, widget, extra=None):
            g.attach(Gtk.Label(label=rotulo, xalign=0), 0, g.linha, 1, 1)
            widget.set_hexpand(True)
            g.attach(widget, 1, g.linha, 1 if extra else 2, 1)
            if extra:
                g.attach(extra, 2, g.linha, 1, 1)
            g.linha += 1
            return widget

        def grupo(titulo_grupo, g):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.add_css_class("cartao")
            rot = Gtk.Label(label=titulo_grupo, xalign=0)
            rot.add_css_class("subtitulo")
            box.append(rot)
            box.append(g)
            caixa.append(box)
            return box

        # provider -------------------------------------------------------------
        g0 = grade_nova()
        codigos = [c for _, c in PROVIDERS]
        lista = campo(g0, "Usar:", Gtk.DropDown.new_from_strings([r for r, _ in PROVIDERS]))
        atual = provider or cfg.get("provider", "none")
        if atual == "openai" and "generativelanguage.googleapis.com" in ac.get("url", ""):
            atual = "gemini"
        lista.set_selected(codigos.index(atual) if atual in codigos else 0)
        caixa.append(g0)

        # Ollama ---------------------------------------------------------------
        g1 = grade_nova()
        o_url = campo(g1, "Endereço:", Gtk.Entry(text=oc.get("url", "")))
        o_mod = Gtk.Entry(text=oc.get("model", ""))
        o_buscar = Gtk.Button(label="🔄 Buscar modelos")
        o_buscar.add_css_class("botao-cinza")
        campo(g1, "Modelo:", o_mod, o_buscar)
        o_lista = Gtk.DropDown()
        o_lista.set_visible(False)
        campo(g1, "", o_lista)
        o_ctx = campo(g1, "Contexto (tokens):", Gtk.SpinButton.new_with_range(2048, 131072, 1024))
        o_ctx.set_value(int(oc.get("num_ctx", 8192)))
        o_keep = campo(g1, "Manter carregado:", Gtk.Entry(text=str(oc.get("keep_alive", "30m")),
                                                          placeholder_text="ex: 30m, 2h, -1 = sempre"))
        o_think = Gtk.Switch(active=bool(oc.get("think", False)), halign=Gtk.Align.START)
        campo(g1, "Modo pensando:", o_think)
        g1.attach(self._label("<small>Contexto maior usa mais memória. Modo pensando deixa o "
                              "qwen3 bem mais lento.</small>", "detalhe", False), 0, g1.linha, 3, 1)
        box_ollama = grupo("🦙 Ollama", g1)

        # API (Gemini / OpenAI) ------------------------------------------------
        g2 = grade_nova()
        a_url = campo(g2, "Endereço:", Gtk.Entry(text=ac.get("url", "")))
        a_mod = Gtk.Entry(text=ac.get("model", ""))
        a_buscar = Gtk.Button(label="🔄 Buscar modelos")
        a_buscar.add_css_class("botao-cinza")
        campo(g2, "Modelo:", a_mod, a_buscar)
        a_lista = Gtk.DropDown()
        a_lista.set_visible(False)
        campo(g2, "", a_lista)
        a_chave = campo(g2, "Chave da API:", Gtk.PasswordEntry(show_peek_icon=True))
        a_ajuda = self._label("", "detalhe", False)
        g2.attach(a_ajuda, 0, g2.linha, 3, 1)
        box_api = grupo("🌐 API na internet", g2)

        resultado = self._label("", "detalhe")
        caixa.append(resultado)

        def arquivo_chave(p):
            return os.path.join(config.user_config_dir(), f"{'gemini' if p == 'gemini' else 'openai'}.key")

        def ao_mudar(*_):
            p = codigos[lista.get_selected()]
            box_ollama.set_visible(p in ("ollama", "auto"))
            box_api.set_visible(p in ("gemini", "openai"))
            if p == "gemini":
                if not a_url.get_text().startswith(GEMINI_URL):
                    a_url.set_text(GEMINI_URL)
                a_ajuda.set_markup("<small>Chave gratuita em <b>aistudio.google.com</b> → Get API key. "
                                   "No plano grátis o Google pode usar os dados enviados para "
                                   "melhorar os produtos dele.</small>")
            elif p == "openai":
                if a_url.get_text().startswith(GEMINI_URL) or not a_url.get_text().strip():
                    a_url.set_text(OPENAI_URL)
                a_ajuda.set_markup("<small>Serve para qualquer API compatível (OpenAI, OpenRouter, "
                                   "llama.cpp, LM Studio…): troque o endereço.</small>")
            if p in ("gemini", "openai"):
                env = ac.get("api_key_env") or "OPENAI_API_KEY"
                tem = os.path.isfile(arquivo_chave(p)) or (p == "openai" and os.environ.get(env))
                a_chave.set_property("placeholder-text",
                                     "(já configurada — deixe vazio para manter)" if tem
                                     else "cole a chave aqui")
            resultado.set_text("")
        lista.connect("notify::selected", ao_mudar)
        ao_mudar()

        def formulario():
            """(mudanças para o config.toml, cfg completo para testar agora)"""
            p = codigos[lista.get_selected()]
            real = "openai" if p == "gemini" else p
            m = {"provider": real,
                 "gui": {"ai_setup": "feito" if real != "none" else cfg.get("gui", {}).get("ai_setup", "")},
                 "ollama": {"url": o_url.get_text().strip(), "model": o_mod.get_text().strip(),
                            "num_ctx": int(o_ctx.get_value()),
                            "keep_alive": o_keep.get_text().strip() or "30m",
                            "think": o_think.get_active()},
                 "openai": {"url": a_url.get_text().strip(), "model": a_mod.get_text().strip()}}
            if p in ("gemini", "openai"):
                arq = arquivo_chave(p)
                # cada serviço tem o seu arquivo de chave (a do Gemini não vai para a OpenAI)
                m["openai"]["api_key_file"] = arq if (a_chave.get_text().strip() or
                                                     os.path.isfile(arq)) else ""
            teste = json.loads(json.dumps(cfg))
            for k, v in m.items():
                if isinstance(v, dict):
                    teste.setdefault(k, {}).update(v)
                else:
                    teste[k] = v
            if a_chave.get_text().strip():
                teste["openai"]["_api_key"] = a_chave.get_text().strip()   # só na memória
            return m, teste

        def em_thread(botao, fn, fim):
            botao.set_sensitive(False)

            def trabalho():
                try:
                    r, erro = fn(), None
                except providers.ProviderError as e:
                    r, erro = None, str(e)
                except Exception as e:  # nunca trava o diálogo
                    r, erro = None, str(e)
                GLib.idle_add(lambda: (botao.set_sensitive(True), fim(r, erro)) and False)
            threading.Thread(target=trabalho, daemon=True).start()

        def buscar(entrada, drop, botao, qual):
            def fn():
                _m, teste = formulario()
                teste["provider"] = qual
                prov = providers.get_provider(teste)
                if prov.name == "none":
                    raise providers.ProviderError(prov.cfg.get("_motivo") or "Ollama não responde")
                return prov.list_models()

            def fim(nomes, erro):
                if erro:
                    resultado.set_markup(f"❌ {esc(erro)}")
                    return
                if not nomes:
                    resultado.set_markup("⚠️ Nenhum modelo disponível.")
                    return
                atual_m = entrada.get_text().strip()
                drop.set_model(Gtk.StringList.new(["— escolha um modelo —", *nomes]))
                drop.set_selected(nomes.index(atual_m) + 1 if atual_m in nomes else 0)
                entrada.set_text(atual_m)
                drop.set_visible(True)
                resultado.set_markup(f"✅ {len(nomes)} modelo(s) — escolha na lista.")

            def ao_escolher(d, *_):
                item = d.get_selected_item()
                if item is not None and d.get_selected() > 0:
                    entrada.set_text(item.get_string())
            if not getattr(drop, "_ligado", False):
                drop.connect("notify::selected", ao_escolher)
                drop._ligado = True
            resultado.set_markup("⏳ Buscando modelos…")
            em_thread(botao, fn, fim)

        o_buscar.connect("clicked", lambda b: buscar(o_mod, o_lista, b, "ollama"))
        a_buscar.connect("clicked", lambda b: buscar(a_mod, a_lista, b, "openai"))

        linha_b = Gtk.Box(spacing=8, homogeneous=True)
        testar = Gtk.Button(label="🧪 Testar")
        testar.add_css_class("botao-azul")
        linha_b.append(testar)
        linha_b.append(self._botao("❌ Cancelar", "botao-cinza", lambda *_: dlg.close()))
        salvar = Gtk.Button(label="💾 Salvar")
        salvar.add_css_class("botao-verde")
        linha_b.append(salvar)
        caixa.append(linha_b)

        rolagem = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                     propagate_natural_height=True, max_content_height=700)
        rolagem.set_child(caixa)
        dlg.set_child(rolagem)

        def ao_testar(b):
            def fn():
                _m, teste = formulario()
                prov = providers.get_provider(teste)
                ok, msg = prov.available() if prov.name != "none" else \
                    (False, prov.cfg.get("_motivo") or "nenhuma IA escolhida")
                if not ok:
                    raise providers.ProviderError(msg)
                inicio = time.monotonic()
                texto = prov.answer([{"role": "user", "content":
                                      "Responda só com a palavra: funcionando"}])
                return prov.describe(), time.monotonic() - inicio, texto.strip()[:80]

            def fim(r, erro):
                if erro:
                    resultado.set_markup(f"❌ {esc(erro)}")
                else:
                    resultado.set_markup(f"✅ {esc(r[0])} respondeu em {r[1]:.1f} s: "
                                         f"<i>{esc(r[2])}</i>")
            resultado.set_markup("⏳ Testando… (com IA local na CPU pode levar um tempo)")
            em_thread(b, fn, fim)
        testar.connect("clicked", ao_testar)

        def ao_salvar(*_):
            p = codigos[lista.get_selected()]
            mudancas, _t = formulario()
            chave = a_chave.get_text().strip()
            try:
                if chave and p in ("gemini", "openai"):
                    arq = arquivo_chave(p)
                    os.makedirs(os.path.dirname(arq), exist_ok=True)
                    fd = os.open(arq, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(chave + "\n")
                    os.chmod(arq, 0o600)
                path = config.save_user(mudancas)
            except OSError as e:
                self.erro("Não foi possível salvar", str(e))
                return
            dlg.close()
            self.cfg = config.load()
            self.agent = Agent(self.cfg)
            self.atualizar_status()
            if getattr(self, "_cartao_ia", None) and self.agent.provider.name != "none":
                self._cartao_ia.set_visible(False)
            history.log.info("configuração salva em %s", path)
        salvar.connect("clicked", ao_salvar)
        dlg.present()

    def ao_clicar_ia(self, *_):
        if self.ocupado:
            return
        hw = setup.hardware()
        sugerido = setup.recommend(hw)
        dlg = Gtk.Window(title="IA local", transient_for=self, modal=True, default_width=620)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        titulo = Gtk.Label(label="🦙 IA local com o Ollama", xalign=0)
        titulo.add_css_class("titulo-app")
        caixa.append(titulo)
        caixa.append(self._label(
            "O modelo roda no seu computador: nada sai da máquina e funciona sem internet "
            "(só o download inicial precisa dela).", "detalhe", False))
        gpu = ", ".join(hw["gpus"]) or "não identificada"
        caixa.append(self._label(
            f"💾 Memória: <b>{setup.gb(hw['ram_gb'])} GB</b>    📀 Disco livre: <b>{setup.gb(hw['free_disk_gb'])} GB</b>\n"
            f"🎮 Vídeo: {esc(gpu)}", selecionavel=False))

        rotulos = [f"{tag}  —  ~{setup.gb(tam)} GB  —  {desc}" + ("   ⭐ sugerido" if tag == sugerido else "")
                   for tag, tam, _r, desc in setup.MODELOS]
        lista = Gtk.DropDown.new_from_strings(rotulos)
        lista.set_selected([m[0] for m in setup.MODELOS].index(sugerido))
        caixa.append(Gtk.Label(label="🧠 Modelo:", xalign=0))
        caixa.append(lista)

        passos_lbl = self._label("⏳ Verificando o que já está instalado…", "detalhe", False)
        caixa.append(passos_lbl)
        linha = Gtk.Box(spacing=8, homogeneous=True)
        linha.append(self._botao("❌ Cancelar", "botao-cinza", lambda *_: dlg.close()))
        ir = Gtk.Button(label="⬇️ Instalar e configurar")
        ir.add_css_class("botao-verde")
        ir.set_sensitive(False)
        linha.append(ir)
        caixa.append(linha)
        dlg.set_child(caixa)
        estado = {}

        def montar(*_):
            if not estado:
                return
            modelo = setup.MODELOS[lista.get_selected()][0]
            passos = setup.plan(estado, modelo, hw)
            txt = ["<b>Será feito:</b>"]
            for _t, desc, cmd in passos:
                txt.append(f"•  {esc(desc)}" + (f"\n      <tt>{esc(cmd)}</tt>" if cmd else ""))
            if any(t in ("install", "service", "restart") for t, _d, _c in passos):
                txt.append("\n🔐 A instalação pede a sua senha (pkexec).")
            tam = setup.model_info(modelo)[1]
            if tam and hw["free_disk_gb"] and tam * 1.2 > hw["free_disk_gb"]:
                txt.append(f"\n⚠️ Pouco espaço: o modelo ocupa ~{setup.gb(tam)} GB.")
            passos_lbl.set_markup("\n".join(txt))
            ir.set_sensitive(True)

        def ler_estado():
            e = setup.state(self.cfg)
            GLib.idle_add(lambda: (estado.update(e), montar(), False)[2])
        threading.Thread(target=ler_estado, daemon=True).start()
        lista.connect("notify::selected", montar)

        def comecar(*_):
            modelo = setup.MODELOS[lista.get_selected()][0]
            dlg.close()
            self.instalar_ia(modelo, hw)
        ir.connect("clicked", comecar)
        dlg.present()

    def instalar_ia(self, modelo, hw=None):
        self.passos = CartaoPassos(f"🦙 Configurando a IA local ({modelo})")
        self.adicionar(self.passos)
        self.set_ocupado(True)
        self.agent.on_event = self._ao_evento
        cartao = self.passos

        def prog(status, frac):
            GLib.idle_add(lambda: (cartao.progresso(status, frac), False)[1])

        def trabalho():
            try:
                ok, msg = setup.run_setup(self.agent, modelo, prog, hw)
            except Exception as e:
                ok, msg = False, str(e)
            GLib.idle_add(self._ao_instalar_ia, ok, msg)
        threading.Thread(target=trabalho, daemon=True).start()

    def _ao_instalar_ia(self, ok, msg):
        self.set_ocupado(False)
        linha = Gtk.Box()
        linha.add_css_class("cartao")
        linha.add_css_class("cartao-ok" if ok else "cartao-erro")
        if ok:
            linha.append(self._label(f"✅  <b>{esc(msg)}</b>\nAgora é só perguntar."))
            self.cfg = config.load()
            self.agent = Agent(self.cfg)
            self.atualizar_status()
            if getattr(self, "_cartao_ia", None):
                self._cartao_ia.set_visible(False)
        else:
            linha.append(self._label(f"❌  <b>Não foi possível configurar a IA local</b>\n{esc(msg)}"))
        self.adicionar(linha)
        return False

    def ao_clicar_sobre(self, *_):
        sobre = Gtk.AboutDialog()
        sobre.set_transient_for(self)
        sobre.set_modal(True)
        sobre.set_program_name("VoidBR AI")
        sobre.set_version(APP_VERSION)
        sobre.set_logo_icon_name("help-browser")
        sobre.set_comments(
            "🤖 Assistente de sistema integrado ao VoidBR.\n"
            "Investiga a máquina real, explica e só muda algo com a sua confirmação.\n"
            "Feito com Python + GTK4 para o VoidBR Linux 🐧"
        )
        sobre.set_website("https://voidbr.org")
        sobre.set_website_label("VoidBR")
        sobre.set_authors(["Vilmar Catafesta <vcatafesta@gmail.com>"])
        sobre.set_copyright("© 2026 Vilmar Catafesta — Licença livre, use e modifique à vontade")
        sobre.set_license_type(Gtk.License.MIT_X11)
        sobre.present()


class AppVoidbrAI(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        janela = self.props.active_window or JanelaVoidbrAI(self)
        janela.present()


def main():
    from ..util import ROOT_MSG, rodando_como_root
    if rodando_como_root():
        print(f"voidbr-ai-gui: {ROOT_MSG}", file=sys.stderr)
        return 1
    if "--reset-font" in sys.argv[1:]:
        # escape caso uma fonte deixe a janela ilegível
        config.save_user({"gui": {"font_family": "", "font_scale": 1.0}})
        print("voidbr-ai-gui: fonte voltou ao padrão do sistema")
        sys.argv = [a for a in sys.argv if a != "--reset-font"]
    cfg = config.load()
    history.setup_logging(cfg.get("log", {}).get("level", "info"))
    # a senha das ações vem do agente gráfico do polkit, nunca do terminal
    from ..tools import privileged
    privileged.SEM_TERMINAL = True
    app = AppVoidbrAI()
    return app.run(None)


__all__ = ["main", "APP_NAME"]
