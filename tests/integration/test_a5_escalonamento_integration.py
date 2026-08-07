"""A5 (Escalonamento Humano) ponta a ponta: webhook simulado ->
orquestrador -> classificador -> avaliar_escalonamento (Claude real,
tool-use) -> agent_create_escalation (RPC, protocolo sequencial real
ESC-YYYY-NNNNN). Cobre também o gancho A5->A2: motivo='desconto_renegociacao'
aciona pausar_charges_em_negociacao (app/orchestrator/orchestrator.py::
_rotear_para_a5), e o cron diário do A2 (STATUS_PAUSADOS) respeita isso
depois. Faz chamadas reais à API da Anthropic — ver nota de custo no README.
"""

import re
from datetime import date

import pytest

pytestmark = pytest.mark.integration

_PROTOCOLO_RE = re.compile(r"^ESC-\d{4}-\d{5}$")


class TestEscalonamentoSimplesENegociacaoConcorrentes:
    def test_dois_contratos_escalando_ao_mesmo_tempo_geram_protocolos_distintos(
        self,
        contrato_para_escalonamento,
        contrato_para_negociacao,
        enviar_mensagem_simulada,
        agente_client_factory,
    ):
        """Cenário 6 (escalonamento simples, sem gancho com o A2) + cenário 4
        (desconto_renegociacao, aciona pausar_charges_em_negociacao) no mesmo
        teste — prova que escalation_protocolo_seq (docs/schemas/
        004_protocolo_e_resolucao_contrato.sql) não colide entre escalações
        de contratos (e tokens RLS) diferentes geradas na mesma janela."""
        from app.agents.a2_cobranca import executar_cobranca_diaria

        telefone_simples = contrato_para_escalonamento["telefone"]
        contract_id_simples = contrato_para_escalonamento["contract_id"]
        enviar_mensagem_simulada(
            telefone=telefone_simples,
            texto=(
                "Isso é um absurdo, já pedi isso antes e ninguém resolve! Vou "
                "processar a imobiliária na justiça se isso não for resolvido logo."
            ),
        )

        telefone_negociacao = contrato_para_negociacao["telefone"]
        contract_id_negociacao = contrato_para_negociacao["contract_id"]
        resultado_negociacao = enviar_mensagem_simulada(
            telefone=telefone_negociacao,
            texto=(
                "Estou com dificuldade financeira esse mês, consigo um desconto no "
                "aluguel ou renegociar o valor de alguma forma?"
            ),
        )

        client_simples = agente_client_factory(contract_id_simples)
        client_negociacao = agente_client_factory(contract_id_negociacao)

        escalation_simples = (
            client_simples.table("escalations")
            .select("motivo, protocolo")
            .eq("contract_id", contract_id_simples)
            .single()
            .execute()
            .data
        )
        escalations_negociacao = (
            client_negociacao.table("escalations")
            .select("motivo, protocolo")
            .eq("contract_id", contract_id_negociacao)
            .execute()
            .data
        )
        assert any(e["motivo"] == "desconto_renegociacao" for e in escalations_negociacao)
        escalation_negociacao = next(
            e for e in escalations_negociacao if e["motivo"] == "desconto_renegociacao"
        )

        # Motivo diferente de desconto_renegociacao (um dos outros 12
        # critérios auto-detectáveis, ver criterios.py) — não afirmamos qual
        # exatamente, só que não é o que dispara o gancho com o A2.
        assert escalation_simples["motivo"] != "desconto_renegociacao"
        assert _PROTOCOLO_RE.match(escalation_simples["protocolo"])
        assert _PROTOCOLO_RE.match(escalation_negociacao["protocolo"])
        assert escalation_simples["protocolo"] != escalation_negociacao["protocolo"]
        assert escalation_negociacao["protocolo"] in resultado_negociacao["resposta"]

        # Cenário 6 não tem nenhuma charge cadastrada — o gancho A5->A2 não
        # tem o que pausar (nem deveria: motivo != desconto_renegociacao).
        charges_simples = (
            client_simples.table("charges")
            .select("id")
            .eq("contract_id", contract_id_simples)
            .execute()
            .data
        )
        assert charges_simples == []

        # Cenário 4: a charge em aberto (status='atrasado' na fixture) foi
        # de fato movida por pausar_charges_em_negociacao.
        charges_negociacao = (
            client_negociacao.table("charges")
            .select("id, status")
            .eq("contract_id", contract_id_negociacao)
            .execute()
            .data
        )
        assert charges_negociacao and all(c["status"] == "em_negociacao" for c in charges_negociacao)

        # STATUS_PAUSADOS (a2_cobranca/cobranca.py:36) — o cron diário do A2
        # não pode reativar cobrança para uma charge 'em_negociacao', mesmo
        # rodado no mesmo dia logo em seguida.
        executar_cobranca_diaria(hoje=date.today())
        charge_depois = (
            client_negociacao.table("charges")
            .select("status, mensagem_estagio")
            .eq("id", charges_negociacao[0]["id"])
            .single()
            .execute()
            .data
        )
        assert charge_depois["status"] == "em_negociacao"
        assert charge_depois["mensagem_estagio"] is None
