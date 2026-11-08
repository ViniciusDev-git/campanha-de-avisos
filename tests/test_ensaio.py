"""A trava entre o ensaio e o disparo real, testada pelos comandos de verdade."""

from datetime import datetime

import pytest

import disparo.operacao as O
from disparo import fila as F
from disparo.ambiente import abrir_fila, caminho
from disparo.fila import Fila
from disparo.motor import Resultado
from disparo.planilha import Contato
from disparo.ritmo import Perfil


def _planilha(caminho, cpfs):
    import openpyxl

    from disparo.planilha import COLUNAS

    livro = openpyxl.Workbook()
    aba = livro.active
    aba.append(list(COLUNAS.values()))
    for i in cpfs:
        aba.append([1000 + i, f"Pessoa {i}", 100.0 + i, 2, datetime(2026, 1, 10), "Filial",
                    f"{i:011d}", "", f"119111{i:05d}", f"p{i}@exemplo.com"])
    livro.save(caminho)
    return caminho


def test_lista_parcial_nao_cancela_a_campanha_e_prioriza_sem_tirar_ninguem(cfg, tmp_path):
    cfg["campanha"].update({"valor_minimo": 1.0, "vencido_ate": "2026-10-31",
                            "saida": str(tmp_path / "saida")})
    O.preparar(cfg, _planilha(tmp_path / "toda.xlsx", range(1, 31)))
    parcial = _planilha(tmp_path / "parcial.xlsx", [29, 30])

    with pytest.raises(O.SaidaEmMassa):
        O.preparar(cfg, parcial)
    fila = abrir_fila(cfg)
    assert fila.contagem()["whatsapp"] == {F.PENDENTE: 30}
    fila.fechar()

    assert O.priorizar(cfg, parcial)["na_frente"] == 2
    O.preparar(cfg, tmp_path / "toda.xlsx")
    fila = abrir_fila(cfg)
    assert fila.contagem()["whatsapp"] == {F.PENDENTE: 30}
    assert fila.urgentes("whatsapp") == 2
    primeiros = {fila.reservar("whatsapp").destino for _ in range(2)}
    fila.fechar()
    assert primeiros == {"5511911100029", "5511911100030"}


class EmailFalso:
    def __init__(self, status=F.ENVIADO):
        self.status = status
        self.destinos = []

    def enviar(self, destino, conteudo):
        self.destinos.append(destino)
        return Resultado(self.status)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    pasta = tmp_path / "m"
    pasta.mkdir()
    (pasta / "email_assunto.txt").write_text("Aviso", encoding="utf-8")
    (pasta / "email.html").write_text("<p>Oi {{primeiro_nome}}</p>", encoding="utf-8")
    (tmp_path / "t.csv").write_text(
        "nome;celular;email\nEquipe;;equipe@exemplo.com\n", encoding="utf-8"
    )
    instantaneo = Perfil((0, 0), (10**9, 10**9), (0, 0))
    monkeypatch.setitem(O.PERFIS, "teste", instantaneo)
    monkeypatch.setitem(O.PERFIS, "email", instantaneo)
    monkeypatch.setattr(O, "manter_acordado", lambda: None)

    config = {
        "campanha": {
            "banco": str(tmp_path / "dados" / "c.sqlite3"), "mensagens": str(pasta),
            "nao_enviar": str(tmp_path / "n.txt"), "parar": str(tmp_path / "PARAR"),
            "teste_interno": str(tmp_path / "t.csv"),
        },
        "email": {
            "janela_inicio": "00:00", "janela_fim": "23:59",
            "dias": list(range(7)), "limite_diario": 100,
        },
    }
    fila = abrir_fila(config)
    fila.importar([
        Contato(cpf="00000000001", nome="MARIA EXEMPLO", valor=10.0, planos=[("1", 1)],
                email="maria@exemplo.com")
    ])
    fila.fechar()
    return config


def usar(monkeypatch, cliente):
    monkeypatch.setattr(O, "cliente_email", lambda *_: cliente)


def enviar(cfg):
    O.disparar(cfg, "email", aguardar_janela=False, log=lambda _: None)


def ensaiar(cfg):
    return 0 if O.ensaiar(cfg, "email", log=lambda _: None)["aprovado"] else 1


def pendentes(cfg):
    fila = Fila(cfg["campanha"]["banco"])
    n = fila.contagem()["email"].get(F.PENDENTE, 0)
    fila.fechar()
    return n


def test_disparo_direto_sem_ensaio(cfg, monkeypatch):
    cliente = EmailFalso()
    usar(monkeypatch, cliente)
    enviar(cfg)
    assert cliente.destinos == ["maria@exemplo.com"] and pendentes(cfg) == 0


def test_ensaio_so_alcanca_a_lista_interna(cfg, monkeypatch):
    cliente = EmailFalso()
    usar(monkeypatch, cliente)
    assert ensaiar(cfg) == 0
    assert cliente.destinos == ["equipe@exemplo.com"]
    assert pendentes(cfg) == 1


