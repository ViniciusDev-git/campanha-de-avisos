"""As operações da campanha, usadas igualmente pela janela e pela linha de comando.

Toda trava de segurança mora aqui, e não na interface: se a tela tiver um defeito,
horário, limite diário e lista de quem não recebe continuam valendo. O ensaio é
opcional: serve para ver se a ferramenta está operacional e não bloqueia o disparo.
"""

from __future__ import annotations

import csv
import ctypes
import json
import sys
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable

from . import fila as F
from . import planilha
from .ambiente import TRAVA_ARQUIVOS, abrir_fila, caminho, janela_de
from .fila import Fila
from .modelos import Modelos
from .motor import Balanco, ParadaObrigatoria, rodar
from .ritmo import CONTA_GOTAS, CONVERSAS_DIA_PADRAO, PERFIS, Janela, Ritmo, conta_gotas


class Recusado(Exception):
    """A operação não pode começar. A mensagem diz à pessoa o que fazer."""


class SaidaEmMassa(Recusado):
    """A planilha é curta demais para ser a campanha: cancelaria boa parte da fila."""


# Abaixo disto a fila é pequena demais para a trava de lista parcial fazer sentido.
MINIMO_PARA_TRAVA = 20


def arquivo_parar(cfg: dict, canal: str) -> Path:
    return caminho(f"{cfg['campanha']['parar']}-{canal}")


def _arquivo_importacao(cfg: dict) -> Path:
    return caminho(cfg["campanha"]["banco"]).parent / "ultima_importacao.json"


def ultima_importacao(cfg: dict) -> dict | None:
    arquivo = _arquivo_importacao(cfg)
    return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else None


def corte(cfg: dict, hoje: date | None = None) -> date:
    """Data de corte em vigor: automática, ou fixa se alguém a definiu no config."""
    valor = cfg["campanha"]["vencido_ate"]
    if valor == "automatico":
        return planilha.data_corte(hoje or date.today())
    return date.fromisoformat(valor)


def preparar(cfg: dict, arquivo_planilha: str | Path, forcar: bool = False) -> dict:
    """Lê a planilha, monta a fila e registra o resumo do que entrou e do que não."""
    campanha = cfg["campanha"]
    data_corte = corte(cfg)
    leitura = planilha.ler(
        arquivo_planilha, campanha["valor_minimo"], data_corte,
        campanha.get("dominios_internos", ()),
    )
    fila = abrir_fila(cfg)
    # Quem some da planilha é tratado como quem pagou. Uma lista parcial carregada
    # aqui cancelaria o resto da campanha, então isso precisa de uma decisão explícita.
    sairiam, pendentes = fila.sairiam_da_fila(leitura.contatos)
    if not forcar and pendentes >= MINIMO_PARA_TRAVA and sairiam * 2 > pendentes:
        fila.fechar()
        raise SaidaEmMassa(
            f"Esta planilha cancelaria {sairiam} de {pendentes} mensagens na fila. "
            "Se ela é uma lista de prioridade, use Priorizar lista."
        )
    fila_resumo = fila.importar(leitura.contatos)

    saida = caminho(campanha["saida"])
    saida.mkdir(exist_ok=True)
    arquivo_retidos = saida / f"retidos-{datetime.now():%Y%m%d-%H%M%S}.csv"
    with open(arquivo_retidos, "w", newline="", encoding="utf-8-sig") as f:
        escrita = csv.writer(f, delimiter=";")
        escrita.writerow(["motivo", "cpf", "nome", "valor", "parcelas", "planos", "filial"])
        for p, motivo in leitura.retidos:
            escrita.writerow(
                [motivo, p.cpf, p.nome, planilha.formatar_valor(p.valor), p.parcelas,
                 " ".join(numero for numero, _ in p.planos), p.filial]
            )

    resumo = {
        "arquivo": Path(arquivo_planilha).name,
        "corte": data_corte.isoformat(),
        "quando": datetime.now().isoformat(timespec="seconds"),
        "linhas": leitura.linhas,
        "pessoas": len(leitura.contatos),
        "pendentes": fila.pessoas_pendentes(),
        "retidos": len(leitura.retidos),
        "motivos_retidos": dict(Counter(m for _, m in leitura.retidos).most_common()),
        "sem_celular": dict(
            Counter(p.motivo_sem_celular for p in leitura.contatos if not p.celular)
        ),
        "sem_email": dict(Counter(p.motivo_sem_email for p in leitura.contatos if not p.email)),
        "arquivo_retidos": str(arquivo_retidos),
        "fila": fila_resumo,
        "retidos_lista": [
            {"nome": planilha.formatar_nome(p.nome), "motivo": m} for p, m in leitura.retidos
        ],
    }
    fila.fechar()
    _arquivo_importacao(cfg).write_text(
        json.dumps(resumo, ensure_ascii=False), encoding="utf-8"
    )
    return resumo


def priorizar(cfg: dict, arquivo_planilha: str | Path) -> dict:
    """Põe na frente da fila do WhatsApp as pessoas desta planilha. Nada é enviado."""
    campanha = cfg["campanha"]
    leitura = planilha.ler(
        arquivo_planilha, campanha["valor_minimo"], corte(cfg),
        campanha.get("dominios_internos", ()),
    )
    if not leitura.contatos:
        raise Recusado("Nenhuma pessoa desta planilha pode ser avisada.")
    fila = abrir_fila(cfg)
    try:
        return fila.priorizar(
            "whatsapp", [p.cpf for p in leitura.contatos], Path(arquivo_planilha).name
        )
    finally:
        fila.fechar()


