"""Fila e registro de envios em SQLite.

A unidade de envio é o CONTATO, não a pessoa: um número ou e-mail recebe uma
mensagem só, listando todas as pessoas ligadas a ele. `envios` guarda o contato e
`envio_contatos` guarda quem está em cada mensagem.

A regra central: a marca de "enviando" é gravada ANTES de tentar o envio. Se o
programa ou a máquina caírem no meio, a linha fica como `incerto` e nunca é
reenviada sozinha. Cobrar duas vezes é pior do que deixar um caso para
conferência humana.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .planilha import Contato

CANAIS = ("email", "whatsapp", "sms")

PENDENTE = "pendente"
ENVIANDO = "enviando"
ENVIADO = "enviado"
INCERTO = "incerto"
FALHOU = "falhou"
SEM_WHATSAPP = "sem_whatsapp"
DUPLICADO = "duplicado"
CANCELADO = "cancelado"
# O provedor aceitou o envio e depois devolveu: a pessoa não recebeu o e-mail.
DEVOLVIDO = "devolvido"

# Quem tem prioridade fica abaixo de zero, antes de qualquer posição da planilha.
URGENTE = 1_000_000

SAIU_DA_PLANILHA = "saiu da planilha"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS contatos (
    cpf TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    valor REAL NOT NULL,
    planos TEXT NOT NULL,
    maior_atraso TEXT,
    filial TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS envios (
    id INTEGER PRIMARY KEY,
    canal TEXT NOT NULL,
    destino TEXT NOT NULL,
    status TEXT NOT NULL,
    prioridade INTEGER NOT NULL,
    detalhe TEXT NOT NULL DEFAULT '',
    texto TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL,
    UNIQUE (canal, destino)
);
CREATE TABLE IF NOT EXISTS envio_contatos (
    envio_id INTEGER NOT NULL REFERENCES envios(id),
    cpf TEXT NOT NULL REFERENCES contatos(cpf),
    ativo INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (envio_id, cpf)
);
CREATE TABLE IF NOT EXISTS prioridades (
    canal TEXT NOT NULL,
    cpf TEXT NOT NULL,
    motivo TEXT NOT NULL,
    PRIMARY KEY (canal, cpf)
);
CREATE INDEX IF NOT EXISTS fila_por_canal ON envios (canal, status, prioridade);
"""


@dataclass
class Item:
    id: int
    canal: str
    destino: str
    contatos: list[Contato]


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gravar_planos(planos: list[tuple[str, int]]) -> str:
    return ",".join(f"{numero}:{parcelas}" for numero, parcelas in planos)


def _ler_planos(texto: str) -> list[tuple[str, int]]:
    pares = (parte.split(":") for parte in texto.split(",") if parte)
    return [(numero, int(parcelas)) for numero, parcelas in pares]


