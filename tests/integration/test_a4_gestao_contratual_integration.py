"""A4 (Gestão Contratual) — cron diário contra o banco real, sem mock.
Cobre os dois guards do prazo indeterminado (Migration 013: Fluxo A de
alerta de renovação E finalização automática no término pulam esses
contratos) e o ciclo completo do contrato "prestes a vencer" (alerta D-60
-> finalização automática em data_termino), cada etapa verificada por
idempotência rodando 2x no mesmo dia simulado. A4 é puro cron — não
depende de Claude nem do WhatsApp, então esta suíte não tem custo de API.
"""

from datetime import date, timedelta
from uuid import UUID

import pytest

pytestmark = pytest.mark.integration


class TestPrazoIndeterminadoPulaFluxoA:
    def test_alerta_de_renovacao_e_finalizacao_pulam_contrato_de_prazo_indeterminado(
        self, contrato_prazo_indeterminado, service_role_client
    ):
        from app.agents.a4_gestao_contratual import executar_alertas_contratuais

        contract_id = contrato_prazo_indeterminado["contract_id"]
        data_termino = date.fromisoformat(contrato_prazo_indeterminado["dados"]["data_termino"])

        # "hoje" simulado bate exatamente na janela D-60 do alerta de
        # renovação — se este contrato não fosse prazo_indeterminado,
        # dispararia o Fluxo A (esta_na_janela_alerta_renovacao).
        resultado_d60 = executar_alertas_contratuais(hoje=data_termino - timedelta(days=60))
        assert resultado_d60.alertas_renovacao == []
        assert not resultado_d60.erros

        # "hoje" simulado bate exatamente em data_termino — se este contrato
        # não fosse prazo_indeterminado, seria finalizado incondicionalmente
        # (Migration 012).
        resultado_fim = executar_alertas_contratuais(hoje=data_termino)
        assert UUID(contract_id) not in resultado_fim.contratos_finalizados
        assert not resultado_fim.erros

        contrato_depois = (
            service_role_client.table("contracts")
            .select("status")
            .eq("id", contract_id)
            .single()
            .execute()
            .data
        )
        assert contrato_depois["status"] == "ativo"

        alertas_no_banco = (
            service_role_client.table("contract_alerts")
            .select("id")
            .eq("contract_id", contract_id)
            .execute()
            .data
        )
        assert alertas_no_banco == []


class TestCicloPrestesAVencer:
    def test_alerta_d60_finalizacao_no_termino_e_idempotencia(
        self, contrato_prestes_a_vencer, service_role_client
    ):
        from app.agents.a4_gestao_contratual import executar_alertas_contratuais

        contract_id = contrato_prestes_a_vencer["contract_id"]
        data_termino = date.fromisoformat(contrato_prestes_a_vencer["dados"]["data_termino"])
        hoje_d60 = data_termino - timedelta(days=60)  # exatamente a janela D-60

        # --- Alerta de renovação D-60 ---
        resultado = executar_alertas_contratuais(hoje=hoje_d60)
        assert len(resultado.alertas_renovacao) == 1
        assert not resultado.erros

        alerta = (
            service_role_client.table("contract_alerts")
            .select("tipo, data_disparo")
            .eq("contract_id", contract_id)
            .eq("tipo", "alerta_renovacao_d60")
            .single()
            .execute()
            .data
        )
        assert alerta["data_disparo"] == hoje_d60.isoformat()

        # Idempotência: rodar 2x no mesmo dia não duplica (índice único
        # contract_alerts_unico_por_disparo, migration 010 seção 10.2) nem
        # reenvia a mensagem de alerta.
        resultado_repeticao = executar_alertas_contratuais(hoje=hoje_d60)
        assert resultado_repeticao.alertas_renovacao == []
        assert not resultado_repeticao.erros
        alertas_apos_repeticao = (
            service_role_client.table("contract_alerts")
            .select("id")
            .eq("contract_id", contract_id)
            .eq("tipo", "alerta_renovacao_d60")
            .execute()
            .data
        )
        assert len(alertas_apos_repeticao) == 1

        # --- Finalização automática em data_termino ---
        resultado_fim = executar_alertas_contratuais(hoje=data_termino)
        assert resultado_fim.contratos_finalizados == [UUID(contract_id)]
        assert not resultado_fim.erros

        contrato_depois = (
            service_role_client.table("contracts")
            .select("status")
            .eq("id", contract_id)
            .single()
            .execute()
            .data
        )
        assert contrato_depois["status"] == "inativo"

        # Idempotência: rodar 2x no mesmo dia não re-finaliza. O guard
        # `where status = 'ativo'` de agent_finalizar_contrato (Migration
        # 012) nem chega a ser exercitado na 2ª chamada: o contrato já
        # inativo simplesmente some de cron_listar_contratos_ativos (que
        # filtra status='ativo'), então o loop do A4 nem o processa de novo.
        resultado_fim_repeticao = executar_alertas_contratuais(hoje=data_termino)
        assert UUID(contract_id) not in resultado_fim_repeticao.contratos_finalizados
        assert not resultado_fim_repeticao.erros
