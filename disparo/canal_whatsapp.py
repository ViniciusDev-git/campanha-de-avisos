"""Envio pelo WhatsApp Web num Chrome real, com sessão guardada em disco.

Todos os seletores do WhatsApp estão no bloco abaixo. Quando o WhatsApp mudar a
página, é só aqui que se mexe, e o sintoma será uma parada por falta de
confirmação, nunca um envio duplicado.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from . import fila as F
from .motor import ParadaObrigatoria, Resultado

URL_PADRAO = "https://web.whatsapp.com"

SEL_LOGADO = "#pane-side, [data-testid='chat-list'], #side"
SEL_QR = "canvas[aria-label], [data-ref] canvas, [data-testid='qrcode']"
SEL_CAIXA = "footer div[contenteditable='true']"
SEL_DIALOGO = "div[role='dialog'], [data-animate-modal-popup='true']"
# Conferido na página real em 05/11/2026: as classes são embaralhadas e não servem
# de referência. O balão é uma linha `conv-msg-*`, a cauda só existe no primeiro
# balão de uma sequência, e o status fica num span com aria-label dentro de msg-meta.
SEL_LINHA = "#main [data-testid^='conv-msg-']"
SEL_META = "[data-testid='msg-meta']"
SEL_CAUDA = "[data-testid='tail-out']"
# Lista do que confirma. O que não estiver aqui (relógio, erro) nunca conta como
# enviado: o pior caso é uma parada por falta de confirmação, não um falso positivo.
ROTULOS_OK = (
    "enviada", "enviado", "entregue", "lida", "lido", "visualizada", "visualizado",
    "sent", "delivered", "read",
)
ICONES_OK = ("check", "read", "sent", "delivered")

TERMOS_NUMERO_INVALIDO = ("invalid", "inválido", "invalido", "não está no whatsapp", "not on whatsapp")
TERMOS_RESTRICAO = (
    "banned", "banid", "restrict", "restrit", "suspens", "suspend",
    "temporariamente", "temporarily", "bloquead", "blocked", "spam",
)

_LER_ESTADO = """
([linha, meta, cauda, trecho, rotulos, icones]) => {
  const situacao = (no) => {
    const caixa = no.querySelector(meta);
    const marca = caixa && [...caixa.querySelectorAll("span[aria-label]")].find(s => s.querySelector("svg"));
    if (!marca) return null;
    const titulo = marca.querySelector("svg title");
    return {
      rotulo: marca.getAttribute("aria-label").trim().toLowerCase(),
      icone: (titulo ? titulo.textContent : "").toLowerCase(),
    };
  };
  const nos = [...document.querySelectorAll(linha)].filter(
    n => (n.querySelector(cauda) || situacao(n)) && n.innerText.includes(trecho)
  );
  const ultimo = nos[nos.length - 1];
  if (!ultimo) return {quantas: 0, confirmada: false};
  const s = situacao(ultimo);
  return {
    quantas: nos.length,
    confirmada: !!s && (rotulos.includes(s.rotulo) || icones.some(i => s.icone.includes(i))),
  };
}
"""


def _trecho(texto: str) -> str:
    """Primeira linha, curta: é o que dá para comparar com o balão renderizado."""
    return texto.strip().splitlines()[0][:60]


class ClienteWhatsApp:
    def __init__(
        self,
        pasta_sessao: str | Path,
        url: str = URL_PADRAO,
        headless: bool = False,
        espera_login: float = 180.0,
        espera_abrir: float = 45.0,
        espera_confirmar: float = 30.0,
        espera_historico: float = 3.0,
        permitir_repetida: bool = False,
        log: Callable[[str], None] = print,
    ):
        self.permitir_repetida = permitir_repetida
        self.log = log
        self.pasta_sessao = Path(pasta_sessao)
        self.url = url.rstrip("/")
        self.headless = headless
        self.espera_login = espera_login
        self.espera_abrir = espera_abrir
        self.espera_confirmar = espera_confirmar
        self.espera_historico = espera_historico
        self._pw = None
        self._contexto = None
        self.pagina = None

    def abrir(self) -> None:
        from playwright.sync_api import sync_playwright

        self.pasta_sessao.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._contexto = self._abrir_navegador()
        self.pagina = (
            self._contexto.pages[0] if self._contexto.pages else self._contexto.new_page()
        )
        self.pagina.goto(self.url, wait_until="domcontentloaded")
        self._aguardar_login()

    def _abrir_navegador(self):
        """Chrome se houver; senão o Edge, que todo Windows 11 traz."""
        from playwright.sync_api import Error

        for canal in ("chrome", "msedge"):
            try:
                return self._pw.chromium.launch_persistent_context(
                    str(self.pasta_sessao), channel=canal, headless=self.headless,
                    viewport=None, chromium_sandbox=True,
                )
            except Error as erro:
                motivo = str(erro)
        raise ParadaObrigatoria(f"Não foi possível abrir o navegador: {motivo}", nada_saiu=True)

    def _aguardar_login(self) -> None:
        self.log("Aguardando o WhatsApp Web. Se aparecer o QR Code, leia com o celular.")
        limite = time.monotonic() + self.espera_login
        while time.monotonic() < limite:
            if self.pagina.locator(SEL_LOGADO).count():
                return
            self.pagina.wait_for_timeout(1000)
        raise ParadaObrigatoria("O WhatsApp Web não conectou a tempo.", nada_saiu=True)

    def fechar(self) -> None:
        if self._contexto is not None:
            self._contexto.close()
        if self._pw is not None:
            self._pw.stop()

    def __enter__(self) -> "ClienteWhatsApp":
        self.abrir()
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def _texto_dialogo(self) -> str:
        dialogos = self.pagina.locator(SEL_DIALOGO)
        if not dialogos.count():
            return ""
        return " ".join(dialogos.all_inner_texts()).lower()

    def _abrir_conversa(self, numero: str, texto: str) -> Resultado | None:
        """Devolve Resultado se a conversa não abriu; None se está pronta."""
        self.pagina.goto(
            f"{self.url}/send?phone={numero}&text={quote(texto)}",
            wait_until="domcontentloaded",
        )
        limite = time.monotonic() + self.espera_abrir
        while time.monotonic() < limite:
            aviso = self._texto_dialogo()
            if any(t in aviso for t in TERMOS_RESTRICAO):
                raise ParadaObrigatoria(f"possível restrição no número: {aviso[:200]}", nada_saiu=True)
            if any(t in aviso for t in TERMOS_NUMERO_INVALIDO):
                return Resultado(F.SEM_WHATSAPP, "numero nao esta no WhatsApp")
            if self.pagina.locator(SEL_QR).count() and not self.pagina.locator(SEL_LOGADO).count():
                raise ParadaObrigatoria("a sessão do WhatsApp desconectou. Leia o QR Code de novo.", nada_saiu=True)
            caixa = self.pagina.locator(SEL_CAIXA)
            if caixa.count() and _trecho(texto) in caixa.first.inner_text():
                return None
            self.pagina.wait_for_timeout(500)
        raise ParadaObrigatoria("a conversa não abriu a tempo. Confira a internet e retome.", nada_saiu=True)

    def _estado(self, trecho: str) -> dict:
        return self.pagina.evaluate(
            _LER_ESTADO,
            [SEL_LINHA, SEL_META, SEL_CAUDA, trecho, list(ROTULOS_OK), list(ICONES_OK)],
        )

    def _aguardar_historico(self) -> None:
        """A caixa fica pronta antes dos balões: ler cedo demais esconderia uma
        mensagem já enviada e abriria caminho para repetir a cobrança."""
        limite = time.monotonic() + self.espera_historico
        while time.monotonic() < limite and not self.pagina.locator(SEL_LINHA).count():
            self.pagina.wait_for_timeout(250)

    def enviar(self, destino: str, conteudo: dict[str, str]) -> Resultado:
        texto = conteudo["texto"]
        recusa = self._abrir_conversa(destino, texto)
        if recusa is not None:
            return recusa

        trecho = _trecho(texto)
        self._aguardar_historico()
        antes = self._estado(trecho)["quantas"]
        if antes and not self.permitir_repetida:
            # Já existe este texto na conversa: alguém recebeu antes (execução
            # anterior, teste, envio manual). Não repete a cobrança.
            return Resultado(F.DUPLICADO, "mensagem ja consta na conversa")

        self.pagina.locator(SEL_CAIXA).first.click()
        self.pagina.keyboard.press("Enter")

        limite = time.monotonic() + self.espera_confirmar
        ultimo: dict = {}
        while time.monotonic() < limite:
            ultimo = self._estado(trecho)
            if ultimo["quantas"] > antes and ultimo["confirmada"]:
                return Resultado(F.ENVIADO)
            aviso = self._texto_dialogo()
            if any(t in aviso for t in TERMOS_RESTRICAO):
                raise ParadaObrigatoria(f"possível restrição no número: {aviso[:200]}")
            self.pagina.wait_for_timeout(500)

        if ultimo.get("quantas", 0) > antes:
            return Resultado(F.INCERTO, "mensagem na conversa, sem confirmacao de envio")
        return Resultado(F.INCERTO, "mensagem nao apareceu na conversa")
