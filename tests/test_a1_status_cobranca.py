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
