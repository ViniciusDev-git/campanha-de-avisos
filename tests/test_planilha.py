from datetime import datetime

import openpyxl
import pytest

from disparo import planilha as P

CAB = list(P.COLUNAS.values())


def criar(caminho, linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(CAB)
    for l in linhas:
        ws.append(l)
    wb.save(caminho)
    return caminho


def linha(plano=1.0, nome="MARIA DE EXEMPLO", valor=100.0, parcelas=1.0, cpf=12345678901.0,
          tel=None, cel="11987654321", email="a@exemplo.com", atraso=datetime(2026, 1, 1)):
    return [plano, nome, valor, parcelas, atraso, "Filial", cpf, tel, cel, email]


@pytest.mark.parametrize("bruto,esperado", [
    ("11987654321", "5511987654321"),
    ("(11) 98765-4321", "5511987654321"),
    ("5511987654321", "5511987654321"),
    ("011987654321", "5511987654321"),
    (11987654321.0, "5511987654321"),
])
def test_celular_aceito(bruto, esperado):
    assert P.normalizar_celular(bruto) == (esperado, "")


@pytest.mark.parametrize("bruto", [
    "", None, "0", "1198765432", "1133334444", "11333344445", "20987654321",
    "11999999999", "11911111111",
])
def test_celular_recusado(bruto):
    numero, motivo = P.normalizar_celular(bruto)
    assert numero == "" and motivo


def test_cpf_recupera_zero_a_esquerda():
    assert P.normalizar_cpf(12345.0) == "00000012345"


def test_email_interno_e_invalido_sao_recusados():
    assert P.normalizar_email("Fulano@Exemplo.com ")[0] == "fulano@exemplo.com"
    assert P.normalizar_email("x@exemplo.com", dominios_internos=["exemplo.com"])[0] == ""
    assert P.normalizar_email("x@exemplo.com", dominios_internos=["@Exemplo.com"])[0] == ""
    assert P.normalizar_email("semarroba.com")[0] == ""


def test_dominio_interno_configurado_retem_quem_so_tem_esse_email(tmp_path):
    arq = criar(tmp_path / "a.xlsx", [linha(cel="0", email="ti@exemplo.com")])
    assert P.ler(arq).contatos  # sem domínio interno configurado, o e-mail vale
    leitura = P.ler(arq, dominios_internos=["exemplo.com"])
    assert leitura.contatos == []
    assert leitura.retidos[0][1] == "sem nenhum contato valido"


def test_nome_e_valor_formatados():
    assert P.formatar_nome("MARIA DE FÁTIMA") == "Maria de Fátima"
    assert P.formatar_valor(1234567.5) == "1.234.567,50"


def test_consolida_planos_da_mesma_pessoa(tmp_path):
    arq = criar(tmp_path / "a.xlsx", [
        linha(plano=1.0, valor=100.0, parcelas=2.0, cel="11911112222"),
        linha(plano=2.0, valor=300.5, parcelas=1.0, cel="11933334444",
              atraso=datetime(2025, 1, 1)),
    ])
    leitura = P.ler(arq)
    assert len(leitura.contatos) == 1
    p = leitura.contatos[0]
    assert p.valor == 400.5 and p.parcelas == 3
    assert p.celular == "5511933334444"  # o do plano de maior valor
    assert p.maior_atraso == datetime(2025, 1, 1)
    assert p.planos == [("2", 1), ("1", 2)]


@pytest.mark.parametrize("valor", [0.0, 0.01, 0.99])
def test_valor_irrisorio_fica_retido(tmp_path, valor):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [linha(valor=valor)]))
    assert leitura.contatos == []
    assert leitura.retidos[0][1] == "valor abaixo do minimo"


def test_centavos_num_plano_nao_retem_quem_deve_em_outro(tmp_path):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [
        linha(plano=1.0, valor=0.01), linha(plano=2.0, valor=500.0),
    ]))
    assert len(leitura.contatos) == 1 and leitura.retidos == []


def test_valor_minimo_configuravel(tmp_path):
    arq = criar(tmp_path / "a.xlsx", [linha(valor=0.01)])
    assert len(P.ler(arq, valor_minimo=0.01).contatos) == 1


CORTE = datetime(2026, 10, 31).date()


