"""A2 (Cobrança) — cron diário contra o banco real, sem mock. Cobre:
avanço de estágio D-5/D0, o guard STATUS_PAUSADOS (negociação/confirmação
não recebem lembrete), e a constraint de banco que impede charge duplicada
no mesmo mês. Não depende do WhatsApp real nem da Anthropic — o envio de
mensagem de cobrança é só-log sem WHATSAPP_ACCESS_TOKEN (ver
app/agents/a2_cobranca/notificacao.py), e este agente não usa Claude.
"""

from datetime import timedelta

import pytest
from postgrest.exceptions import APIError

pytestmark = pytest.mark.integration


class TestEstagiosDeCobranca:
    def test_avanca_estagio_d5_e_depois_d0(self, contrato_pf_padrao, agente_client_factory):
        from app.agents.a2_cobranca import executar_cobranca_diaria

        contract_id = contrato_pf_padrao["contract_id"]
        data_vencimento = contrato_pf_padrao["data_vencimento_charge"]
        client = agente_client_factory(contract_id)

        def _charge() -> dict:
            return (
                client.table("charges")
                .select("status, dias_atraso, mensagem_estagio")
                .eq("contract_id", contract_id)
                .single()
                .execute()
                .data
            )

        executar_cobranca_diaria(hoje=data_vencimento - timedelta(days=5))
        charge_d5 = _charge()
        assert charge_d5["mensagem_estagio"] == "d-5"
        assert charge_d5["dias_atraso"] == -5
        assert charge_d5["status"] == "pendente"

        # Idempotência: rodar de novo NO MESMO dia não deve reenviar (o
        # guard é `estagio != charge.mensagem_estagio`) nem mudar nada.
        executar_cobranca_diaria(hoje=data_vencimento - timedelta(days=5))
        assert _charge() == charge_d5

        executar_cobranca_diaria(hoje=data_vencimento)
        charge_d0 = _charge()
        assert charge_d0["mensagem_estagio"] == "d0"
        assert charge_d0["dias_atraso"] == 0

    def test_charge_pausada_stat_pausados_nao_e_alterada_pelo_cron(
        self, contrato_pf_padrao, agente_client_factory, service_role_client
    ):
        """cobranca.py:36 (STATUS_PAUSADOS) — charge 'confirmado' não pode
        ganhar um novo mensagem_estagio nem mudar dias_atraso mesmo que a
        data bata exatamente com um estágio (regressão)."""
        from app.agents.a2_cobranca import executar_cobranca_diaria

        contract_id = contrato_pf_padrao["contract_id"]
        data_vencimento = contrato_pf_padrao["data_vencimento_charge"]
        client = agente_client_factory(contract_id)

        charge_id = (
            client.table("charges")
            .select("id")
            .eq("contract_id", contract_id)
            .single()
            .execute()
            .data["id"]
        )
        service_role_client.table("charges").update({"status": "confirmado"}).eq(
            "id", charge_id
        ).execute()

        executar_cobranca_diaria(hoje=data_vencimento)

        charge_depois = (
            client.table("charges")
            .select("status, dias_atraso, mensagem_estagio")
            .eq("id", charge_id)
            .single()
            .execute()
            .data
        )
        assert charge_depois["status"] == "confirmado"
        assert charge_depois["mensagem_estagio"] is None
        assert charge_depois["dias_atraso"] == 0


class TestChargesUnicoPorMes:
    def test_constraint_bloqueia_charge_agua_duplicada_no_mesmo_mes(
        self, contrato_pj_caucao, service_role_client
    ):
        """docs/schemas/001_create_tables.sql:146 —
        `charges_unico_por_mes unique (contract_id, tipo, mes_referencia)` —
        é a trava de idempotência contra cron rodando 2x ou upload duplicado
        de conta de água pro mesmo mês. contrato_pj_caucao já nasce com uma
        charge tipo=agua no mês corrente (ver fixtures/contratos.py)."""
        contract_id = contrato_pj_caucao["contract_id"]
        charge_existente = (
            service_role_client.table("charges")
            .select("mes_referencia")
            .eq("contract_id", contract_id)
            .eq("tipo", "agua")
            .single()
            .execute()
            .data
        )

        with pytest.raises(APIError):
            service_role_client.table("charges").insert(
                {
                    "contract_id": contract_id,
                    "tipo": "agua",
                    "mes_referencia": charge_existente["mes_referencia"],
                    "valor_esperado": 99.0,
                    "data_vencimento": charge_existente["mes_referencia"],
                }
            ).execute()
