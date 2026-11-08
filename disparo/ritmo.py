"""Ritmo de disparo e janela de horário.

Sem relógio nem sorteio escondidos: os dois entram por parâmetro, então os
testes conseguem provar exatamente quando a ferramenta envia e quando espera.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class Perfil:
    intervalo: tuple[float, float]
    bloco: tuple[int, int]
    pausa: tuple[float, float]
    aquecer: bool = True

    def por_hora(self, segundos_por_envio: float = 6.0) -> int:
        """Estimativa de capacidade; o tempo real por envio sai do piloto."""
        bloco = sum(self.bloco) / 2
        duracao = bloco * (sum(self.intervalo) / 2 + segundos_por_envio)
        return int(3600 * bloco / (duracao + sum(self.pausa) / 2))


PERFIS = {
    "prudente": Perfil((45, 90), (20, 30), (300, 600)),
    "padrao": Perfil((20, 40), (30, 40), (180, 360)),
    "acelerado": Perfil((8, 15), (50, 70), (120, 240)),
    # E-mail: o limite é do Exchange (30 por minuto), não de reputação de número.
    "email": Perfil((2.5, 2.5), (10**9, 10**9), (0, 0)),
    "teste": Perfil((3, 6), (10**9, 10**9), (0, 0)),
}

AQUECIMENTO = 15
CONTA_GOTAS = "contagotas"
CONVERSAS_DIA_PADRAO = 40


@dataclass
class Janela:
    inicio: time
    fim: time
    dias: tuple[int, ...]

    def aberta(self, agora: datetime) -> bool:
        return agora.weekday() in self.dias and self.inicio <= agora.time() < self.fim

    def segundos_ate_abrir(self, agora: datetime) -> float:
        if self.aberta(agora):
            return 0.0
        for adiante in range(8):
            dia = agora.date() + timedelta(days=adiante)
            abertura = datetime.combine(dia, self.inicio)
            if dia.weekday() in self.dias and abertura > agora:
                return (abertura - agora).total_seconds()
        raise ValueError("Janela de envio sem nenhum dia valido.")


def conta_gotas(por_dia: int, janela: Janela) -> Perfil:
    """Poucas conversas novas por dia, espalhadas pelo horário inteiro.

    A linha foi restrita em 05/11/2026 depois de 50 conversas novas em uma hora.
    Aqui o que protege é o total do dia e a distância entre os envios, não pausas
    dentro de uma rajada.
    """
    por_dia = max(1, int(por_dia))
    hoje = datetime(2000, 1, 3)
    segundos = (
        datetime.combine(hoje, janela.fim) - datetime.combine(hoje, janela.inicio)
    ).total_seconds()
    medio = max(60.0, segundos / por_dia)
    return Perfil((medio * 0.6, medio * 1.4), (10**9, 10**9), (0, 0), aquecer=False)


@dataclass
class Ritmo:
    perfil: Perfil
    sorteio: random.Random = field(default_factory=random.Random)
    enviados: int = 0
    _ate_pausa: int = 0

    def __post_init__(self) -> None:
        self._ate_pausa = self.sorteio.randint(*self.perfil.bloco)

    def proxima_espera(self) -> float:
        """Segundos até o próximo envio. Chamar uma vez depois de cada envio."""
        self.enviados += 1
        espera = self.sorteio.uniform(*self.perfil.intervalo)
        if self.perfil.aquecer and self.enviados <= AQUECIMENTO:
            espera *= 2

        self._ate_pausa -= 1
        if self._ate_pausa <= 0:
            self._ate_pausa = self.sorteio.randint(*self.perfil.bloco)
            espera += self.sorteio.uniform(*self.perfil.pausa)
        return espera
