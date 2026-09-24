"""A2 — geração automática da charge de aluguel contra o banco real
(Migration 025): RPCs, isolamento por token e idempotência via
charges_unico_por_mes. Não envia WhatsApp nem chama a Anthropic.
"""

from datetime import date, timedelta
from typing import Any, Iterator

import pytest
from supabase import Client

from tests.integration.fixtures.contratos import PREFIXO_TELEFONE_FIXTURE, _contrato_base

pytestmark = pytest.mark.integration

TELEFONE = f"{PREFIXO_TELEFONE_FIXTURE}090"


@pytest.fixture
def contrato_sem_charges(service_role_client: Client) -> Iterator[dict[str, Any]]:
    hoje = date.today()
    vencimento = hoje + timedelta(days=7)
    dados = _contrato_base(
        imovel_identificacao="Apto Fixture Geração",
        telefone_whatsapp=TELEFONE,
        dia_vencimento=vencimento.day,
        valor_aluguel=1750.0,
    )
    service_role_client.table("contracts").delete().eq("telefone_whatsapp", TELEFONE).execute()
    contract_id = service_role_client.table("contracts").insert(dados).execute().data[0]["id"]
    yield {"contract_id": contract_id, "hoje": hoje, "vencimento": vencimento}
    service_role_client.table("contracts").delete().eq("telefone_whatsapp", TELEFONE).execute()


def _charges_aluguel(service_role_client: Client, contract_id: str) -> list[dict]:
    return (
        service_role_client.table("charges")
        .select("mes_referencia, data_vencimento, valor_esperado, status, mensagem_estagio")
        .eq("contract_id", contract_id)
        .eq("tipo", "aluguel")
        .execute()
        .data
    )


class TestGeracaoChargesAluguel:
    def test_gera_charge_do_mes_com_valor_do_contrato(self, contrato_sem_charges, service_role_client):
        from app.agents.a2_cobranca import gerar_charges_aluguel

        vencimento = contrato_sem_charges["vencimento"]
        gerar_charges_aluguel(hoje=contrato_sem_charges["hoje"])

        assert _charges_aluguel(service_role_client, contrato_sem_charges["contract_id"]) == [
            {
                "mes_referencia": vencimento.replace(day=1).isoformat(),
                "data_vencimento": vencimento.isoformat(),
                "valor_esperado": 1750.0,
                "status": "pendente",
                "mensagem_estagio": None,
            }
        ]

    def test_rodar_duas_vezes_nao_duplica(self, contrato_sem_charges, service_role_client):
        from app.agents.a2_cobranca import gerar_charges_aluguel

        gerar_charges_aluguel(hoje=contrato_sem_charges["hoje"])
        gerar_charges_aluguel(hoje=contrato_sem_charges["hoje"])

        assert len(_charges_aluguel(service_role_client, contrato_sem_charges["contract_id"])) == 1

    def test_nao_sobrescreve_charge_ja_lancada(self, contrato_sem_charges, service_role_client):
        from app.agents.a2_cobranca import gerar_charges_aluguel

        vencimento = contrato_sem_charges["vencimento"]
        service_role_client.table("charges").insert(
            {
                "contract_id": contrato_sem_charges["contract_id"],
                "tipo": "aluguel",
                "mes_referencia": vencimento.replace(day=1).isoformat(),
                "valor_esperado": 999.0,
                "data_vencimento": vencimento.isoformat(),
            }
        ).execute()

        gerar_charges_aluguel(hoje=contrato_sem_charges["hoje"])

        charges = _charges_aluguel(service_role_client, contrato_sem_charges["contract_id"])
        assert len(charges) == 1
        assert charges[0]["valor_esperado"] == 999.0

    def test_contrato_inativo_nao_gera(self, contrato_sem_charges, service_role_client):
        from app.agents.a2_cobranca import gerar_charges_aluguel

        service_role_client.table("contracts").update({"status": "inativo"}).eq(
            "id", contrato_sem_charges["contract_id"]
        ).execute()

        gerar_charges_aluguel(hoje=contrato_sem_charges["hoje"])

        assert _charges_aluguel(service_role_client, contrato_sem_charges["contract_id"]) == []
