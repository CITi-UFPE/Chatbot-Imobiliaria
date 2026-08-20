import pytest
from pydantic import ValidationError

from app.models.contract import ContratoExtraido

CAMPOS_BASE = {
    "imovel_identificacao": "Apto 101",
    "imovel_endereco": "Rua X, 123",
    "tipo_locatario": "pf",
    "inquilino_nome": "Fulano de Tal",
    "inquilino_cpf_cnpj": "000.000.000-00",
    "valor_aluguel": 2500.0,
    "dia_vencimento": 10,
    "data_inicio": "2026-01-01",
    "data_termino": "2027-01-01",
    "multa_infracao_tipo": "meses_aluguel",
    "multa_infracao_valor": 3,
    "aviso_previo_dias": 30,
    "aviso_previo_a_partir_mes": 1,
}


def test_fiador_com_nome_e_cpf_valida():
    contrato = ContratoExtraido(
        **CAMPOS_BASE,
        garantia_tipo="fiador",
        fiador_nome="Ciclano",
        fiador_cpf="111.111.111-11",
    )
    assert contrato.garantia_tipo == "fiador"


def test_fiador_sem_nome_falha():
    with pytest.raises(ValidationError, match="fiador_nome e fiador_cpf"):
        ContratoExtraido(**CAMPOS_BASE, garantia_tipo="fiador", fiador_cpf="111.111.111-11")


def test_fiador_sem_cpf_falha():
    with pytest.raises(ValidationError, match="fiador_nome e fiador_cpf"):
        ContratoExtraido(**CAMPOS_BASE, garantia_tipo="fiador", fiador_nome="Ciclano")


def test_caucao_com_valor_valida():
    contrato = ContratoExtraido(**CAMPOS_BASE, garantia_tipo="caucao", garantia_valor=5000.0)
    assert contrato.garantia_valor == 5000.0


def test_caucao_sem_valor_falha():
    with pytest.raises(ValidationError, match="garantia_valor"):
        ContratoExtraido(**CAMPOS_BASE, garantia_tipo="caucao")


def test_aluguel_antecipado_com_valor_valida():
    contrato = ContratoExtraido(
        **CAMPOS_BASE, garantia_tipo="aluguel_antecipado", garantia_valor=12000.0
    )
    assert contrato.garantia_tipo == "aluguel_antecipado"


def test_aluguel_antecipado_sem_valor_falha():
    with pytest.raises(ValidationError, match="garantia_valor"):
        ContratoExtraido(**CAMPOS_BASE, garantia_tipo="aluguel_antecipado")


def test_data_termino_antes_de_inicio_falha():
    campos = dict(CAMPOS_BASE, data_inicio="2027-01-01", data_termino="2026-01-01")
    with pytest.raises(ValidationError, match="data_termino"):
        ContratoExtraido(**campos, garantia_tipo="caucao", garantia_valor=5000.0)


def test_data_termino_igual_inicio_falha():
    campos = dict(CAMPOS_BASE, data_inicio="2026-01-01", data_termino="2026-01-01")
    with pytest.raises(ValidationError, match="data_termino"):
        ContratoExtraido(**campos, garantia_tipo="caucao", garantia_valor=5000.0)
