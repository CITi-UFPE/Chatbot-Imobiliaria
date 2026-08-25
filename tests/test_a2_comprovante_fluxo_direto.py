"""Decisão do A2 para pagamento combinado direto ou resolução manual."""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.a2_cobranca.comprovante import _resolver_charge_e_notificar
from app.agents.a2_cobranca.schemas import ComprovanteExtraido


CONTRACT_ID = "11111111-1111-1111-1111-111111111111"
DADOS_CONTRATO = {
    "inquilino_nome": "João Pereira",
    "imovel_identificacao": "Apto 305",
}


def _client_fake(charges: list[dict], updates: list[dict]) -> MagicMock:
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(
        data=charges
    )

    def _rpc(nome, parametros):
        assert nome == "agent_update_charge_status"
        updates.append(parametros)
        builder = MagicMock()
        builder.execute.return_value = MagicMock(data=None)
        return builder

    client.rpc.side_effect = _rpc
    return client


def _extraido(valor: float) -> ComprovanteExtraido:
    return ComprovanteExtraido(
        valor_identificado=valor,
        data_identificada="2026-07-17",
        legivel=True,
    )


def test_uma_agua_e_um_aluguel_usam_fluxo_direto_e_marcam_ambas():
    charges = [
        {
            "id": "charge-agua",
            "tipo": "agua",
            "valor_esperado": 100.0,
            "data_vencimento": "2026-07-15",
        },
        {
            "id": "charge-aluguel",
            "tipo": "aluguel",
            "valor_esperado": 2200.0,
            "data_vencimento": "2026-07-10",
        },
    ]
    updates = []
    client = _client_fake(charges, updates)

    with patch(
        "app.agents.a2_cobranca.comprovante.notificar_fernanda_pagamento_combinado"
    ) as notificar_direto, patch(
        "app.agents.a2_cobranca.comprovante.notificar_fernanda_pagamento_combinado_manual"
    ) as notificar_manual:
        _resolver_charge_e_notificar(
            client, CONTRACT_ID, _extraido(2300.0), DADOS_CONTRATO
        )

    assert {u["p_charge_id"] for u in updates} == {"charge-agua", "charge-aluguel"}
    assert all(u["p_status"] == "aguardando_confirmacao" for u in updates)
    notificar_direto.assert_called_once()
    notificar_manual.assert_not_called()


@pytest.mark.parametrize(
    "charges, valor",
    [
        (
            [
                {"id": "aluguel-1", "tipo": "aluguel", "valor_esperado": 1000.0},
                {"id": "aluguel-2", "tipo": "aluguel", "valor_esperado": 1200.0},
            ],
            2200.0,
        ),
        (
            [
                {"id": "agua-1", "tipo": "agua", "valor_esperado": 80.0},
                {"id": "agua-2", "tipo": "agua", "valor_esperado": 90.0},
            ],
            170.0,
        ),
        (
            [
                {"id": "aluguel-1", "tipo": "aluguel", "valor_esperado": 1000.0},
                {"id": "agua-1", "tipo": "agua", "valor_esperado": 80.0},
                {"id": "agua-2", "tipo": "agua", "valor_esperado": 90.0},
            ],
            1170.0,
        ),
    ],
    ids=["dois_alugueis", "duas_aguas", "tres_cobrancas"],
)
def test_combinacoes_ambiguas_vao_para_manual_sem_mudar_status(charges, valor):
    updates = []
    client = _client_fake(charges, updates)

    with patch(
        "app.agents.a2_cobranca.comprovante.notificar_fernanda_pagamento_combinado"
    ) as notificar_direto, patch(
        "app.agents.a2_cobranca.comprovante.notificar_fernanda_pagamento_combinado_manual"
    ) as notificar_manual:
        _resolver_charge_e_notificar(client, CONTRACT_ID, _extraido(valor), DADOS_CONTRATO)

    assert updates == []
    notificar_direto.assert_not_called()
    notificar_manual.assert_called_once()
    assert notificar_manual.call_args.kwargs["charges_em_aberto"] == charges
