"""A janela do programa e a ponte entre a interface e o motor.

A interface nunca decide nada que importe: ela pergunta aqui, e as travas moram em
`operacao.py`. Cada canal roda na própria linha de execução, para o e-mail terminar
enquanto o WhatsApp segue no seu ritmo.
"""

from __future__ import annotations

import csv
import os
import sys
import threading
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import fila as F
from . import operacao as O
from . import planilha
from .ambiente import RAIZ, abrir_fila, caminho, carregar_config, janela_de, salvar_ajustes
from .canal_email import gravar_segredo, identificadores, tem_segredo
from .modelos import MARCA_PENDENTE, ModeloInvalido, Modelos, gerar_html_email
from .motor import ParadaObrigatoria
from .planilha import Contato
from .ritmo import CONTA_GOTAS, CONVERSAS_DIA_PADRAO, PERFIS

CANAIS_ATIVOS = ("email", "whatsapp")
EXEMPLO = [
    Contato(cpf="1", nome="MARIA APARECIDA DE SOUZA", planos=[("12345", 3), ("67890", 1)]),
    Contato(cpf="2", nome="JOÃO CARLOS DE SOUZA", planos=[("11111", 2)]),
]


@dataclass
class Tarefa:
    canal: str
    tipo: str
    inicio: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    fim: str = ""
    parando: bool = False
    resultado: dict = field(default_factory=dict)
    erro: str = ""

    @property
    def ativa(self) -> bool:
        return not self.fim