class Fila:
    def __init__(self, caminho: str | Path):
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(caminho, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(_ESQUEMA)

    def fechar(self) -> None:
        self.db.close()

    def importar(self, contatos: list[Contato]) -> dict[str, int]:
        """Carrega a planilha na fila. Pode rodar de novo com planilha mais nova.

        Quem já foi processado não é tocado. Contato pendente que ficou sem
        ninguém é cancelado: é o caso de quem pagou depois da extração.
        """
        resumo = {"novos": 0, "agrupados": 0, "cancelados": 0}

        self.db.execute("BEGIN IMMEDIATE")
        try:
            for p in contatos:
                self.db.execute(
                    """INSERT INTO contatos VALUES (?,?,?,?,?,?)
                       ON CONFLICT (cpf) DO UPDATE SET nome=excluded.nome,
                       valor=excluded.valor, planos=excluded.planos,
                       maior_atraso=excluded.maior_atraso, filial=excluded.filial""",
                    (
                        p.cpf, p.nome, p.valor, _gravar_planos(p.planos),
                        p.maior_atraso.isoformat() if p.maior_atraso else None,
                        p.filial,
                    ),
                )
            for canal in CANAIS:
                self._sincronizar(canal, contatos, resumo)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return resumo

    def _sincronizar(self, canal: str, contatos: list[Contato], resumo: dict) -> None:
        # Quem já foi cobrado neste canal não entra em contato novo: um telefone
        # atualizado na planilha não pode virar uma segunda cobrança.
        atendidos = {
            l["cpf"]
            for l in self.db.execute(
                """SELECT l.cpf FROM envio_contatos l JOIN envios e ON e.id = l.envio_id
                   WHERE e.canal=? AND l.ativo=1 AND e.status IN (?,?,?)""",
                (canal, ENVIADO, ENVIANDO, INCERTO),
            )
        }

        # A prioridade é da pessoa: sobrevive à recarga e a um celular atualizado.
        urgentes = {
            l["cpf"]
            for l in self.db.execute("SELECT cpf FROM prioridades WHERE canal=?", (canal,))
        }

        desejado: dict[str, list[str]] = {}
        prioridade: dict[str, int] = {}
        for posicao, p in enumerate(contatos, start=1):
            destino = p.email if canal == "email" else p.celular
            if destino and p.cpf not in atendidos:
                desejado.setdefault(destino, []).append(p.cpf)
                prioridade.setdefault(destino, posicao)
                if p.cpf in urgentes and prioridade[destino] >= 0:
                    prioridade[destino] -= URGENTE

        for linha in self.db.execute(
            "SELECT id, destino FROM envios WHERE canal=? AND status=?", (canal, PENDENTE)
        ).fetchall():
            if linha["destino"] not in desejado:
                self.finalizar(linha["id"], CANCELADO, SAIU_DA_PLANILHA)
                resumo["cancelados"] += 1

        for destino, cpfs in desejado.items():
            atual = self.db.execute(
                "SELECT id, status, detalhe FROM envios WHERE canal=? AND destino=?",
                (canal, destino),
            ).fetchone()

            if atual is None:
                id_envio = self.db.execute(
                    """INSERT INTO envios (canal, destino, status, prioridade, atualizado_em)
                       VALUES (?,?,?,?,?)""",
                    (canal, destino, PENDENTE, prioridade[destino], _agora()),
                ).lastrowid
                resumo["novos"] += 1
            else:
                # Cancelado pela lista nao_enviar nunca reabre.
                voltou = atual["status"] == CANCELADO and atual["detalhe"] == SAIU_DA_PLANILHA
                if atual["status"] != PENDENTE and not voltou:
                    continue
                id_envio = atual["id"]
                self.db.execute(
                    "UPDATE envios SET status=?, detalhe='', prioridade=?, atualizado_em=? "
                    "WHERE id=?",
                    (PENDENTE, prioridade[destino], _agora(), id_envio),
                )
                self.db.execute("DELETE FROM envio_contatos WHERE envio_id=?", (id_envio,))

            self.db.executemany(
                "INSERT INTO envio_contatos (envio_id, cpf) VALUES (?,?)",
                [(id_envio, cpf) for cpf in cpfs],
            )
            if len(cpfs) > 1:
                resumo["agrupados"] += 1

    def sairiam_da_fila(self, contatos: list[Contato]) -> tuple[int, int]:
        """(quantos pendentes esta planilha cancelaria, total de pendentes)."""
        ficam = {("email", p.email) for p in contatos}
        ficam |= {(c, p.celular) for p in contatos for c in ("whatsapp", "sms")}
        pendentes = [
            (l["canal"], l["destino"])
            for l in self.db.execute(
                "SELECT canal, destino FROM envios WHERE status=?", (PENDENTE,)
            )
        ]
        return sum(1 for chave in pendentes if chave not in ficam), len(pendentes)

    def priorizar(self, canal: str, cpfs: list[str], motivo: str) -> dict[str, int]:
        """Põe estas pessoas na frente da fila, sem criar nem cancelar envio.

        Só muda a ordem das linhas que já existem, então a trava de duplicidade
        continua valendo. Quem já recebeu, ou pode ter recebido, fica como está.
        """
        resumo = {"na_frente": 0, "ja_avisados": 0, "sem_contato": 0, "fora_da_campanha": 0}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for cpf in cpfs:
                linhas = self.db.execute(
                    """SELECT e.id, e.status, e.prioridade FROM envio_contatos l
                       JOIN envios e ON e.id = l.envio_id
                       WHERE e.canal=? AND l.cpf=? AND l.ativo=1""",
                    (canal, cpf),
                ).fetchall()
                situacoes = {l["status"] for l in linhas}
                if situacoes & {ENVIADO, ENVIANDO, INCERTO}:
                    resumo["ja_avisados"] += 1
                elif PENDENTE in situacoes:
                    self.db.execute(
                        "INSERT OR REPLACE INTO prioridades VALUES (?,?,?)", (canal, cpf, motivo)
                    )
                    for linha in linhas:
                        if linha["status"] == PENDENTE and linha["prioridade"] >= 0:
                            self.db.execute(
                                "UPDATE envios SET prioridade=? WHERE id=?",
                                (linha["prioridade"] - URGENTE, linha["id"]),
                            )
                    resumo["na_frente"] += 1
                elif self.db.execute("SELECT 1 FROM contatos WHERE cpf=?", (cpf,)).fetchone():
                    resumo["sem_contato"] += 1
                else:
                    resumo["fora_da_campanha"] += 1
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return resumo

    def urgentes(self, canal: str) -> int:
        """Mensagens com prioridade que ainda não saíram."""
        return self.db.execute(
            "SELECT COUNT(*) FROM envios WHERE canal=? AND status=? AND prioridade<0",
            (canal, PENDENTE),
        ).fetchone()[0]

    def marcar_devolvido(self, destino: str, detalhe: str) -> bool:
        """Registra um e-mail que saiu e voltou. Só vale para o que consta como enviado."""
        return bool(self.db.execute(
            "UPDATE envios SET status=?, detalhe=? WHERE canal='email' AND destino=? AND status=?",
            (DEVOLVIDO, detalhe[:500], destino, ENVIADO),
        ).rowcount)

    def recuperar_interrompidos(self, canal: str) -> int:
        """`enviando` no início de uma execução significa que a anterior caiu."""
        return self.db.execute(
            "UPDATE envios SET status=?, detalhe=?, atualizado_em=? "
            "WHERE canal=? AND status=?",
            (INCERTO, "execucao interrompida durante o envio", _agora(), canal, ENVIANDO),
        ).rowcount

    def reservar(self, canal: str) -> Item | None:
        """Pega o próximo da fila. O UPDATE condicional impede envio em dobro,
        mesmo que duas execuções estejam abertas por engano."""
        while True:
            linha = self.db.execute(
                "SELECT id FROM envios WHERE canal=? AND status=? "
                "ORDER BY prioridade LIMIT 1",
                (canal, PENDENTE),
            ).fetchone()
            if linha is None:
                return None
            pegou = self.db.execute(
                "UPDATE envios SET status=?, atualizado_em=? WHERE id=? AND status=?",
                (ENVIANDO, _agora(), linha["id"], PENDENTE),
            ).rowcount
            if pegou:
                return self._item(linha["id"])

    def _item(self, id_envio: int) -> Item:
        envio = self.db.execute(
            "SELECT id, canal, destino FROM envios WHERE id=?", (id_envio,)
        ).fetchone()
        pessoas = self.db.execute(
            """SELECT c.* FROM envio_contatos l JOIN contatos c ON c.cpf = l.cpf
               WHERE l.envio_id=? AND l.ativo=1 ORDER BY c.valor DESC, c.nome""",
            (id_envio,),
        ).fetchall()
        return Item(
            id=envio["id"],
            canal=envio["canal"],
            destino=envio["destino"],
            contatos=[
                Contato(
                    cpf=p["cpf"],
                    nome=p["nome"],
                    valor=p["valor"],
                    planos=_ler_planos(p["planos"]),
                    maior_atraso=(
                        datetime.fromisoformat(p["maior_atraso"]) if p["maior_atraso"] else None
                    ),
                    filial=p["filial"],
                )
                for p in pessoas
            ],
        )

    def amostra(self, canal: str, quantos: int, agrupados: bool = False) -> list[Item]:
        filtro = (
            "AND (SELECT COUNT(*) FROM envio_contatos l WHERE l.envio_id = e.id) > 1"
            if agrupados
            else ""
        )
        linhas = self.db.execute(
            f"SELECT e.id FROM envios e WHERE e.canal=? AND e.status=? {filtro} "
            "ORDER BY e.prioridade LIMIT ?",
            (canal, PENDENTE, quantos),
        ).fetchall()
        return [self._item(l["id"]) for l in linhas]

    def excluir_contato(self, id_envio: int, cpf: str) -> None:
        """Tira uma pessoa da mensagem sem perder o registro de que ela estava ali."""
        self.db.execute(
            "UPDATE envio_contatos SET ativo=0 WHERE envio_id=? AND cpf=?", (id_envio, cpf)
        )

    def gravar_texto(self, id_envio: int, texto: str) -> None:
        self.db.execute("UPDATE envios SET texto=? WHERE id=?", (texto, id_envio))

    def finalizar(self, id_envio: int, status: str, detalhe: str = "") -> None:
        self.db.execute(
            "UPDATE envios SET status=?, detalhe=?, atualizado_em=? WHERE id=?",
            (status, detalhe[:500], _agora(), id_envio),
        )

    def devolver(self, id_envio: int) -> None:
        """Só para quando há certeza de que nada saiu."""
        self.finalizar(id_envio, PENDENTE)

    def liberar_incertos(self, canal: str) -> int:
        return self.db.execute(
            "UPDATE envios SET status=?, detalhe='', atualizado_em=? "
            "WHERE canal=? AND status=?",
            (PENDENTE, _agora(), canal, INCERTO),
        ).rowcount

    def enviados_hoje(self, canal: str) -> int:
        hoje = datetime.now().date().isoformat()
        return self.db.execute(
            "SELECT COUNT(*) FROM envios WHERE canal=? AND status=? AND atualizado_em>=?",
            (canal, ENVIADO, hoje),
        ).fetchone()[0]

    def contagem(self) -> dict[str, dict[str, int]]:
        saida: dict[str, dict[str, int]] = {c: {} for c in CANAIS}
        for l in self.db.execute(
            "SELECT canal, status, COUNT(*) n FROM envios GROUP BY canal, status"
        ):
            saida[l["canal"]][l["status"]] = l["n"]
        return saida

    def pessoas_pendentes(self, canal: str | None = None) -> int:
        """Pessoas com ao menos uma mensagem por sair, em um canal ou em qualquer um."""
        return self.db.execute(
            """SELECT COUNT(DISTINCT l.cpf) FROM envio_contatos l
               JOIN envios e ON e.id = l.envio_id
               WHERE l.ativo=1 AND e.status=:status
                 AND (:canal IS NULL OR e.canal=:canal)""",
            {"status": PENDENTE, "canal": canal},
        ).fetchone()[0]

    def mapa(self, canal: str) -> list[str]:
        """Situação de cada contato, na ordem da fila."""
        return [
            l["status"]
            for l in self.db.execute(
                "SELECT status FROM envios WHERE canal=? ORDER BY prioridade, id", (canal,)
            )
        ]

    def listar(
        self,
        canal: str,
        status: str | None = None,
        busca: str = "",
        limite: int = 50,
        inicio: int = 0,
    ) -> dict:
        """Contatos para a tela: uma linha por mensagem, com os nomes e inscrições."""
        filtro = "WHERE e.canal=:canal AND (:status IS NULL OR e.status=:status)"
        tem_busca = (
            "AND (e.destino LIKE :busca OR EXISTS (SELECT 1 FROM envio_contatos l2 "
            "JOIN contatos c2 ON c2.cpf = l2.cpf WHERE l2.envio_id = e.id "
            "AND (c2.nome LIKE :busca OR c2.planos LIKE :busca OR c2.cpf LIKE :busca)))"
        )
        termos = {
            "canal": canal, "status": status, "busca": f"%{busca.strip()}%",
            "limite": limite, "inicio": inicio,
        }
        condicao = f"{filtro} {tem_busca if busca.strip() else ''}"
        total = self.db.execute(
            f"SELECT COUNT(*) FROM envios e {condicao}", termos
        ).fetchone()[0]
        linhas = self.db.execute(
            f"""SELECT e.id, e.destino, e.status, e.detalhe, e.atualizado_em
                FROM envios e {condicao}
                ORDER BY e.prioridade, e.id LIMIT :limite OFFSET :inicio""",
            termos,
        ).fetchall()
        itens = []
        for linha in linhas:
            pessoas = self._item(linha["id"]).contatos
            itens.append({
                **dict(linha),
                "pessoas": [
                    {"nome": p.nome, "planos": p.planos, "parcelas": p.parcelas} for p in pessoas
                ],
            })
        return {"total": total, "itens": itens}

    def recentes(self, canal: str, quantos: int = 8) -> list[dict]:
        """Os últimos contatos processados, do mais novo para o mais antigo."""
        linhas = self.db.execute(
            """SELECT id, destino, status, detalhe, atualizado_em FROM envios
               WHERE canal=? AND status NOT IN (?, ?)
               ORDER BY atualizado_em DESC, id DESC LIMIT ?""",
            (canal, PENDENTE, CANCELADO, quantos),
        ).fetchall()
        return [
            {**dict(l), "nomes": [p.nome for p in self._item(l["id"]).contatos]} for l in linhas
        ]

    def relatorio(self) -> list[sqlite3.Row]:
        """Uma linha por pessoa em cada mensagem."""
        return self.db.execute(
            """SELECT e.canal, e.status, e.detalhe, e.atualizado_em, e.destino,
                      l.ativo AS incluido, c.cpf, c.nome, c.valor, c.planos, c.filial
               FROM envios e
               JOIN envio_contatos l ON l.envio_id = e.id
               JOIN contatos c ON c.cpf = l.cpf
               ORDER BY e.canal, e.prioridade"""
        ).fetchall()
