"""Abre o programa real com clientes fictícios e envio falso, para conferir a tela.

Nada sai daqui: e-mail e WhatsApp são substituídos por um cliente que só dorme.
A planilha é sintética, então capturas de tela não expõem dado de ninguém.

    python tests/demo_janela.py <pasta-temporaria>
"""

import os
import random
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PASTA = Path(sys.argv[1]).resolve()
PASTA.mkdir(parents=True, exist_ok=True)
os.environ["CAMPANHA_PASTA"] = str(PASTA)
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9333"
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

shutil.copy(RAIZ / "config.example.toml", PASTA / "config.toml")
(PASTA / "mensagens").mkdir(exist_ok=True)
for nome in ("whatsapp.txt", "sms.txt", "email_assunto.txt", "email.html"):
    alvo = PASTA / "mensagens" / nome
    if not alvo.exists():
        alvo.write_text("PENDENTE_DEFINIR", encoding="utf-8")


def planilha_sintetica() -> Path:
    import openpyxl

    from disparo.planilha import COLUNAS

    arquivo = PASTA / "demo.xlsx"
    if arquivo.exists():
        return arquivo
    sorte = random.Random(7)
    nomes = "MARIA JOAO ANA PEDRO CARLA PAULO LUCIA MARCOS".split()
    sobrenomes = "EXEMPLO TESTE FICTICIO MODELO".split()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(COLUNAS.values()))
    for i in range(1, 421):
        ws.append([
            float(20000 + i), f"{sorte.choice(nomes)} DE {sorte.choice(sobrenomes)}",
            0.01 if i % 37 == 0 else round(sorte.uniform(50, 4000), 2), float(sorte.randint(1, 9)),
            datetime(2026, 11, 2) if i % 41 == 0 else datetime(2026, 10, 10) - timedelta(days=i % 200),
            "Filial Demo", float(i), None, f"1191{i:07d}", f"pessoa{i}@exemplo.com",
        ])
    wb.save(arquivo)
    return arquivo


planilha_sintetica()

from disparo import fila as F  # noqa: E402
from disparo import janela, operacao  # noqa: E402
from disparo.motor import Resultado  # noqa: E402
from disparo.ritmo import PERFIS, Perfil  # noqa: E402


class Falso:
    """Finge enviar. A cada 50 envios simula um número sem WhatsApp."""

    def __init__(self, travar_em=None):
        self.n = 0
        self.travar_em = travar_em

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def enviar(self, destino, conteudo):
        time.sleep(0.05)
        self.n += 1
        if self.travar_em and self.travar_em <= self.n < self.travar_em + 3:
            return Resultado(F.INCERTO, "sem confirmacao de envio")
        if self.n % 50 == 0:
            return Resultado(F.SEM_WHATSAPP, "numero nao esta no WhatsApp")
        return Resultado(F.ENVIADO)


rapido = Perfil((0.2, 0.2), (10**9, 10**9), (0, 0))
for nome in ("teste", "email", "padrao", "prudente", "acelerado"):
    PERFIS[nome] = rapido
operacao.cliente_email = lambda *_: Falso()
operacao.cliente_whatsapp = lambda *_, **k: Falso(None if k.get("permitir_repetida") else 70)
janela.tem_segredo = lambda _: True
(PASTA / "pid.txt").write_text(str(os.getpid()))
janela.abrir()
