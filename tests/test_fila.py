import pytest

from disparo import fila as F
from disparo.fila import Fila
from disparo.planilha import Contato


def pessoa(cpf, cel="5511911112222", email="a@exemplo.com", valor=10.0, planos=None):
    return Contato(cpf=cpf, nome=f"Fulano {cpf}", valor=valor, planos=planos or [("1", 1)],
                   celular=cel, email=email)


@pytest.fixture
def fila(tmp_path):
    f = Fila(tmp_path / "f.sqlite3")
    yield f
    f.fechar()


def test_prioridade_passa_na_frente_sem_criar_nem_cancelar_envio(fila):
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="5511911110002"),
                   pessoa("3", cel="5511911110003")])
    antes = fila.contagem()["whatsapp"]
    resumo = fila.priorizar("whatsapp", ["3"], "devolvidos")
    assert resumo["na_frente"] == 1
    assert fila.contagem()["whatsapp"] == antes
    assert fila.urgentes("whatsapp") == 1
    assert fila.reservar("whatsapp").destino == "5511911110003"
    assert fila.reservar("whatsapp").destino == "5511911110001"


def test_prioridade_repetida_nao_muda_a_ordem_duas_vezes(fila):
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="5511911110002")])
    fila.priorizar("whatsapp", ["2"], "a")
    primeira = fila.db.execute("SELECT prioridade FROM envios WHERE destino='5511911110002'").fetchone()[0]
    fila.priorizar("whatsapp", ["2"], "a")
    segunda = fila.db.execute("SELECT prioridade FROM envios WHERE destino='5511911110002'").fetchone()[0]
    assert primeira == segunda < 0


def test_prioridade_sobrevive_a_recarga_e_ao_celular_novo(fila):
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="5511911110002")])
    fila.priorizar("whatsapp", ["2"], "a")
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="5511911110002")])
    assert fila.reservar("whatsapp").destino == "5511911110002"


def test_prioridade_acompanha_o_celular_atualizado(fila):
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="5511911110002")])
    fila.priorizar("whatsapp", ["2"], "a")
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="5511911110009")])
    assert fila.reservar("whatsapp").destino == "5511911110009"


@pytest.mark.parametrize("status", [F.ENVIADO, F.INCERTO, F.ENVIANDO])
def test_quem_ja_recebeu_ou_pode_ter_recebido_nao_volta_para_a_fila(fila, status):
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="5511911110002")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, status)
    resumo = fila.priorizar("whatsapp", ["1"], "a")
    assert resumo["ja_avisados"] == 1 and resumo["na_frente"] == 0
    assert fila.db.execute("SELECT status FROM envios WHERE id=?", (item.id,)).fetchone()[0] == status
    assert fila.urgentes("whatsapp") == 0


