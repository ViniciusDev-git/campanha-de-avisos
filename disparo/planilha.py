"""Leitura da planilha de cobrança e consolidação por pessoa.

A planilha tem uma linha por PLANO; a campanha fala com PESSOAS. Tudo aqui existe
para que cada pessoa receba um aviso só, no contato certo, e para que quem não
pode receber fique registrado com o motivo em vez de sumir em silêncio.
"""

from __future__ import annotations

import csv
import re
import unicodedata
import warnings
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

COLUNAS = {
    "plano": "ID_Plano",
    "nome": "nome_cliente",
    "valor": "Valor Vencido",
    "parcelas": "Parcelas Vencidas",
    "atraso": "Maior Atraso",
    "filial": "fantasia_filiais",
    "cpf": "cpf_cliente",
    "telefone": "tel_cliente",
    "celular": "cel_cliente",
    "email": "email_cliente",
}

DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35,
    37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64,
    65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87, 88,
    89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
}

# Endereço da própria empresa no cadastro do cliente é erro de cadastro: o aviso
# de cobrança iria para um colaborador, não para o devedor. Os domínios da sua
# empresa vêm do config.toml ([campanha] dominios_internos); vazio por padrão.
DOMINIOS_INTERNOS: frozenset[str] = frozenset()

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}")
_MINUSCULAS = {"da", "de", "do", "das", "dos", "e"}


class PlanilhaInvalida(Exception):
    pass


@dataclass
class Contato:
    cpf: str
    nome: str
    valor: float = 0.0
    maior_atraso: datetime | None = None
    # (número de inscrição, parcelas vencidas) de cada plano.
    planos: list[tuple[str, int]] = field(default_factory=list)
    filial: str = ""
    celular: str = ""
    email: str = ""
    motivo_sem_celular: str = ""
    motivo_sem_email: str = ""

    @property
    def primeiro_nome(self) -> str:
        return formatar_nome(self.nome).split(" ")[0] if self.nome else ""

    @property
    def parcelas(self) -> int:
        return sum(quantidade for _, quantidade in self.planos)


@dataclass
class Leitura:
    contatos: list[Contato]
    retidos: list[tuple[Contato, str]]
    linhas: int


def data_corte(hoje: date) -> date:
    """Até que vencimento a campanha cobra, numa data de disparo.

    O foco são os meses retroativos. Até o dia 15, nada do mês corrente entra; do
    dia 16 em diante, entra o que venceu do dia 1 ao dia 15. Exemplo:
    disparo em 14/11 vai até 31/10; disparo em 16/11 vai até 15/11.
    """
    if hoje.day >= 16:
        return hoje.replace(day=15)
    return hoje.replace(day=1) - timedelta(days=1)


def digitos(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\D", "", str(valor))


def normalizar_cpf(valor) -> str:
    """O Excel guarda CPF como número e perde os zeros à esquerda."""
    bruto = digitos(valor)
    return bruto.zfill(11) if bruto else ""


def normalizar_celular(valor) -> tuple[str, str]:
    """Devolve (numero com 55, motivo da recusa). Só um dos dois vem preenchido.

    Número de 10 dígitos é recusado de propósito, mesmo parecendo celular antigo:
    deduzir o nono dígito é chutar, e o chute errado leva um aviso de dívida a um
    desconhecido. Essa pessoa continua recebendo por e-mail.
    """
    d = digitos(valor).lstrip("0")
    if not d:
        return "", "sem numero"
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) != 11:
        return "", f"{len(d)} digitos"
    if int(d[:2]) not in DDDS:
        return "", "DDD inexistente"
    if d[2] != "9":
        return "", "nao e celular"
    if Counter(d[2:]).most_common(1)[0][1] >= 7:
        return "", "numero de preenchimento"
    return "55" + d, ""


def normalizar_email(
    valor, aceitar_interno: bool = False, dominios_internos=None
) -> tuple[str, str]:
    internos = DOMINIOS_INTERNOS if dominios_internos is None else {
        str(d).strip().lower().lstrip("@") for d in dominios_internos
    }
    e = str(valor or "").strip().lower()
    if not e:
        return "", "sem e-mail"
    if not _EMAIL.fullmatch(e):
        return "", "formato invalido"
    if not aceitar_interno and e.rsplit("@", 1)[1] in internos:
        return "", "dominio interno da empresa"
    return e, ""


