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


# --- encargos (multa/juros) nas cobranças atrasadas -----------------------


def _charge_aberta(status: str, dias_atraso: int, charge_id: str = "c1") -> dict:
    return {
        "charge_id": charge_id,
        "tipo": "aluguel",
        "mes_referencia": "2026-08-01",
        "valor_esperado": 4300.0,
        "data_vencimento": "2026-08-23",
        "dias_atraso": dias_atraso,
        "status": status,
    }


def _client_fake_por_rpc(status_cobranca: dict, dados_inquilino) -> MagicMock:
    """Fake que devolve um retorno diferente por RPC — a tool de status
    também consulta buscar_dados_inquilino pra ler multa/juros do contrato."""
    client = MagicMock()

    def _rpc(nome, _params):
        chamada = MagicMock()
        if nome == "buscar_dados_inquilino" and isinstance(dados_inquilino, Exception):
            chamada.execute.side_effect = dados_inquilino
            return chamada
        resposta = MagicMock()
        resposta.data = status_cobranca if nome == "buscar_status_cobranca_inquilino" else dados_inquilino
        chamada.execute.return_value = resposta
        return chamada

    client.rpc.side_effect = _rpc
    return client


def _executar_com(client: MagicMock) -> dict:
    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        return_value=client,
    ):
        return atendimento._executar_buscar_status_cobranca(CONTRACT_ID_FAKE)


def test_charge_atrasada_recebe_valor_atualizado_com_multa_e_juros():
    """Regressão: o A1 informava 'atrasada há 32 dias' só com o valor
    original, sem os encargos que o cron do A2 mostra nas mensagens."""
    client = _client_fake_por_rpc(
        {"charges_abertas": [_charge_aberta("atrasado", 32)], "charges_pagas_ultimos_30_dias": []},
        {"multa_moratoria_percentual": 0.02, "juros_moratorio_mensal": 0.01},
    )

    charge = _executar_com(client)["charges_abertas"][0]

    assert charge["valor_multa"] == 86.0
    assert charge["valor_juros"] == 45.87
    assert charge["valor_atualizado"] == 4431.87


def test_charge_pendente_e_em_negociacao_nao_recebem_encargos():
    """Pendente ainda está no prazo; em negociação pode ter multa perdoada —
    em nenhum dos dois o A1 deve apresentar um valor com encargos."""
    client = _client_fake_por_rpc(
        {
            "charges_abertas": [
                _charge_aberta("pendente", 0, "c1"),
                _charge_aberta("em_negociacao", 20, "c2"),
            ],
            "charges_pagas_ultimos_30_dias": [],
        },
        {"multa_moratoria_percentual": 0.02, "juros_moratorio_mensal": 0.01},
    )

    abertas = _executar_com(client)["charges_abertas"]

    for charge in abertas:
        assert "valor_atualizado" not in charge
    # sem nenhuma charge atrasada, nem precisa buscar os dados do contrato
    nomes_rpc = [c.args[0] for c in client.rpc.call_args_list]
    assert "buscar_dados_inquilino" not in nomes_rpc


def test_multa_nula_no_contrato_calcula_so_juros():
    client = _client_fake_por_rpc(
        {"charges_abertas": [_charge_aberta("atrasado", 30)], "charges_pagas_ultimos_30_dias": []},
        {"multa_moratoria_percentual": None, "juros_moratorio_mensal": 0.01},
    )

    charge = _executar_com(client)["charges_abertas"][0]

    assert charge["valor_multa"] == 0.0
    assert charge["valor_juros"] == 43.0
    assert charge["valor_atualizado"] == 4343.0


def test_falha_ao_buscar_encargos_nao_derruba_a_tool():
    """Se a leitura de multa/juros falhar, o inquilino ainda recebe o status
    das cobranças — só sem o valor atualizado."""
    client = _client_fake_por_rpc(
        {"charges_abertas": [_charge_aberta("atrasado", 32)], "charges_pagas_ultimos_30_dias": []},
        RuntimeError("rede instável"),
    )

    charge = _executar_com(client)["charges_abertas"][0]

    assert charge["status"] == "atrasado"
    assert "valor_atualizado" not in charge


def test_system_prompt_orienta_informar_valor_atualizado():
    assert "valor_atualizado" in atendimento.SYSTEM_PROMPT