def test_prioridade_separa_sem_whatsapp_e_quem_nao_esta_na_campanha(fila):
    fila.importar([pessoa("1", cel="5511911110001"), pessoa("2", cel="")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, F.SEM_WHATSAPP)
    resumo = fila.priorizar("whatsapp", ["1", "2", "9"], "a")
    assert resumo == {"na_frente": 0, "ja_avisados": 0, "sem_contato": 2, "fora_da_campanha": 1}


def test_devolvido_nao_volta_a_ser_enviado_para_o_mesmo_endereco(fila):
    fila.importar([pessoa("1", email="x@exemplo.com")])
    item = fila.reservar("email")
    fila.finalizar(item.id, F.ENVIADO)
    assert fila.marcar_devolvido("x@exemplo.com", "endereco nao existe")
    fila.importar([pessoa("1", email="x@exemplo.com")])
    assert fila.contagem()["email"] == {F.DEVOLVIDO: 1}


def test_devolvido_com_email_corrigido_entra_na_fila_de_novo(fila):
    fila.importar([pessoa("1", email="x@exemplo.com")])
    fila.finalizar(fila.reservar("email").id, F.ENVIADO)
    fila.marcar_devolvido("x@exemplo.com", "endereco nao existe")
    fila.importar([pessoa("1", email="certo@exemplo.com")])
    assert fila.contagem()["email"] == {F.DEVOLVIDO: 1, F.PENDENTE: 1}


def test_so_marca_devolvido_o_que_consta_como_enviado(fila):
    fila.importar([pessoa("1", email="x@exemplo.com")])
    assert not fila.marcar_devolvido("x@exemplo.com", "motivo")
    assert fila.contagem()["email"] == {F.PENDENTE: 1}


def test_sairiam_da_fila_conta_o_que_a_planilha_cancelaria(fila):
    todos = [pessoa(str(i), cel=f"55119111100{i:02d}", email=f"p{i}@exemplo.com") for i in range(10)]
    fila.importar(todos)
    sairiam, pendentes = fila.sairiam_da_fila(todos[:2])
    assert pendentes == 30 and sairiam == 24


def test_cada_canal_tem_sua_fila(fila):
    fila.importar([pessoa("1")])
    c = fila.contagem()
    assert c["email"][F.PENDENTE] == c["whatsapp"][F.PENDENTE] == c["sms"][F.PENDENTE] == 1


def test_reservar_nunca_entrega_o_mesmo_item_duas_vezes(fila, tmp_path):
    fila.importar([pessoa("1")])
    outra = Fila(tmp_path / "f.sqlite3")
    assert fila.reservar("whatsapp") is not None
    assert outra.reservar("whatsapp") is None
    outra.fechar()


def test_mesmo_celular_vira_uma_mensagem_com_as_duas_pessoas(fila):
    fila.importar([pessoa("1", email="a@exemplo.com", valor=50.0),
                   pessoa("2", email="c@exemplo.com", valor=10.0)])
    assert fila.contagem()["whatsapp"] == {F.PENDENTE: 1}
    assert fila.contagem()["email"] == {F.PENDENTE: 2}
    item = fila.reservar("whatsapp")
    assert [p.cpf for p in item.contatos] == ["1", "2"]
    assert fila.reservar("whatsapp") is None


def test_mesmo_email_tambem_agrupa(fila):
    resumo = fila.importar([pessoa("1", cel="5511911112222"), pessoa("2", cel="5511933334444")])
    assert fila.contagem()["email"] == {F.PENDENTE: 1}
    assert resumo["agrupados"] == 1
    assert len(fila.reservar("email").contatos) == 2


def test_ninguem_fica_de_fora_quando_os_contatos_sao_compartilhados(fila):
    fila.importar([pessoa("1"), pessoa("2")])
    assert fila.pessoas_pendentes() == 2
    assert fila.pessoas_pendentes("whatsapp") == 2


def test_inscricoes_e_parcelas_voltam_por_plano(fila):
    fila.importar([pessoa("1", planos=[("111", 2), ("222", 5)])])
    p = fila.reservar("whatsapp").contatos[0]
    assert p.planos == [("111", 2), ("222", 5)] and p.parcelas == 7


def test_queda_vira_incerto_e_nao_e_reenviada(fila):
    fila.importar([pessoa("1")])
    fila.reservar("whatsapp")
    assert fila.recuperar_interrompidos("whatsapp") == 1
    assert fila.reservar("whatsapp") is None
    assert fila.contagem()["whatsapp"][F.INCERTO] == 1


def test_reimportar_nao_reabre_quem_ja_recebeu(fila):
    fila.importar([pessoa("1")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, F.ENVIADO)
    fila.importar([pessoa("1")])
    assert fila.reservar("whatsapp") is None


def test_telefone_novo_nao_vira_segunda_cobranca(fila):
    fila.importar([pessoa("1", cel="5511911112222")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, F.ENVIADO)
    fila.importar([pessoa("1", cel="5511933334444")])
    assert fila.reservar("whatsapp") is None


def test_incerto_com_telefone_novo_tambem_nao_reenvia(fila):
    fila.importar([pessoa("1", cel="5511911112222")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, F.INCERTO)
    fila.importar([pessoa("1", cel="5511933334444")])
    assert fila.reservar("whatsapp") is None


def test_sem_whatsapp_com_numero_novo_tenta_de_novo(fila):
    fila.importar([pessoa("1", cel="5511911112222")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, F.SEM_WHATSAPP)
    fila.importar([pessoa("1", cel="5511933334444")])
    assert fila.reservar("whatsapp").destino == "5511933334444"


def test_quem_saiu_da_planilha_e_cancelado(fila):
    fila.importar([pessoa("1", "5511911112222", "a@exemplo.com"),
                   pessoa("2", "5511933334444", "c@exemplo.com")])
    resumo = fila.importar([pessoa("1", "5511911112222", "a@exemplo.com")])
    assert resumo["cancelados"] == 3
    assert fila.contagem()["whatsapp"] == {F.PENDENTE: 1, F.CANCELADO: 1}


def test_quem_pagou_sai_da_mensagem_e_o_outro_continua(fila):
    fila.importar([pessoa("1", email="a@exemplo.com"), pessoa("2", email="c@exemplo.com")])
    fila.importar([pessoa("2", email="c@exemplo.com")])
    assert [p.cpf for p in fila.reservar("whatsapp").contatos] == ["2"]


def test_quem_saiu_mas_ja_recebeu_nao_muda(fila):
    fila.importar([pessoa("1")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, F.ENVIADO)
    fila.importar([])
    assert fila.contagem()["whatsapp"][F.ENVIADO] == 1


def test_quem_volta_a_planilha_volta_a_fila(fila):
    fila.importar([pessoa("1")])
    fila.importar([])
    fila.importar([pessoa("1")])
    assert fila.reservar("whatsapp").contatos[0].cpf == "1"


def test_cancelado_pelo_nao_enviar_nunca_reabre(fila):
    fila.importar([pessoa("1")])
    item = fila.reservar("whatsapp")
    fila.finalizar(item.id, F.CANCELADO, "lista nao_enviar")
    fila.importar([pessoa("1")])
    assert fila.reservar("whatsapp") is None


def test_contato_novo_na_planilha_atualiza_pendente(fila):
    fila.importar([pessoa("1", "5511911112222")])
    fila.importar([pessoa("1", "5511933334444")])
    assert fila.reservar("whatsapp").destino == "5511933334444"


def test_relatorio_tem_uma_linha_por_pessoa(fila):
    fila.importar([pessoa("1"), pessoa("2")])
    linhas = [l for l in fila.relatorio() if l["canal"] == "whatsapp"]
    assert sorted(l["cpf"] for l in linhas) == ["1", "2"]