def _ensaios(cfg: dict) -> Path:
    return caminho(cfg["campanha"]["banco"]).parent / "ensaios_aprovados.json"


def ler_ensaios(cfg: dict) -> dict:
    arquivo = _ensaios(cfg)
    return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}


def ensaio_vale(cfg: dict, canal: str) -> bool:
    try:
        modelos = Modelos(caminho(cfg["campanha"]["mensagens"]), canal)
    except Exception:
        return False
    return ler_ensaios(cfg).get(canal) == modelos.assinatura()


def manter_acordado() -> None:
    """Sem isto o Windows suspende e a campanha para sem aviso."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)


def cliente_whatsapp(cfg: dict, permitir_repetida: bool = False, log: Callable = print):
    from .canal_whatsapp import ClienteWhatsApp

    return ClienteWhatsApp(
        caminho(cfg["whatsapp"]["sessao"]), permitir_repetida=permitir_repetida, log=log
    )


def cliente_email(cfg: dict, log: Callable = print):
    from .canal_email import ClienteEmail, conectar

    secao = cfg["email"]
    if not secao["responder_para"]:
        raise Recusado("Informe o e-mail que recebe as respostas dos clientes.")
    graph = conectar(secao, secao["remetente"], secao["responder_para"])
    log(graph.testar_conexao())
    return ClienteEmail(graph)


def ensaiar(cfg: dict, canal: str, log: Callable = print) -> dict:
    """Ensaio com a equipe, pelo mesmo motor do disparo real.

    Usa um banco próprio, recriado a cada ensaio: a fila dos clientes não é lida
    nem alterada. Passar sem nenhuma falha registra o ensaio do texto atual.
    """
    if canal == "sms":
        raise Recusado("O SMS ainda não tem fornecedor definido.")

    modelos = Modelos(caminho(cfg["campanha"]["mensagens"]), canal)
    internos = planilha.ler_internos(caminho(cfg["campanha"]["teste_interno"]))

    banco = caminho(cfg["campanha"]["banco"]).with_name(f"ensaio-{canal}.sqlite3")
    for sufixo in ("", "-wal", "-shm"):
        Path(f"{banco}{sufixo}").unlink(missing_ok=True)
    fila = Fila(banco)
    try:
        fila.importar(internos)
        total = fila.contagem()[canal].get(F.PENDENTE, 0)
        if not total:
            raise Recusado(f"A lista interna não tem nenhum contato para {canal}.")
        log(f"Ensaio para {total} contato(s) interno(s), com dados fictícios.")

        parar = arquivo_parar(cfg, canal)
        parar.unlink(missing_ok=True)
        opcoes = dict(
            fila=fila, canal=canal, modelos=modelos, ritmo=Ritmo(PERFIS["teste"]),
            janela=Janela(time.min, time.max, tuple(range(7))), limite_diario=10**6,
            arquivo_supressao=caminho(cfg["campanha"]["nao_enviar"]), arquivo_parar=parar,
            log=log,
        )
        if canal == "email":
            balanco = rodar(cliente=cliente_email(cfg, log), **opcoes)
        else:
            with cliente_whatsapp(cfg, permitir_repetida=True, log=log) as cliente:
                balanco = rodar(cliente=cliente, **opcoes)
    finally:
        fila.fechar()

    aprovado = balanco.enviados == total
    if aprovado:
        with TRAVA_ARQUIVOS:
            aprovados = ler_ensaios(cfg)
            aprovados[canal] = modelos.assinatura()
            _ensaios(cfg).write_text(json.dumps(aprovados), encoding="utf-8")
    return {
        "aprovado": aprovado,
        "enviados": balanco.enviados,
        "total": total,
        "outros": balanco.outros,
        "motivo": balanco.motivo_parada,
    }


def disparar(
    cfg: dict,
    canal: str,
    maximo: int | None = None,
    ritmo: str | None = None,
    aguardar_janela: bool = True,
    log: Callable = print,
) -> Balanco:
    if canal == "sms":
        raise Recusado("O SMS ainda não tem fornecedor definido.")

    secao = cfg[canal]
    modelos = Modelos(caminho(cfg["campanha"]["mensagens"]), canal)

    limite = secao["limite_diario"]
    gotas = canal != "email" and (ritmo or secao["ritmo"]) == CONTA_GOTAS
    if canal == "email":
        perfil = PERFIS["email"]
    elif gotas:
        limite = max(1, int(secao.get("conversas_dia", CONVERSAS_DIA_PADRAO)))
        perfil = conta_gotas(limite, janela_de(secao))
    else:
        perfil = PERFIS[ritmo or secao["ritmo"]]
    parar = arquivo_parar(cfg, canal)
    parar.unlink(missing_ok=True)
    fila = abrir_fila(cfg)
    manter_acordado()
    try:
        opcoes = dict(
            fila=fila, canal=canal, modelos=modelos, ritmo=Ritmo(perfil),
            janela=janela_de(secao), limite_diario=limite,
            arquivo_supressao=caminho(cfg["campanha"]["nao_enviar"]), arquivo_parar=parar,
            maximo=maximo, aguardar_janela=aguardar_janela,
            aguardar_limite=gotas and maximo is None, log=log,
        )
        if canal == "email":
            return rodar(cliente=cliente_email(cfg, log), **opcoes)
        with cliente_whatsapp(cfg, log=log) as cliente:
            return rodar(cliente=cliente, **opcoes)
    finally:
        fila.fechar()


__all__ = [
    "ParadaObrigatoria", "Recusado", "arquivo_parar", "disparar", "ensaiar", "ensaio_vale",
    "ler_ensaios", "preparar", "ultima_importacao",
]
