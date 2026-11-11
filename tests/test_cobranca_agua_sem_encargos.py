"""Conta de água não sofre multa nem juros (pedido do cliente, 30/10 e
11/11/2026) até existir a opção "aplicar multa e juros" por conta. Aluguel
continua com os encargos de sempre."""

from datetime import date

import pytest

from app.agents.a2_cobranca.mensagens import (
    encargos_da_cobranca,
    montar_mensagem,
    montar_template_cobranca,
)
from app.agents.a2_cobranca.schemas import ChargeAtiva, DadosCobrancaContrato

_DADOS = DadosCobrancaContrato(
    telefone_whatsapp="5581999999999",
    inquilino_nome="Ewerton",
    imovel_identificacao="Golden Beach 2702",
    multa_moratoria_percentual=0.02,
    juros_moratorio_mensal=0.01,
)


def _charge(tipo: str, dias_atraso: int) -> ChargeAtiva:
    return ChargeAtiva(
        contract_id="contrato-1",
        charge_id="charge-1",
        tipo=tipo,
        mes_referencia=date(2026, 10, 1),
        valor_esperado=300.0,
        data_vencimento=date(2026, 10, 21),
        dias_atraso=dias_atraso,
        status="atrasado",
    )


def test_encargos_da_agua_sao_zero_e_total_igual_ao_original():
    assert encargos_da_cobranca("agua", 300.0, 32, 0.02, 0.01) == (0.0, 0.0, 300.0)


def test_encargos_do_aluguel_continuam_sendo_calculados():
    assert encargos_da_cobranca("aluguel", 4300.0, 32, 0.02, 0.01) == (86.0, 45.87, 4431.87)


@pytest.mark.parametrize("estagio,dias", [("d+5", 5), ("d+10", 10), ("d+15", 15)])
def test_mensagem_da_agua_atrasada_mostra_so_o_valor_original(estagio, dias):
    texto = montar_mensagem(_charge("agua", dias), _DADOS, estagio, dias)

    assert "R$ 300.00" in texto
    assert "encargos" not in texto
    assert "atualizado" not in texto


@pytest.mark.parametrize("estagio,dias", [("d+5", 5), ("d+10", 10)])
def test_template_da_agua_atrasada_leva_multa_e_juros_zerados(estagio, dias):
    template = montar_template_cobranca(_charge("agua", dias), _DADOS, estagio, dias)

    # (nome, descricao, vencimento, dias, original, multa, juros, total)
    assert template.nome == "aviso_atraso"
    original, multa, juros, total = template.parametros[4:8]
    assert multa == juros == "0,00"
    assert original == total


def test_template_do_aluguel_atrasado_continua_com_encargos():
    template = montar_template_cobranca(_charge("aluguel", 10), _DADOS, "d+10", 10)

    multa, juros, total = template.parametros[5:8]
    assert multa == "6,00"
    assert juros == "1,00"
    assert total == "307,00"
