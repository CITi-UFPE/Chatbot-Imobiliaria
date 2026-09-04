"""Testes da tool buscar_status_cobranca_inquilino do A1 (Atendimento).

Não chama a API da Anthropic nem o Supabase de verdade — só a função Python
que embrulha a RPC (_executar_buscar_status_cobranca) e a validação
Pydantic do retorno, mesmo padrão de tests/test_classificador_intencao.py e
tests/test_a1_atendimento_prompt.py (nenhum dos dois precisa de
ANTHROPIC_API_KEY nem de Supabase real)."""

import pytest
from pydantic import ValidationError

from app.agents.a1_atendimento.schemas import StatusCobrancaContrato


def test_status_cobranca_contrato_aceita_retorno_valido():
    dados = {
        "charges_abertas": [
            {
                "charge_id": "c1",
                "tipo": "aluguel",
                "mes_referencia": "2026-09-01",
                "valor_esperado": 1500.0,
                "data_vencimento": "2026-09-10",
                "dias_atraso": 3,
                "status": "atrasado",
            }
        ],
        "charges_pagas_ultimos_30_dias": [
            {
                "charge_id": "c2",
                "tipo": "agua",
                "mes_referencia": "2026-08-01",
                "valor_esperado": 120.5,
                "valor_identificado": 120.5,
                "data_pagamento": "2026-08-20",
                "status": "confirmado",
            }
        ],
    }

    validado = StatusCobrancaContrato.model_validate(dados)

    assert validado.charges_abertas[0].status == "atrasado"
    assert validado.charges_pagas_ultimos_30_dias[0].data_pagamento == "2026-08-20"


def test_status_cobranca_contrato_aceita_listas_vazias():
    validado = StatusCobrancaContrato.model_validate(
        {"charges_abertas": [], "charges_pagas_ultimos_30_dias": []}
    )
    assert validado.charges_abertas == []
    assert validado.charges_pagas_ultimos_30_dias == []


def test_charge_paga_recente_aceita_valor_identificado_nulo():
    """Cobranças marcadas 'quitado' manualmente pelo staff (fora do fluxo
    automático do A2) podem não ter valor_identificado preenchido — ver
    docs/schemas/023_status_cobranca_a1.sql."""
    validado = StatusCobrancaContrato.model_validate(
        {
            "charges_abertas": [],
            "charges_pagas_ultimos_30_dias": [
                {
                    "charge_id": "c3",
                    "tipo": "aluguel",
                    "mes_referencia": "2026-08-01",
                    "valor_esperado": 1500.0,
                    "valor_identificado": None,
                    "data_pagamento": "2026-08-15",
                    "status": "quitado",
                }
            ],
        }
    )
    assert validado.charges_pagas_ultimos_30_dias[0].valor_identificado is None


def test_status_cobranca_contrato_rejeita_status_desconhecido():
    with pytest.raises(ValidationError):
        StatusCobrancaContrato.model_validate(
            {
                "charges_abertas": [
                    {
                        "charge_id": "c1",
                        "tipo": "aluguel",
                        "mes_referencia": "2026-09-01",
                        "valor_esperado": 1500.0,
                        "data_vencimento": "2026-09-10",
                        "dias_atraso": 0,
                        "status": "status_que_nao_existe",
                    }
                ],
                "charges_pagas_ultimos_30_dias": [],
            }
        )


def test_status_cobranca_contrato_rejeita_campo_extra():
    """model_config = ConfigDict(extra='forbid') — mesmo padrão de
    DadosInquilino: se a RPC mudar de formato no banco sem avisar aqui, isso
    deve quebrar explicitamente, não virar um campo estranho que o Claude
    tenta interpretar sozinho."""
    with pytest.raises(ValidationError):
        StatusCobrancaContrato.model_validate(
            {
                "charges_abertas": [],
                "charges_pagas_ultimos_30_dias": [],
                "campo_que_nao_deveria_existir": True,
            }
        )


# --- _executar_buscar_status_cobranca (wrapper Python da RPC) -------------

from unittest.mock import MagicMock, patch  # noqa: E402

from app.agents.a1_atendimento import atendimento  # noqa: E402

CONTRACT_ID_FAKE = "11111111-1111-1111-1111-111111111111"


def _client_fake(retorno_rpc) -> MagicMock:
    client = MagicMock()
    resposta = MagicMock()
    resposta.data = retorno_rpc
    client.rpc.return_value.execute.return_value = resposta
    return client


def test_executar_buscar_status_cobranca_chama_rpc_sem_parametros():
    retorno = {"charges_abertas": [], "charges_pagas_ultimos_30_dias": []}
    client = _client_fake(retorno)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        resultado = atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)

    client.rpc.assert_called_once_with("buscar_status_cobranca_inquilino", {})
    assert resultado == retorno


def test_executar_buscar_status_cobranca_devolve_dados_da_rpc():
    retorno = {
        "charges_abertas": [
            {
                "charge_id": "c1",
                "tipo": "aluguel",
                "mes_referencia": "2026-09-01",
                "valor_esperado": 1500.0,
                "data_vencimento": "2026-09-10",
                "dias_atraso": 3,
                "status": "atrasado",
            }
        ],
        "charges_pagas_ultimos_30_dias": [],
    }
    client = _client_fake(retorno)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        resultado = atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)

    assert resultado["charges_abertas"][0]["status"] == "atrasado"


def test_executar_buscar_status_cobranca_com_retorno_none_vira_listas_vazias():
    """Se a RPC devolver null (ex: contrato sem nenhuma charge cadastrada
    ainda), o wrapper não deve quebrar tentando indexar um dict inexistente."""
    client = _client_fake(None)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        resultado = atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)

    assert resultado == {"charges_abertas": [], "charges_pagas_ultimos_30_dias": []}


def test_executar_buscar_status_cobranca_com_shape_invalido_levanta_erro():
    """Formato inesperado da RPC (ex: mudou no banco sem avisar aqui) deve
    quebrar explicitamente na validação Pydantic — mesma doutrina de
    _executar_buscar_dados_inquilino."""
    from pydantic import ValidationError

    retorno_invalido = {
        "charges_abertas": [{"charge_id": "c1"}],  # faltam campos obrigatórios
        "charges_pagas_ultimos_30_dias": [],
    }
    client = _client_fake(retorno_invalido)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        with pytest.raises(ValidationError):
            atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)


def test_tools_schema_registra_buscar_status_cobranca():
    nomes = {t["name"] for t in atendimento._tools_schema()}
    assert atendimento.TOOL_BUSCAR_STATUS_COBRANCA in nomes
    assert atendimento.TOOL_BUSCAR_STATUS_COBRANCA == "buscar_status_cobranca_inquilino"