def ler_internos(caminho: str | Path) -> list[Contato]:
    """Lista da equipe para o ensaio. Os valores são fictícios de propósito:
    dado real de cliente não circula entre colaboradores por causa de um teste.
    Contato inválido aqui é erro, não exclusão: a lista é curta e feita à mão.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise PlanilhaInvalida(f"Falta a lista de teste: {caminho}")

    contatos: list[Contato] = []
    with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
        for i, linha in enumerate(csv.DictReader(arquivo, delimiter=";"), start=1):
            nome = (linha.get("nome") or "").strip()
            bruto_celular = (linha.get("celular") or "").strip()
            bruto_email = (linha.get("email") or "").strip()
            if not nome and not bruto_celular and not bruto_email:
                continue

            celular, motivo = normalizar_celular(bruto_celular)
            if bruto_celular and not celular:
                raise PlanilhaInvalida(f"Lista de teste, linha {i}: celular recusado ({motivo}).")
            email, motivo = normalizar_email(bruto_email, aceitar_interno=True)
            if bruto_email and not email:
                raise PlanilhaInvalida(f"Lista de teste, linha {i}: e-mail recusado ({motivo}).")

            contatos.append(
                Contato(
                    cpf=f"teste-{i}", nome=nome or "Equipe Teste", valor=1234.56,
                    planos=[("12345", 3)], filial="Teste", celular=celular, email=email,
                )
            )
    if not contatos:
        raise PlanilhaInvalida(f"A lista de teste esta vazia: {caminho}")
    return contatos


def formatar_nome(nome: str) -> str:
    partes = [p for p in str(nome or "").strip().split() if p]
    saida = []
    for i, parte in enumerate(partes):
        baixa = parte.lower()
        saida.append(baixa if i and baixa in _MINUSCULAS else baixa.capitalize())
    return " ".join(saida)


def formatar_valor(valor: float) -> str:
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"{inteiro.replace(',', '.')},{centavos}"


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)
    )


def _ler_linhas(caminho: Path) -> list[dict]:
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        planilha = openpyxl.load_workbook(caminho, read_only=True, data_only=True)

    aba = planilha.worksheets[0]
    cabecalho: list | None = None
    linhas: list[dict] = []
    for linha in aba.iter_rows(values_only=True):
        if cabecalho is None:
            if sum(c is not None for c in linha) >= 3:
                cabecalho = [str(c).strip() if c is not None else "" for c in linha]
            continue
        if any(c is not None for c in linha):
            linhas.append(dict(zip(cabecalho, linha)))
    planilha.close()

    faltando = [c for c in COLUNAS.values() if c not in (cabecalho or [])]
    if faltando:
        raise PlanilhaInvalida(
            "A planilha nao tem as colunas esperadas: " + ", ".join(faltando)
        )
    return linhas


def ler(
    caminho: str | Path,
    valor_minimo: float = 1.0,
    vencido_ate: date | None = None,
    dominios_internos=None,
) -> Leitura:
    """Lê a planilha e separa quem entra na campanha de quem fica retido.

    O total abaixo de `valor_minimo` é retido por CPF: quem deve R$ 0,01 num plano
    e R$ 500 em outro continua na campanha.

    `vencido_ate` corta por PLANO, pela coluna Maior Atraso: o plano cuja dívida
    mais antiga é posterior à data sai da conta. A planilha não detalha parcelas,
    então um plano mantido pode carregar parcelas posteriores ao corte no total.

    `dominios_internos`: e-mails desses domínios (os da sua empresa) são recusados.
    """
    linhas = _ler_linhas(Path(caminho))
    c = COLUNAS

    por_pessoa: dict[str, list[dict]] = {}
    for linha in linhas:
        chave = normalizar_cpf(linha[c["cpf"]]) or f"plano-{digitos(linha[c['plano']])}"
        por_pessoa.setdefault(chave, []).append(linha)

    contatos: list[Contato] = []
    retidos: list[tuple[Contato, str]] = []

    for cpf, grupo in por_pessoa.items():
        elegiveis = grupo
        if vencido_ate is not None:
            elegiveis = [
                l for l in grupo
                if isinstance(l[c["atraso"]], datetime)
                and l[c["atraso"]].date() <= vencido_ate
            ]
        fora_do_corte = not elegiveis
        grupo = elegiveis or grupo

        # O plano de maior valor manda no contato: é o cadastro com mais chance
        # de estar em uso quando a mesma pessoa tem dados diferentes por plano.
        grupo.sort(key=lambda l: float(l[c["valor"]] or 0), reverse=True)
        atrasos = [l[c["atraso"]] for l in grupo if isinstance(l[c["atraso"]], datetime)]

        contato = Contato(
            cpf=cpf,
            nome=str(grupo[0][c["nome"]] or "").strip(),
            valor=round(sum(float(l[c["valor"]] or 0) for l in grupo), 2),
            maior_atraso=min(atrasos) if atrasos else None,
            planos=[
                (digitos(l[c["plano"]]), int(float(l[c["parcelas"]] or 0))) for l in grupo
            ],
            filial=str(grupo[0][c["filial"]] or "").strip(),
        )

        motivo_cel = "sem numero"
        for linha in grupo:
            for coluna in (c["celular"], c["telefone"]):
                numero, motivo = normalizar_celular(linha[coluna])
                if numero:
                    contato.celular = numero
                    break
                if coluna == c["celular"]:
                    motivo_cel = motivo
            if contato.celular:
                break
        contato.motivo_sem_celular = "" if contato.celular else motivo_cel

        motivo_mail = "sem e-mail"
        for linha in grupo:
            endereco, motivo = normalizar_email(linha[c["email"]], dominios_internos=dominios_internos)
            if endereco:
                contato.email = endereco
                break
            motivo_mail = motivo
        contato.motivo_sem_email = "" if contato.email else motivo_mail

        if fora_do_corte:
            retidos.append((contato, "vencido apenas depois do corte"))
        elif contato.valor < valor_minimo:
            retidos.append((contato, "valor abaixo do minimo"))
        elif not contato.nome:
            retidos.append((contato, "sem nome"))
        elif not contato.celular and not contato.email:
            retidos.append((contato, "sem nenhum contato valido"))
        else:
            contatos.append(contato)

    # Quem não tem e-mail vai primeiro: o WhatsApp é o único aviso dessa pessoa.
    contatos.sort(key=lambda p: (bool(p.email), -p.valor, _sem_acento(p.nome)))
    return Leitura(contatos=contatos, retidos=retidos, linhas=len(linhas))
