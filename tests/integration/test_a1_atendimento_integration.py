"""A1 (Atendimento) ponta a ponta: webhook simulado -> orquestrador ->
Claude (tool-use real, buscando dado do contrato via RPC) -> resposta ->
conversation_logs. Estes testes fazem chamadas reais à API da Anthropic
(modelo claude-sonnet-5, barato) — não dá pra mockar isso sem perder
exatamente o que a suíte de integração deveria comprovar (que o loop de
tool-use do A1 realmente busca o dado certo e responde com ele). Evite
rodar esta suíte em excesso fora de quando for necessário — ver nota de
custo em tests/integration/README.md.
"""

import pytest

pytestmark = pytest.mark.integration


class TestA1RespondePorClausulaReal:
    def test_responde_pergunta_com_clausula_correspondente(
        self, contrato_pf_padrao, enviar_mensagem_simulada, agente_client_factory
    ):
        telefone = contrato_pf_padrao["telefone"]
        contract_id = contrato_pf_padrao["contract_id"]

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="Qual a multa se eu atrasar o aluguel?",
        )

        resposta = resultado["resposta"]
        assert resposta
        # Não exigimos o texto exato (é o Claude respondendo em linguagem
        # natural) — só que o valor real da cláusula 5.1 apareça na resposta,
        # provando que o dado veio do contrato certo via RPC, não de um
        # conhecimento genérico do modelo.
        assert "2%" in resposta or "2 %" in resposta

        client = agente_client_factory(contract_id)
        logs = (
            client.table("conversation_logs")
            .select("remetente, agente_responsavel, mensagem")
            .eq("contract_id", contract_id)
            .order("timestamp")
            .execute()
            .data
        )
        assert len(logs) == 2
        assert logs[0]["remetente"] == "inquilino"
        assert logs[1]["remetente"] == "agente"
        assert logs[1]["agente_responsavel"] == "A1"

    def test_pergunta_sem_clausula_correspondente_escala_para_a5(
        self, contrato_pf_padrao, enviar_mensagem_simulada, agente_client_factory
    ):
        """docs/specs/categorizacao-clausulas.md já aponta ambiguidade de
        categorização como fonte real de bug — este teste cobre o caminho
        oposto e mais simples: uma pergunta que claramente não tem cláusula
        nenhuma no contrato fixture (só multa e água/energia cadastradas)."""
        telefone = contrato_pf_padrao["telefone"]
        contract_id = contrato_pf_padrao["contract_id"]

        enviar_mensagem_simulada(
            telefone=telefone,
            texto="Posso ter um cachorro de grande porte no apartamento?",
        )

        client = agente_client_factory(contract_id)
        escalations = (
            client.table("escalations")
            .select("motivo, protocolo")
            .eq("contract_id", contract_id)
            .execute()
            .data
        )
        assert any(e["motivo"] == "sem_clausula" for e in escalations)
        sem_clausula = next(e for e in escalations if e["motivo"] == "sem_clausula")
        assert sem_clausula["protocolo"] and sem_clausula["protocolo"].startswith("ESC-")
