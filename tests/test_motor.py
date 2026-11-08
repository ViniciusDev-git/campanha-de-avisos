import random
from datetime import datetime, time

import pytest

from disparo import fila as F
from disparo.fila import Fila
from disparo.modelos import ModeloInvalido, Modelos, preencher
from disparo.motor import ParadaObrigatoria, Resultado, ler_supressao, rodar
from disparo.planilha import Contato
from disparo.ritmo import AQUECIMENTO, PERFIS, Janela, Perfil, Ritmo, conta_gotas

JANELA = Janela(time(8), time(19), (0, 1, 2, 3, 4, 5))
QUINTA_10H = datetime(2026, 11, 5, 10, 0)


class Falso:
    def __init__(self, respostas=None):
        self.respostas = list(respostas or [])
        self.enviados = []

    def enviar(self, destino, conteudo):
        self.enviados.append((destino, conteudo["texto"]))
        r = self.respostas.pop(0) if self.respostas else Resultado(F.ENVIADO)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def ambiente(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("Oi {{primeiro_nome}}", encoding="utf-8")
    fila = Fila(tmp_path / "f.sqlite3")
    fila.importar([
        Contato(cpf=f"{i:011d}", nome=f"NOME{i} SILVA", valor=10.0, planos=[("1", 1)],
                celular=f"55119{i:08d}", email="")
        for i in range(1, 31)
    ])
    yield tmp_path, fila
    fila.fechar()


def executar(ambiente, cliente, agora=QUINTA_10H, **extra):
    pasta, fila = ambiente
    esperas = []
    opcoes = dict(
        fila=fila, canal="whatsapp", cliente=cliente,
        modelos=Modelos(pasta, "whatsapp"),
        ritmo=Ritmo(Perfil((1, 1), (1000, 1000), (0, 0))), janela=JANELA,
        limite_diario=1000, arquivo_supressao=pasta / "nao.txt",
        arquivo_parar=pasta / "PARAR", log=lambda _: None,
        agora=lambda: agora, dormir=esperas.append,
    )
    opcoes.update(extra)
    return rodar(**opcoes), esperas


def test_envia_todos_e_personaliza(ambiente):
    cliente = Falso()
    balanco, _ = executar(ambiente, cliente)
    assert balanco.enviados == 30 and balanco.motivo_parada == "fila concluida"
    assert cliente.enviados[0][1].startswith("Oi Nome")
    assert len({d for d, _ in cliente.enviados}) == 30


def test_maximo_serve_de_piloto(ambiente):
    balanco, _ = executar(ambiente, Falso(), maximo=5)
    assert balanco.enviados == 5
    assert ambiente[1].contagem()["whatsapp"][F.PENDENTE] == 25


def test_nao_envia_fora_da_janela(ambiente):
    cliente = Falso()
    balanco, _ = executar(ambiente, cliente, agora=datetime(2026, 11, 5, 19, 0),
                          aguardar_janela=False)
    assert cliente.enviados == [] and balanco.motivo_parada == "fora da janela de envio"


def test_noite_aguarda_a_manha_seguinte():
    assert JANELA.segundos_ate_abrir(datetime(2026, 11, 5, 19, 0)) == 13 * 3600


def test_sabado_noite_pula_domingo():
    assert JANELA.segundos_ate_abrir(datetime(2026, 11, 7, 20, 0)) == 36 * 3600


def test_supressao_por_cpf_e_por_celular_cancela_sem_enviar(ambiente):
    pasta, fila = ambiente
    alvos = fila.amostra("whatsapp", 2)
    (pasta / "nao.txt").write_text(
        f"{alvos[0].contatos[0].cpf} # pagou\n{alvos[1].destino.removeprefix('55')}\n",
        encoding="utf-8",
    )
    cliente = Falso()
    executar(ambiente, cliente)
    enviados = [d for d, _ in cliente.enviados]
    assert len(enviados) == 28
    assert alvos[0].destino not in enviados and alvos[1].destino not in enviados
    assert fila.contagem()["whatsapp"][F.CANCELADO] == 2


def test_lista_de_supressao_aceita_email_e_mascara(tmp_path):
    arq = tmp_path / "n.txt"
    arq.write_text("Fulano@Exemplo.com\n(11) 98765-4321\n", encoding="utf-8")
    lista = ler_supressao(arq)
    assert "fulano@exemplo.com" in lista and "11987654321" in lista


def test_tres_incertos_seguidos_param_tudo(ambiente):
    cliente = Falso([Resultado(F.INCERTO, "x")] * 3)
    balanco, _ = executar(ambiente, cliente)
    assert len(cliente.enviados) == 3 and "sem confirmacao" in balanco.motivo_parada


def test_restricao_para_na_hora_e_devolve_se_nada_saiu(ambiente):
    cliente = Falso([ParadaObrigatoria("restricao", nada_saiu=True)])
    balanco, _ = executar(ambiente, cliente)
    assert balanco.motivo_parada == "restricao" and balanco.enviados == 0
    assert ambiente[1].contagem()["whatsapp"] == {F.PENDENTE: 30}


def test_restricao_apos_tentar_vira_incerto(ambiente):
    cliente = Falso([ParadaObrigatoria("restricao")])
    executar(ambiente, cliente)
    assert ambiente[1].contagem()["whatsapp"][F.INCERTO] == 1


def test_erro_inesperado_nunca_reenvia(ambiente):
    cliente = Falso([RuntimeError("quebrou")])
    executar(ambiente, cliente, maximo=1)
    destinos = [d for d, _ in cliente.enviados]
    assert len(destinos) == len(set(destinos))
    assert ambiente[1].contagem()["whatsapp"][F.INCERTO] == 1


def test_muitos_sem_whatsapp_param_tudo(ambiente):
    cliente = Falso([Resultado(F.SEM_WHATSAPP)] * 30)
    balanco, _ = executar(ambiente, cliente)
    assert len(cliente.enviados) == 20 and "sem WhatsApp" in balanco.motivo_parada


def test_arquivo_parar_interrompe(ambiente):
    pasta, _ = ambiente
    (pasta / "PARAR").write_text("")
    cliente = Falso()
    balanco, _ = executar(ambiente, cliente)
    assert cliente.enviados == [] and "operador" in balanco.motivo_parada


def test_limite_diario(ambiente):
    balanco, _ = executar(ambiente, Falso(), limite_diario=4)
    assert balanco.enviados == 4 and "limite diario" in balanco.motivo_parada


def test_limite_diario_em_conta_gotas_espera_o_dia_seguinte(ambiente):
    """Em vez de parar, dorme até a abertura de amanhã; o relógio do teste não anda,
    então a parada pedida encerra o laço depois da primeira espera longa."""
    pasta, _ = ambiente
    esperas = []

    def dormir(segundos):
        esperas.append(segundos)
        if sum(esperas) > 3600:
            (pasta / "PARAR").write_text("", encoding="utf-8")

    balanco, _ = executar(
        ambiente, Falso(), limite_diario=4, aguardar_limite=True, dormir=dormir
    )
    assert balanco.enviados == 4
    assert balanco.motivo_parada == "parada pedida pelo operador"


def test_conta_gotas_espalha_o_dia_inteiro():
    perfil = conta_gotas(40, JANELA)
    ritmo = Ritmo(perfil, random.Random(3))
    esperas = [ritmo.proxima_espera() for _ in range(40)]
    segundos = (JANELA.fim.hour - JANELA.inicio.hour) * 3600
    assert min(esperas) >= segundos / 40 * 0.6
    assert 0.8 * segundos <= sum(esperas) <= 1.2 * segundos


def test_ritmo_respeita_faixa_aquecimento_e_pausa():
    perfil = PERFIS["padrao"]
    ritmo = Ritmo(perfil, random.Random(1))
    esperas = [ritmo.proxima_espera() for _ in range(200)]
    assert all(e >= perfil.intervalo[0] * 2 for e in esperas[:AQUECIMENTO])
    assert all(e >= perfil.intervalo[0] for e in esperas)
    assert sum(e >= perfil.pausa[0] for e in esperas) >= 4


def test_modelo_pendente_trava(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("PENDENTE_DEFINIR", encoding="utf-8")
    with pytest.raises(ModeloInvalido):
        Modelos(tmp_path, "whatsapp")


def test_variavel_inexistente_trava(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("Oi {{nme}}", encoding="utf-8")
    with pytest.raises(ModeloInvalido):
        Modelos(tmp_path, "whatsapp")


def test_sms_acima_do_limite_trava(tmp_path):
    (tmp_path / "sms.txt").write_text("x" * 161, encoding="utf-8")
    with pytest.raises(ModeloInvalido):
        Modelos(tmp_path, "sms").montar([Contato(cpf="1", nome="A")])


def test_email_escapa_html_do_nome():
    assert preencher("{{nome}}", {"nome": "<b>"}, escapar=True) == "&lt;b&gt;"


MARIA = Contato(cpf="1", nome="MARIA DE EXEMPLO", planos=[("12345", 3), ("67890", 1)])
JOAO = Contato(cpf="2", nome="JOÃO EXEMPLO", planos=[("11111", 1)])


def test_mensagem_de_uma_pessoa(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("{{primeiro_nome}}:\n{{pendencias}}", encoding="utf-8")
    assert Modelos(tmp_path, "whatsapp").montar([JOAO])["texto"] == (
        "João:\nJoão Exemplo | Número de Inscrição: 11111 | 1 parcela em aberto"
    )


def test_numero_compartilhado_lista_todos_os_nomes_e_parcelas(tmp_path):
    (tmp_path / "whatsapp.txt").write_text(
        "{{nome}} / {{numero_inscricao}} / {{parcelas}}\n{{pendencias}}", encoding="utf-8"
    )
    assert Modelos(tmp_path, "whatsapp").montar([MARIA, JOAO])["texto"] == (
        "Maria de Exemplo e João Exemplo / 12345, 67890, 11111 / 5\n"
        "Maria de Exemplo | Número de Inscrição: 12345 | 3 parcelas em aberto\n"
        "Maria de Exemplo | Número de Inscrição: 67890 | 1 parcela em aberto\n"
        "João Exemplo | Número de Inscrição: 11111 | 1 parcela em aberto"
    )


def test_valor_nao_existe_como_variavel(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("Deve {{valor}}", encoding="utf-8")
    with pytest.raises(ModeloInvalido):
        Modelos(tmp_path, "whatsapp")


def test_email_quebra_linha_nas_pendencias(tmp_path):
    (tmp_path / "email_assunto.txt").write_text("Aviso", encoding="utf-8")
    (tmp_path / "email.html").write_text("<p>{{pendencias}}</p>", encoding="utf-8")
    corpo = Modelos(tmp_path, "email").montar([MARIA])["html"]
    assert corpo.count("<br>") == 1


def test_cpf_suprimido_sai_da_mensagem_e_o_outro_recebe(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("{{nome}}", encoding="utf-8")
    (tmp_path / "nao.txt").write_text("00000000001\n", encoding="utf-8")
    fila = Fila(tmp_path / "g.sqlite3")
    fila.importar([
        Contato(cpf="00000000001", nome="ANA EXEMPLO", valor=20.0, planos=[("1", 1)],
                celular="5511911112222"),
        Contato(cpf="00000000002", nome="BETO EXEMPLO", valor=10.0, planos=[("2", 1)],
                celular="5511911112222"),
    ])
    cliente = Falso()
    executar((tmp_path, fila), cliente)
    assert cliente.enviados == [("5511911112222", "Beto Exemplo")]
    incluidos = {l["cpf"]: l["incluido"] for l in fila.relatorio() if l["canal"] == "whatsapp"}
    assert incluidos == {"00000000001": 0, "00000000002": 1}
    fila.fechar()


def test_numero_suprimido_cancela_a_mensagem_inteira(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("{{nome}}", encoding="utf-8")
    (tmp_path / "nao.txt").write_text("11911112222\n", encoding="utf-8")
    fila = Fila(tmp_path / "g.sqlite3")
    fila.importar([
        Contato(cpf="1", nome="ANA", valor=20.0, planos=[("1", 1)], celular="5511911112222"),
        Contato(cpf="2", nome="BETO", valor=10.0, planos=[("2", 1)], celular="5511911112222"),
    ])
    cliente = Falso()
    executar((tmp_path, fila), cliente)
    assert cliente.enviados == []
    fila.fechar()


def test_mudar_o_texto_muda_a_assinatura(tmp_path):
    (tmp_path / "whatsapp.txt").write_text("Texto A", encoding="utf-8")
    antes = Modelos(tmp_path, "whatsapp").assinatura()
    (tmp_path / "whatsapp.txt").write_text("Texto B", encoding="utf-8")
    assert Modelos(tmp_path, "whatsapp").assinatura() != antes