@pytest.mark.parametrize("atraso,entra", [
    (datetime(2026, 10, 31, 23, 59), True),
    (datetime(2025, 7, 1), True),
    (datetime(2026, 11, 1), False),
    (datetime(2026, 11, 5), False),
])
def test_corte_por_data(tmp_path, atraso, entra):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [linha(atraso=atraso)]), vencido_ate=CORTE)
    assert bool(leitura.contatos) is entra
    if not entra:
        assert leitura.retidos[0][1] == "vencido apenas depois do corte"


def test_corte_tira_so_o_plano_de_novembro_da_pessoa(tmp_path):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [
        linha(plano=1.0, valor=100.0, parcelas=2.0, atraso=datetime(2026, 9, 10)),
        linha(plano=2.0, valor=900.0, parcelas=1.0, atraso=datetime(2026, 11, 3)),
    ]), vencido_ate=CORTE)
    p = leitura.contatos[0]
    assert p.valor == 100.0 and p.parcelas == 2 and p.planos == [("1", 2)]


def test_corte_vem_antes_do_valor_minimo(tmp_path):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [
        linha(valor=0.0, atraso=datetime(2026, 11, 3)),
    ]), vencido_ate=CORTE)
    assert leitura.retidos[0][1] == "vencido apenas depois do corte"


def test_sem_data_nao_passa_pelo_corte(tmp_path):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [linha(atraso=None)]), vencido_ate=CORTE)
    assert leitura.contatos == []


def test_sem_nenhum_contato_fica_retido(tmp_path):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [linha(cel="0", email="")]))
    assert leitura.retidos[0][1] == "sem nenhum contato valido"


def test_usa_telefone_quando_celular_falha(tmp_path):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [linha(cel="0", tel="11987654321")]))
    assert leitura.contatos[0].celular == "5511987654321"


def test_ordem_por_maior_valor(tmp_path):
    leitura = P.ler(criar(tmp_path / "a.xlsx", [
        linha(cpf=1.0, valor=10.0, cel="11911112222"),
        linha(cpf=2.0, valor=99.0, cel="11933334444"),
    ]))
    assert [p.valor for p in leitura.contatos] == [99.0, 10.0]


def test_coluna_faltando_recusa_planilha(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b", "c"])
    wb.active.append([1, 2, 3])
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(P.PlanilhaInvalida):
        P.ler(tmp_path / "x.xlsx")


def test_lista_interna_aceita_dominio_da_empresa_e_usa_valor_ficticio(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DOMINIOS_INTERNOS", frozenset({"exemplo.com"}))
    arq = tmp_path / "t.csv"
    arq.write_text(
        "nome;celular;email\nEquipe;11987654321;equipe@exemplo.com\n;;\nSo Mail;;a@exemplo.com\n",
        encoding="utf-8",
    )
    internos = P.ler_internos(arq)
    assert len(internos) == 2
    assert internos[0].email == "equipe@exemplo.com"
    assert internos[0].celular == "5511987654321"
    assert internos[0].valor == 1234.56


def test_lista_interna_com_numero_errado_recusa(tmp_path):
    arq = tmp_path / "t.csv"
    arq.write_text("nome;celular;email\nEquipe;1133334444;\n", encoding="utf-8")
    with pytest.raises(P.PlanilhaInvalida):
        P.ler_internos(arq)


def test_lista_interna_vazia_recusa(tmp_path):
    arq = tmp_path / "t.csv"
    arq.write_text("nome;celular;email\n", encoding="utf-8")
    with pytest.raises(P.PlanilhaInvalida):
        P.ler_internos(arq)


@pytest.mark.parametrize("hoje,esperado", [
    ((2026, 11, 5), (2026, 10, 31)),
    ((2026, 11, 14), (2026, 10, 31)),
    ((2026, 11, 15), (2026, 10, 31)),
    ((2026, 11, 16), (2026, 11, 15)),
    ((2026, 11, 30), (2026, 11, 15)),
    ((2026, 12, 1), (2026, 11, 30)),
    ((2027, 1, 10), (2026, 12, 31)),
    ((2028, 3, 1), (2028, 2, 29)),
])
def test_data_de_corte_segue_a_regra_do_dia_15(hoje, esperado):
    from datetime import date

    assert P.data_corte(date(*hoje)) == date(*esperado)