def test_disparo_depois_do_ensaio(cfg, monkeypatch):
    cliente = EmailFalso()
    usar(monkeypatch, cliente)
    ensaiar(cfg)
    enviar(cfg)
    assert cliente.destinos == ["equipe@exemplo.com", "maria@exemplo.com"]


def test_ensaio_com_falha_nao_consta_mas_nao_bloqueia(cfg, monkeypatch):
    usar(monkeypatch, EmailFalso(F.FALHOU))
    assert ensaiar(cfg) == 1
    assert not O.ensaio_vale(cfg, "email")
    cliente = EmailFalso()
    usar(monkeypatch, cliente)
    enviar(cfg)
    assert cliente.destinos == ["maria@exemplo.com"]


def test_mudar_o_texto_tira_o_ensaio_mas_nao_bloqueia(cfg, monkeypatch):
    cliente = EmailFalso()
    usar(monkeypatch, cliente)
    ensaiar(cfg)
    arquivo = caminho(cfg["campanha"]["mensagens"]) / "email.html"
    arquivo.write_text("<p>Outro texto</p>", encoding="utf-8")
    assert not O.ensaio_vale(cfg, "email")
    enviar(cfg)
    assert "maria@exemplo.com" in cliente.destinos


def test_ensaio_repetido_recomeca_do_zero(cfg, monkeypatch):
    cliente = EmailFalso()
    usar(monkeypatch, cliente)
    ensaiar(cfg)
    ensaiar(cfg)
    assert cliente.destinos == ["equipe@exemplo.com"] * 2


def test_dois_canais_aprovados_ao_mesmo_tempo_nao_se_apagam(cfg, monkeypatch):
    """Cada canal grava a própria aprovação; a última gravação não pode apagar a outra."""
    import threading

    pasta = caminho(cfg["campanha"]["mensagens"])
    (pasta / "whatsapp.txt").write_text("Oi {{primeiro_nome}}", encoding="utf-8")
    (caminho(cfg["campanha"]["teste_interno"])).write_text(
        "nome;celular;email" + chr(10) + "Equipe;11987654321;equipe@exemplo.com" + chr(10), encoding="utf-8"
    )
    from disparo.modelos import Modelos

    assinaturas = {c: Modelos(pasta, c).assinatura() for c in ("email", "whatsapp")}
    arquivo = O._ensaios(cfg)

    def gravar(canal):
        with O.TRAVA_ARQUIVOS:
            atuais = O.ler_ensaios(cfg)
            atuais[canal] = assinaturas[canal]
            arquivo.write_text(__import__("json").dumps(atuais), encoding="utf-8")

    linhas = [threading.Thread(target=gravar, args=(c,)) for c in ("email", "whatsapp") * 20]
    [t.start() for t in linhas]
    [t.join() for t in linhas]
    assert O.ler_ensaios(cfg) == assinaturas


def test_ajustes_salvos_em_paralelo_nao_se_perdem(tmp_path):
    import threading

    from disparo.ambiente import salvar_ajustes

    cfg = {"campanha": {"banco": str(tmp_path / "dados" / "c.sqlite3")}}
    linhas = [
        threading.Thread(target=salvar_ajustes, args=(cfg, f"s{i}", {"v": i})) for i in range(30)
    ]
    [t.start() for t in linhas]
    [t.join() for t in linhas]
    gravado = __import__("json").loads((tmp_path / "dados" / "ajustes.json").read_text("utf-8"))
    assert len(gravado) == 30


def test_ensaios_de_dois_canais_rodam_juntos(cfg, monkeypatch):
    """Sem banco próprio por canal, um ensaio apagava o arquivo em uso pelo outro."""
    import threading

    pasta = caminho(cfg["campanha"]["mensagens"])
    (pasta / "whatsapp.txt").write_text("Oi {{primeiro_nome}}", encoding="utf-8")
    caminho(cfg["campanha"]["teste_interno"]).write_text(
        "nome;celular;email" + chr(10) + "Equipe;11987654321;equipe@exemplo.com" + chr(10),
        encoding="utf-8",
    )

    class Canal(EmailFalso):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    usar(monkeypatch, Canal())
    monkeypatch.setattr(O, "cliente_whatsapp", lambda *_, **__: Canal())
    cfg["whatsapp"] = {}
    resultados = {}

    def rodar(canal):
        resultados[canal] = O.ensaiar(cfg, canal, log=lambda _: None)["aprovado"]

    linhas = [threading.Thread(target=rodar, args=(c,)) for c in ("email", "whatsapp")]
    [t.start() for t in linhas]
    [t.join() for t in linhas]
    assert resultados == {"email": True, "whatsapp": True}
    assert set(O.ler_ensaios(cfg)) == {"email", "whatsapp"}
