"""Textos da campanha: ficam em `mensagens/`, fora do código.

Modelo com variável desconhecida ou ainda marcado como pendente trava o envio.
Um "{{nome}}" literal chegando ao cliente não tem como ser desfeito.
"""

from __future__ import annotations

import hashlib
import html
import random
import re
from pathlib import Path

from .planilha import Contato, formatar_nome

MARCA_PENDENTE = "PENDENTE_DEFINIR"
_VARIAVEL = re.compile(r"\{\{\s*(\w+)\s*\}\}")
LIMITE_SMS = 160


class ModeloInvalido(Exception):
    pass


def _juntar(itens: list[str]) -> str:
    """"A", "A e B", "A, B e C", sem repetir nomes iguais."""
    unicos = list(dict.fromkeys(itens))
    if len(unicos) < 2:
        return "".join(unicos)
    return ", ".join(unicos[:-1]) + " e " + unicos[-1]


def _parcelas(quantidade: int) -> str:
    return f"{quantidade} parcela{'' if quantidade == 1 else 's'} em aberto"


def _pendencias(contatos: list[Contato]) -> str:
    """Uma linha por inscrição, com o nome de quem responde por ela."""
    return "\n".join(
        f"{formatar_nome(p.nome)} | Número de Inscrição: {numero} | {_parcelas(quantidade)}"
        for p in contatos
        for numero, quantidade in p.planos
    )


def variaveis(contatos: list[Contato]) -> dict[str, str]:
    """Dados que um modelo pode usar. Valor em dinheiro fica de fora de propósito:
    sem a variável, nenhum texto consegue expor quanto a pessoa deve."""
    return {
        "primeiro_nome": _juntar([p.primeiro_nome for p in contatos]),
        "nome": _juntar([formatar_nome(p.nome) for p in contatos]),
        "parcelas": str(sum(p.parcelas for p in contatos)),
        "numero_inscricao": ", ".join(n for p in contatos for n, _ in p.planos),
        "pendencias": _pendencias(contatos),
        "filial": _juntar([p.filial for p in contatos]),
    }


def preencher(modelo: str, dados: dict[str, str], escapar: bool = False) -> str:
    def trocar(achado: re.Match) -> str:
        valor = dados[achado.group(1)]
        return html.escape(valor).replace("\n", "<br>") if escapar else valor

    return _VARIAVEL.sub(trocar, modelo)


def _conferir(nome: str, modelo: str) -> None:
    if not modelo.strip():
        raise ModeloInvalido(f"O modelo {nome} esta vazio.")
    if MARCA_PENDENTE in modelo:
        raise ModeloInvalido(f"O modelo {nome} ainda nao foi definido.")
    validas = set(variaveis([]))
    desconhecidas = set(_VARIAVEL.findall(modelo)) - validas
    if desconhecidas:
        raise ModeloInvalido(
            f"O modelo {nome} usa variaveis inexistentes: {sorted(desconhecidas)}. "
            f"Disponiveis: {sorted(validas)}"
        )


def checar_modelo(modelo: str) -> None:
    """Recusa variável inexistente num texto ainda não salvo."""
    if modelo.strip():
        _conferir("digitado", modelo)


_MOLDURA_EMAIL = """<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f4;padding:24px 12px;font-family:Segoe UI,Arial,Helvetica,sans-serif;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background-color:#ffffff;">
<tr><td style="padding:28px 32px 4px 32px;font-size:15px;font-weight:600;color:#1a1c1e;">{empresa}</td></tr>
<tr><td style="padding:16px 32px 32px 32px;font-size:15px;line-height:1.6;color:#2a2d30;">{corpo}</td></tr>
</table>
</td></tr>
</table>"""


EMPRESA_PADRAO = "Sua Empresa"


def gerar_html_email(texto: str, empresa: str = EMPRESA_PADRAO) -> str:
    """Quem opera escreve texto comum; o HTML que vai ao cliente nasce aqui.

    `empresa` é o nome exibido no topo do e-mail (config.toml, [campanha] empresa).
    """
    paragrafos = [p for p in re.split(r"\n\s*\n", texto.strip()) if p.strip()]
    corpo = "".join(
        f'<p style="margin:0 0 16px 0;">{html.escape(p).replace(chr(10), "<br>")}</p>'
        for p in paragrafos
    )
    return _MOLDURA_EMAIL.format(corpo=corpo, empresa=html.escape(empresa or EMPRESA_PADRAO))


class Modelos:
    """Carrega só o que o canal pede, para o e-mail não depender do texto do SMS."""

    def __init__(self, pasta: str | Path, canal: str, sorteio: random.Random | None = None):
        self.pasta = Path(pasta)
        self.canal = canal
        self.sorteio = sorteio or random.Random()
        if canal == "email":
            self.assunto = self._ler("email_assunto.txt")
            self.corpo = self._ler("email.html")
        else:
            # Variações opcionais: whatsapp.txt, whatsapp_2.txt, whatsapp_3.txt...
            arquivos = sorted(self.pasta.glob(f"{canal}*.txt"))
            if not arquivos:
                raise ModeloInvalido(f"Nenhum modelo de {canal} em {self.pasta}.")
            self.textos = [self._ler(a.name) for a in arquivos]

    def assinatura(self) -> str:
        """Impressão digital do texto. Mudou o texto, o ensaio deixa de constar como feito."""
        partes = [self.assunto, self.corpo] if self.canal == "email" else self.textos
        return hashlib.sha256("\0".join(partes).encode("utf-8")).hexdigest()

    def _ler(self, nome: str) -> str:
        caminho = self.pasta / nome
        if not caminho.exists():
            raise ModeloInvalido(f"Falta o modelo {caminho}.")
        modelo = caminho.read_text(encoding="utf-8").strip()
        _conferir(nome, modelo)
        return modelo

    def montar(self, contatos: list[Contato]) -> dict[str, str]:
        dados = variaveis(contatos)
        if self.canal == "email":
            return {
                "assunto": preencher(self.assunto, dados),
                "html": preencher(self.corpo, dados, escapar=True),
            }
        texto = preencher(self.sorteio.choice(self.textos), dados)
        if self.canal == "sms" and len(texto) > LIMITE_SMS:
            raise ModeloInvalido(
                f"SMS com {len(texto)} caracteres; o limite e {LIMITE_SMS}."
            )
        return {"texto": texto}