class Ponte:
    """Tudo aqui é chamado pelo JavaScript e devolve dados simples."""

    def __init__(self) -> None:
        self._tarefas: dict[str, Tarefa] = {}
        self._registro: deque[dict] = deque(maxlen=200)
        self._trava = threading.Lock()
        self._janela = None

    # -- leitura ------------------------------------------------------------

    def estado(self) -> dict:
        cfg = carregar_config()
        fila = abrir_fila(cfg)
        try:
            contagem = fila.contagem()
            canais = {}
            for canal in F.CANAIS:
                situacoes = contagem[canal]
                tarefa = self._tarefas.get(canal)
                canais[canal] = {
                    "contagem": situacoes,
                    "total": sum(
                        n for s, n in situacoes.items() if s != F.CANCELADO
                    ),
                    "enviados_hoje": fila.enviados_hoje(canal),
                    "urgentes": fila.urgentes(canal),
                    "texto_definido": self._texto_definido(cfg, canal),
                    "ensaio_aprovado": O.ensaio_vale(cfg, canal),
                    "tarefa": self._tarefa_dict(tarefa),
                    "recentes": fila.recentes(canal),
                }
        finally:
            fila.fechar()

        whatsapp = cfg["whatsapp"]
        email = cfg["email"]
        tenant, cliente = identificadores(email)
        agora = datetime.now()
        importacao = O.ultima_importacao(cfg)
        if importacao:
            importacao = {k: v for k, v in importacao.items() if k != "retidos_lista"}
        return {
            "agora": agora.isoformat(timespec="seconds"),
            "importacao": importacao,
            "canais": canais,
            "internos": len(self._ler_internos(cfg)),
            "ajustes": {
                "responder_para": email["responder_para"],
                "remetente": email["remetente"],
                "ritmo": whatsapp["ritmo"],
                "conversas_dia": int(whatsapp.get("conversas_dia", CONVERSAS_DIA_PADRAO)),
                "janela_inicio": whatsapp["janela_inicio"],
                "janela_fim": whatsapp["janela_fim"],
                "tenant_id": tenant,
                "client_id": cliente,
                "segredo_gravado": tem_segredo(email),
                "valor_minimo": cfg["campanha"]["valor_minimo"],
                "corte_hoje": O.corte(cfg).isoformat(),
            },
            "janela_aberta": janela_de(whatsapp).aberta(agora),
            "ritmos": {n: PERFIS[n].por_hora() for n in ("prudente", "padrao", "acelerado")},
            "registro": list(self._registro)[-40:],
        }

    def mapa(self, canal: str) -> list[str]:
        cfg = carregar_config()
        fila = abrir_fila(cfg)
        try:
            return fila.mapa(canal)
        finally:
            fila.fechar()

    def listar(self, canal: str, status=None, busca: str = "", inicio: int = 0) -> dict:
        cfg = carregar_config()
        fila = abrir_fila(cfg)
        try:
            return fila.listar(canal, status or None, busca, 50, inicio)
        finally:
            fila.fechar()

    def retidos(self) -> list[dict]:
        importacao = O.ultima_importacao(carregar_config())
        return importacao["retidos_lista"] if importacao else []

    # -- planilha -----------------------------------------------------------

    def escolher_planilha(self) -> str:
        import webview

        arquivos = self._janela.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("Planilha do Excel (*.xlsx)",)
        )
        return arquivos[0] if arquivos else ""

    def carregar_planilha(self, arquivo: str, forcar: bool = False) -> dict:
        if self._alguma_ativa():
            return {"erro": "Aguarde os envios em andamento pararem antes de trocar a planilha."}

        def carregar() -> dict:
            try:
                return O.preparar(carregar_config(), arquivo, forcar)
            except O.SaidaEmMassa as erro:
                return {"erro": str(erro), "arquivo_parcial": arquivo}

        return self._seguro(carregar)

    def priorizar_planilha(self, arquivo: str) -> dict:
        if self._alguma_ativa():
            return {"erro": "Aguarde os envios em andamento pararem antes de mudar a fila."}
        return self._seguro(lambda: O.priorizar(carregar_config(), arquivo))

    # -- textos -------------------------------------------------------------

    def _pasta(self, cfg: dict) -> Path:
        return caminho(cfg["campanha"]["mensagens"])

    def _texto_definido(self, cfg: dict, canal: str) -> bool:
        try:
            Modelos(self._pasta(cfg), canal)
        except ModeloInvalido:
            return False
        return True

    def _ler_arquivo(self, arquivo: Path) -> str:
        if not arquivo.exists():
            return ""
        texto = arquivo.read_text(encoding="utf-8").strip()
        return "" if MARCA_PENDENTE in texto else texto

    def ler_texto(self, canal: str) -> dict:
        pasta = self._pasta(carregar_config())
        if canal == "email":
            return {
                "assunto": self._ler_arquivo(pasta / "email_assunto.txt"),
                "texto": self._ler_arquivo(pasta / "email_corpo.txt"),
            }
        return {"texto": self._ler_arquivo(pasta / f"{canal}.txt")}

    def salvar_texto(self, canal: str, texto: str, assunto: str = "") -> dict:
        def salvar() -> dict:
            cfg = carregar_config()
            pasta = self._pasta(cfg)
            pasta.mkdir(exist_ok=True)
            if canal == "email":
                (pasta / "email_assunto.txt").write_text(assunto.strip(), encoding="utf-8")
                (pasta / "email_corpo.txt").write_text(texto.strip(), encoding="utf-8")
                (pasta / "email.html").write_text(
                    gerar_html_email(texto, cfg["campanha"].get("empresa", "")), encoding="utf-8"
                )
            else:
                (pasta / f"{canal}.txt").write_text(texto.strip(), encoding="utf-8")
            Modelos(pasta, canal)
            return {"ok": True}

        return self._seguro(salvar)

    def previa(self, canal: str, texto: str, assunto: str = "") -> dict:
        """Mostra o texto com pessoas fictícias, sem gravar nada."""
        from .modelos import checar_modelo, preencher, variaveis

        try:
            checar_modelo(texto)
            if canal == "email":
                checar_modelo(assunto)
        except ModeloInvalido as erro:
            return {"erro": str(erro)}
        dados_um = variaveis(EXEMPLO[:1])
        dados_dois = variaveis(EXEMPLO)
        return {
            "um": preencher(texto, dados_um),
            "dois": preencher(texto, dados_dois),
            "assunto": preencher(assunto, dados_um),
        }

    # -- lista interna ------------------------------------------------------

    def _ler_internos(self, cfg: dict) -> list[dict]:
        arquivo = caminho(cfg["campanha"]["teste_interno"])
        if not arquivo.exists():
            return []
        with open(arquivo, encoding="utf-8-sig", newline="") as f:
            return [
                {k: (linha.get(k) or "").strip() for k in ("nome", "celular", "email")}
                for linha in csv.DictReader(f, delimiter=";")
                if any((v or "").strip() for v in linha.values())
            ]

    def internos(self) -> list[dict]:
        return self._ler_internos(carregar_config())

    def salvar_internos(self, lista: list[dict]) -> dict:
        def salvar() -> dict:
            arquivo = caminho(carregar_config()["campanha"]["teste_interno"])
            with open(arquivo, "w", newline="", encoding="utf-8") as f:
                escrita = csv.writer(f, delimiter=";")
                escrita.writerow(["nome", "celular", "email"])
                for p in lista:
                    if any(str(p.get(k, "")).strip() for k in ("nome", "celular", "email")):
                        escrita.writerow(
                            [str(p.get(k, "")).strip() for k in ("nome", "celular", "email")]
                        )
            planilha.ler_internos(arquivo)
            return {"ok": True}

        return self._seguro(salvar)

    # -- ajustes ------------------------------------------------------------

    def salvar_ajuste(self, secao: str, valores: dict) -> dict:
        return self._seguro(lambda: (salvar_ajustes(carregar_config(), secao, valores), {"ok": True})[1])

    def gravar_segredo(self, segredo: str) -> dict:
        def gravar() -> dict:
            gravar_segredo(carregar_config()["email"], segredo.strip())
            return {"ok": True}

        return self._seguro(gravar)

    def nao_enviar(self) -> list[str]:
        arquivo = caminho(carregar_config()["campanha"]["nao_enviar"])
        if not arquivo.exists():
            return []
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
        return [l.strip() for l in linhas if l.strip() and not l.strip().startswith("#")]

    def adicionar_nao_enviar(self, valor: str) -> dict:
        def adicionar() -> dict:
            arquivo = caminho(carregar_config()["campanha"]["nao_enviar"])
            with open(arquivo, "a", encoding="utf-8") as f:
                f.write(f"{valor.strip()}\n")
            return {"ok": True}

        return self._seguro(adicionar)

    # -- execução -----------------------------------------------------------

    def iniciar_ensaio(self, canal: str) -> dict:
        return self._iniciar(canal, "ensaio", lambda cfg, log: O.ensaiar(cfg, canal, log))

    def iniciar_piloto(self, canal: str, quantos: int = 5, ritmo: str | None = None) -> dict:
        # O teste com poucas pessoas não precisa levar horas: usa o intervalo prudente.
        if ritmo == CONTA_GOTAS:
            ritmo = "prudente"
        return self._iniciar(
            canal, "piloto",
            lambda cfg, log: self._balanco(
                O.disparar(
                    cfg, canal, maximo=int(quantos), ritmo=ritmo, aguardar_janela=False, log=log
                )
            ),
        )

    def iniciar_disparo(self, canal: str, ritmo: str | None = None) -> dict:
        return self._iniciar(
            canal, "disparo",
            lambda cfg, log: self._balanco(O.disparar(cfg, canal, ritmo=ritmo, log=log)),
        )

    def parar(self, canal: str) -> dict:
        tarefa = self._tarefas.get(canal)
        if tarefa and tarefa.ativa:
            tarefa.parando = True
            O.arquivo_parar(carregar_config(), canal).write_text("", encoding="utf-8")
        return {"ok": True}

    def liberar_incertos(self, canal: str) -> dict:
        cfg = carregar_config()
        fila = abrir_fila(cfg)
        try:
            return {"liberados": fila.liberar_incertos(canal)}
        finally:
            fila.fechar()

    def _balanco(self, balanco) -> dict:
        return {
            "enviados": balanco.enviados,
            "outros": balanco.outros,
            "motivo": balanco.motivo_parada,
        }

    def _iniciar(self, canal: str, tipo: str, trabalho) -> dict:
        with self._trava:
            atual = self._tarefas.get(canal)
            if atual and atual.ativa:
                return {"erro": "Este canal já está em andamento."}
            tarefa = Tarefa(canal, tipo)
            self._tarefas[canal] = tarefa

        def anotar(mensagem: str) -> None:
            self._registro.append({
                "hora": datetime.now().strftime("%H:%M:%S"),
                "canal": canal,
                "texto": str(mensagem),
            })

        def rodar() -> None:
            try:
                tarefa.resultado = trabalho(carregar_config(), anotar)
            except (O.Recusado, ParadaObrigatoria, ModeloInvalido, planilha.PlanilhaInvalida) as erro:
                tarefa.erro = str(erro)
            except Exception as erro:  # nunca deixar a tela sem resposta
                tarefa.erro = f"Erro inesperado: {erro}"
                self._anotar_erro()
            finally:
                tarefa.fim = datetime.now().isoformat(timespec="seconds")

        threading.Thread(target=rodar, name=f"tarefa-{canal}", daemon=True).start()
        return {"ok": True}

    def _tarefa_dict(self, tarefa: Tarefa | None) -> dict | None:
        if tarefa is None:
            return None
        return {
            "tipo": tarefa.tipo,
            "inicio": tarefa.inicio,
            "fim": tarefa.fim,
            "ativa": tarefa.ativa,
            "parando": tarefa.parando,
            "resultado": tarefa.resultado,
            "erro": tarefa.erro,
        }

    def _alguma_ativa(self) -> bool:
        return any(t.ativa for t in self._tarefas.values())

    # -- arquivos -----------------------------------------------------------

    def exportar_relatorio(self) -> dict:
        def exportar() -> dict:
            cfg = carregar_config()
            saida = caminho(cfg["campanha"]["saida"])
            saida.mkdir(exist_ok=True)
            arquivo = saida / f"relatorio-{datetime.now():%Y%m%d-%H%M%S}.csv"
            fila = abrir_fila(cfg)
            try:
                linhas = fila.relatorio()
            finally:
                fila.fechar()
            with open(arquivo, "w", newline="", encoding="utf-8-sig") as f:
                escrita = csv.writer(f, delimiter=";")
                if linhas:
                    escrita.writerow(linhas[0].keys())
                escrita.writerows(tuple(l) for l in linhas)
            return {"arquivo": str(arquivo), "linhas": len(linhas)}

        return self._seguro(exportar)

    def abrir_pasta_saida(self) -> dict:
        pasta = caminho(carregar_config()["campanha"]["saida"])
        pasta.mkdir(exist_ok=True)
        os.startfile(pasta)  # noqa: S606
        return {"ok": True}

    # -- apoio --------------------------------------------------------------

    def _seguro(self, trabalho) -> dict:
        try:
            return trabalho()
        except (O.Recusado, ParadaObrigatoria, ModeloInvalido, planilha.PlanilhaInvalida) as erro:
            return {"erro": str(erro)}
        except Exception as erro:
            self._anotar_erro()
            return {"erro": f"Não foi possível concluir: {erro}"}

    def _anotar_erro(self) -> None:
        pasta = RAIZ / "saida"
        pasta.mkdir(exist_ok=True)
        with open(pasta / "erros.log", "a", encoding="utf-8") as f:
            f.write(f"\n{datetime.now().isoformat()}\n{traceback.format_exc()}")


def pasta_interface() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "disparo" / "ui"


def abrir() -> None:
    import webview

    ponte = Ponte()
    janela = webview.create_window(
        "Campanha de Avisos",
        url=str(pasta_interface() / "index.html"),
        js_api=ponte,
        width=1320,
        height=860,
        min_size=(1080, 700),
    )
    ponte._janela = janela

    def ao_fechar() -> bool:
        if not ponte._alguma_ativa():
            return True
        confirmou = janela.create_confirmation_dialog(
            "Há envios em andamento",
            "Se fechar agora, os envios param. Quem já foi avisado continua registrado. Fechar?",
        )
        if confirmou:
            for canal in CANAIS_ATIVOS:
                ponte.parar(canal)
        return bool(confirmou)

    janela.events.closing += ao_fechar
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(RAIZ / "dados" / "janela"))
