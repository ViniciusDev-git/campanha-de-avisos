"""Laço de envio, igual para todos os canais.

Cada canal só precisa saber enviar uma mensagem. Janela, ritmo, supressão,
limite diário e paradas de segurança moram aqui, num lugar só.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as hora, timedelta
from pathlib import Path
from typing import Callable, Protocol

from . import fila as F
from .fila import Fila, Item
from .modelos import Modelos
from .ritmo import Janela, Ritmo

MAX_INCERTOS_SEGUIDOS = 3
AMOSTRA_INVALIDOS = 20
TAXA_MAX_INVALIDOS = 0.5


class ParadaObrigatoria(Exception):
    """Sinal de que continuar é perigoso. Nunca é tratada com nova tentativa.

    `nada_saiu=True` devolve o item à fila; sem isso ele vira `incerto`.
    """

    def __init__(self, motivo: str, nada_saiu: bool = False):
        super().__init__(motivo)
        self.nada_saiu = nada_saiu


@dataclass
class Resultado:
    status: str
    detalhe: str = ""


class Cliente(Protocol):
    def enviar(self, destino: str, conteudo: dict[str, str]) -> Resultado: ...


@dataclass
class Balanco:
    enviados: int = 0
    outros: dict[str, int] = field(default_factory=dict)
    motivo_parada: str = ""

    def contar(self, status: str) -> None:
        if status == F.ENVIADO:
            self.enviados += 1
        else:
            self.outros[status] = self.outros.get(status, 0) + 1


def ler_supressao(caminho: Path) -> set[str]:
    """Lista de quem não deve receber. Relida a cada envio: o atendimento pode incluir
    alguém com a campanha rodando e o efeito é imediato."""
    if not caminho.exists():
        return set()
    saida = set()
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#")[0].strip().lower()
        if not linha:
            continue
        if "@" in linha:
            saida.add(linha)
            continue
        numero = re.sub(r"\D", "", linha)
        if numero:
            saida.add(numero)
            saida.add(numero.zfill(11))
            saida.add(numero.removeprefix("55"))
    return saida


def contato_suprimido(item: Item, lista: set[str]) -> bool:
    return bool({item.destino.lower(), item.destino.removeprefix("55")} & lista)


def rodar(
    fila: Fila,
    canal: str,
    cliente: Cliente,
    modelos: Modelos,
    ritmo: Ritmo,
    janela: Janela,
    limite_diario: int,
    arquivo_supressao: Path,
    arquivo_parar: Path,
    maximo: int | None = None,
    aguardar_janela: bool = True,
    aguardar_limite: bool = False,
    log: Callable[[str], None] = print,
    agora: Callable[[], datetime] = datetime.now,
    dormir: Callable[[float], None] = time.sleep,
) -> Balanco:
    balanco = Balanco()
    incertos_seguidos = 0
    ultimos: deque[bool] = deque(maxlen=AMOSTRA_INVALIDOS)

    def parar_pedido() -> bool:
        return arquivo_parar.exists()

    def esperar(segundos: float) -> bool:
        """Espera em fatias para atender o pedido de parada sem demora."""
        restante = segundos
        while restante > 0:
            if parar_pedido():
                return False
            fatia = min(restante, 5.0)
            dormir(fatia)
            restante -= fatia
        return True

    recuperados = fila.recuperar_interrompidos(canal)
    if recuperados:
        log(f"{recuperados} envio(s) interrompido(s) marcados como incertos.")

    while True:
        if parar_pedido():
            balanco.motivo_parada = "parada pedida pelo operador"
            break
        if maximo is not None and balanco.enviados >= maximo:
            balanco.motivo_parada = f"meta de {maximo} envios atingida"
            break

        momento = agora()
        if not janela.aberta(momento):
            if not aguardar_janela:
                balanco.motivo_parada = "fora da janela de envio"
                break
            segundos = janela.segundos_ate_abrir(momento)
            log(f"Fora da janela. Retomando em {segundos / 3600:.1f} h.")
            esperar(segundos)
            continue

        if fila.enviados_hoje(canal) >= limite_diario:
            if not aguardar_limite:
                balanco.motivo_parada = f"limite diario de {limite_diario} atingido"
                break
            # Campanha de vários dias: espera a abertura de amanhã em vez de parar.
            virada = datetime.combine(momento.date() + timedelta(days=1), hora.min)
            segundos = (virada - momento).total_seconds() + janela.segundos_ate_abrir(
                virada - timedelta(seconds=1)
            )
            log(f"Limite de hoje atingido ({limite_diario}). Retoma no próximo dia de envio.")
            esperar(segundos)
            continue

        item = fila.reservar(canal)
        if item is None:
            balanco.motivo_parada = "fila concluida"
            break

        # O número suprimido cancela a mensagem. O CPF suprimido sai só dela: as
        # outras pessoas do mesmo número continuam sendo avisadas.
        lista = ler_supressao(arquivo_supressao)
        restantes = [p for p in item.contatos if p.cpf not in lista]
        for pessoa in item.contatos:
            if pessoa.cpf in lista:
                fila.excluir_contato(item.id, pessoa.cpf)
        if contato_suprimido(item, lista) or not restantes:
            fila.finalizar(item.id, F.CANCELADO, "lista nao_enviar")
            balanco.contar(F.CANCELADO)
            continue

        try:
            conteudo = modelos.montar(restantes)
        except Exception:
            fila.devolver(item.id)
            raise
        fila.gravar_texto(item.id, conteudo.get("texto") or conteudo.get("assunto", ""))

        try:
            resultado = cliente.enviar(item.destino, conteudo)
        except ParadaObrigatoria as parada:
            if parada.nada_saiu:
                fila.devolver(item.id)
            else:
                fila.finalizar(item.id, F.INCERTO, str(parada))
                balanco.contar(F.INCERTO)
            balanco.motivo_parada = str(parada)
            break
        except Exception as erro:  # qualquer surpresa: não dá para afirmar que não saiu
            resultado = Resultado(F.INCERTO, f"{type(erro).__name__}: {erro}")

        fila.finalizar(item.id, resultado.status, resultado.detalhe)
        balanco.contar(resultado.status)
        log(f"{resultado.status:<13} {_mascarar(item.destino)}  {resultado.detalhe}".rstrip())

        incertos_seguidos = incertos_seguidos + 1 if resultado.status == F.INCERTO else 0
        if incertos_seguidos >= MAX_INCERTOS_SEGUIDOS:
            balanco.motivo_parada = f"{incertos_seguidos} envios sem confirmacao seguidos"
            break

        ultimos.append(resultado.status == F.SEM_WHATSAPP)
        if len(ultimos) == AMOSTRA_INVALIDOS and sum(ultimos) / len(ultimos) > TAXA_MAX_INVALIDOS:
            balanco.motivo_parada = (
                f"mais de {TAXA_MAX_INVALIDOS:.0%} dos ultimos {AMOSTRA_INVALIDOS} "
                "numeros sem WhatsApp: confira a lista antes de seguir"
            )
            break

        esperar(ritmo.proxima_espera())

    return balanco


def _mascarar(destino: str) -> str:
    if "@" in destino:
        nome, dominio = destino.split("@", 1)
        return f"{nome[:2]}***@{dominio}"
    return f"{destino[:4]}*****{destino[-2:]}"
