"""A3 (Manutenção) — ciclo completo da máquina de estados multi-turno via
/dev/chat-simulado, contra o banco real: agent_conversation_states
persistindo entre mensagens (docs/schemas/007_estado_conversa_agente.sql) e
o maintenance_tickets final. A etapa de classificação da descrição
(aguardando_descricao) usa Claude de verdade (claude-sonnet-5,
app/tools/maintenance_classification.py) — ver nota de custo no README.
"""

import pytest

pytestmark = pytest.mark.integration


class TestCicloCompletoDeAtendimento:
    def test_confirma_imovel_descreve_problema_e_abre_ticket(
        self, contrato_para_manutencao, enviar_mensagem_simulada, agente_client_factory
    ):
        telefone = contrato_para_manutencao["telefone"]
        contract_id = contrato_para_manutencao["contract_id"]
        client = agente_client_factory(contract_id)

        # Turno 1: primeira mensagem sobre manutenção — sem estado salvo
        # ainda, então iniciar_atendimento pergunta a confirmação do imóvel.
        r1 = enviar_mensagem_simulada(
            telefone=telefone, texto="O cano da pia da cozinha está vazando bastante água"
        )
        assert "onfirm" in r1["resposta"]  # "Confirmando: apto..." (maiúscula varia)

        estado = (
            client.rpc("agent_get_conversation_state", {"p_agente": "A3"}).execute().data
        )
        assert estado["etapa"] == "aguardando_confirmacao_imovel"

        # Turno 2: confirma o imóvel -> pede a descrição do problema.
        r2 = enviar_mensagem_simulada(telefone=telefone, texto="sim, confirmo")
        assert r2["resposta"]

        # Turno 3: descrição clara e inequívoca de um problema hidráulico —
        # confiança da classificação deve ser alta o bastante para abrir o
        # ticket direto, sem passar por aguardando_esclarecimento.
        r3 = enviar_mensagem_simulada(
            telefone=telefone,
            texto=(
                "O cano embaixo da pia da cozinha está vazando água constantemente "
                "há dois dias, já empoçando no chão do armário."
            ),
        )
        assert r3["resposta"]

        tickets = (
            client.table("maintenance_tickets")
            .select("categoria, urgencia, descricao, status")
            .eq("contract_id", contract_id)
            .execute()
            .data
        )
        assert len(tickets) == 1
        assert tickets[0]["categoria"] == "hidraulica"
        assert tickets[0]["status"] == "aberto"

        # Estado é apagado quando a etapa chega em 'finalizado' (ver
        # responder_manutencao em app/agents/a3_manutencao/atendimento.py) —
        # próxima mensagem de manutenção deve poder começar do zero.
        estado_final = client.rpc("agent_get_conversation_state", {"p_agente": "A3"}).execute().data
        assert estado_final is None


class TestFalhaDeIdentificacaoDoImovel:
    def test_nao_confirmar_imovel_duas_vezes_escala_para_a5(
        self, contrato_para_manutencao, enviar_mensagem_simulada, agente_client_factory
    ):
        """MAX_TENTATIVAS_IDENTIFICACAO=2 (fluxo.py) — depois da 2ª resposta
        que não confirma nem nega claramente, escala motivo='pedido_humano'
        em vez de ficar perguntando pra sempre. Não depende de classificação
        por Claude (só contem_palavra), então é determinístico e barato."""
        telefone = contrato_para_manutencao["telefone"]
        contract_id = contrato_para_manutencao["contract_id"]
        client = agente_client_factory(contract_id)

        enviar_mensagem_simulada(telefone=telefone, texto="tem um problema aqui no apê")
        enviar_mensagem_simulada(telefone=telefone, texto="hein? que endereço?")
        r_final = enviar_mensagem_simulada(telefone=telefone, texto="ainda não entendi")

        assert "humano" in r_final["resposta"].lower() or "atendente" in r_final["resposta"].lower()

        escalations = (
            client.table("escalations")
            .select("motivo")
            .eq("contract_id", contract_id)
            .execute()
            .data
        )
        assert any(e["motivo"] == "pedido_humano" for e in escalations)
