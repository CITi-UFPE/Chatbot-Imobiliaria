"""A1 (Atendimento) respondendo sobre contas em aberto e histórico de
pagamento recente — ponta a ponta contra o Supabase de teste real e a API
real da Anthropic (mesmo padrão de test_a1_atendimento_integration.py).
"""

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


class TestA1RespondeStatusCobranca:
    def test_avisa_cobranca_em_aberto(self, contrato_pf_padrao, enviar_mensagem_simulada):
        """contrato_pf_padrao já nasce com uma charge tipo=aluguel
        status=pendente (fixtures/contratos.py) — o A1 deve mencionar que
        existe uma conta em aberto, sem inventar que está tudo pago."""
        telefone = contrato_pf_padrao["telefone"]

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="Tem alguma conta em aberto no meu apartamento?",
        )

        resposta = resultado["resposta"].lower()
        assert "aluguel" in resposta
        assert not any(
            frase in resposta
            for frase in ("nenhuma conta em aberto", "tudo em dia", "sem pendências", "sem pendencias")
        )

    def test_sem_charges_diz_que_nao_ha_conta_em_aberto(
        self, contrato_para_escalonamento, enviar_mensagem_simulada
    ):
        """contrato_para_escalonamento não tem nenhuma charge cadastrada
        (fixtures/contratos.py) — charges_abertas vem vazia da RPC, o A1
        precisa dizer isso com clareza, não inventar uma pendência."""
        telefone = contrato_para_escalonamento["telefone"]

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="Tem alguma conta em aberto no meu apartamento?",
        )

        resposta = resultado["resposta"].lower()
        assert any(
            frase in resposta
            for frase in ("nenhuma conta em aberto", "não há conta", "nao ha conta", "tudo em dia", "sem pendências", "sem pendencias", "não tem nenhuma")
        )

    def test_confirma_pagamento_recente_dentro_de_30_dias(
        self, contrato_pj_caucao, enviar_mensagem_simulada
    ):
        """contrato_pj_caucao já nasce com uma charge tipo=agua,
        status=confirmado, data_pagamento=hoje (fixtures/contratos.py) —
        dentro da janela de 30 dias."""
        telefone = contrato_pj_caucao["telefone"]

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="A conta de água que eu paguei já foi identificada?",
        )

        resposta = resultado["resposta"].lower()
        assert "água" in resposta or "agua" in resposta

    def test_nao_afirma_pagamento_fora_da_janela_de_30_dias(
        self, contrato_pj_caucao, enviar_mensagem_simulada, service_role_client
    ):
        """Regressão do requisito explícito do usuário: pagamento
        identificado há mais de 30 dias não deve ser tratado como recente.
        Move a data_pagamento da charge da fixture para 45 dias atrás."""
        contract_id = contrato_pj_caucao["contract_id"]
        telefone = contrato_pj_caucao["telefone"]
        data_antiga = (date.today() - timedelta(days=45)).isoformat()

        service_role_client.table("charges").update(
            {"data_pagamento": data_antiga}
        ).eq("contract_id", contract_id).execute()

        resultado = enviar_mensagem_simulada(
            telefone=telefone,
            texto="Meu pagamento de água recente já foi confirmado?",
        )

        resposta = resultado["resposta"].lower()
        assert "30 dias" in resposta


class TestGarantiaDeFiltragemNaRpc:
    """Diferente da classe acima, estes testes chamam a RPC direto (sem
    passar pelo Claude) — mais barato (zero custo de Anthropic, ver nota de
    custo em tests/integration/README.md) e mais preciso pra travar o
    CONTRATO da RPC em si, não a fraseação do modelo. Prova as duas metades
    da mesma garantia (ver docs/schemas/023_status_cobranca_a1.sql):
    (1) charges_abertas nunca tem condição de data no WHERE (nem
    data_vencimento nem data_pagamento) — uma conta em aberto aparece
    sempre, mesmo com vencimento muito antigo ou data_pagamento nula;
    (2) charges_pagas_ultimos_30_dias filtra data_pagamento NA QUERY — um
    pagamento fora da janela de 30 dias nunca sai do Postgres, não é
    escondido depois em Python nem deixado a critério do modelo."""

    def test_conta_em_aberto_aparece_mesmo_com_vencimento_muito_antigo(
        self, contrato_pf_padrao, agente_client_factory, service_role_client
    ):
        contract_id = contrato_pf_padrao["contract_id"]
        vencimento_antigo = date.today() - timedelta(days=200)

        service_role_client.table("charges").insert(
            {
                "contract_id": contract_id,
                "tipo": "agua",
                "mes_referencia": vencimento_antigo.replace(day=1).isoformat(),
                "valor_esperado": 90.0,
                "data_vencimento": vencimento_antigo.isoformat(),
                "dias_atraso": 200,
                "status": "atrasado",
            }
        ).execute()

        client = agente_client_factory(contract_id)
        resultado = client.rpc("buscar_status_cobranca_inquilino", {}).execute().data

        tipos_em_aberto = {c["tipo"] for c in resultado["charges_abertas"]}
        # A charge de água inserida agora (200 dias vencida) E a charge de
        # aluguel que já vem da fixture (contrato_pf_padrao) precisam
        # continuar as duas em charges_abertas.
        assert "agua" in tipos_em_aberto
        assert "aluguel" in tipos_em_aberto

        agua_aberta = next(c for c in resultado["charges_abertas"] if c["tipo"] == "agua")
        assert agua_aberta["dias_atraso"] == 200
        assert agua_aberta["status"] == "atrasado"

        # Nenhuma das duas tem data_pagamento preenchida — nenhuma pode
        # aparecer no histórico de pagamento, e a lista não pode ter
        # travado/quebrado por causa da data de vencimento antiga.
        assert resultado["charges_pagas_ultimos_30_dias"] == []

    def test_conta_em_aberto_com_status_divergente_nao_e_perdida(
        self, contrato_pf_padrao, service_role_client, agente_client_factory
    ):
        """status='divergente' nunca ganha data_pagamento (ver
        app/agents/a2_cobranca/comprovante.py::marcar_valor_divergente) —
        confirma que mesmo sem NENHUMA data de pagamento (nem antiga nem
        recente), a charge continua aparecendo em charges_abertas."""
        contract_id = contrato_pf_padrao["contract_id"]

        charge_id = (
            service_role_client.table("charges")
            .select("id")
            .eq("contract_id", contract_id)
            .single()
            .execute()
            .data["id"]
        )
        service_role_client.table("charges").update({"status": "divergente"}).eq(
            "id", charge_id
        ).execute()

        client = agente_client_factory(contract_id)
        resultado = client.rpc("buscar_status_cobranca_inquilino", {}).execute().data

        status_abertos = {c["charge_id"]: c["status"] for c in resultado["charges_abertas"]}
        assert status_abertos.get(charge_id) == "divergente"
        assert resultado["charges_pagas_ultimos_30_dias"] == []

    def test_pagamento_antigo_nunca_aparece_no_retorno_da_rpc(
        self, contrato_pj_caucao, service_role_client, agente_client_factory
    ):
        """Lado oposto da garantia: a exclusão de charges_pagas_ultimos_30_dias
        acontece NA QUERY (WHERE data_pagamento >= current_date - 30), não
        depois em Python nem por o modelo "escolher não mencionar" — a linha
        nem chega a sair do Postgres. contrato_pj_caucao já nasce com uma
        charge tipo=agua, status=confirmado, data_pagamento=hoje
        (fixtures/contratos.py); move para 45 dias atrás e confirma que ela
        desaparece do retorno da RPC por completo."""
        contract_id = contrato_pj_caucao["contract_id"]
        data_antiga = (date.today() - timedelta(days=45)).isoformat()

        service_role_client.table("charges").update(
            {"data_pagamento": data_antiga}
        ).eq("contract_id", contract_id).execute()

        client = agente_client_factory(contract_id)
        resultado = client.rpc("buscar_status_cobranca_inquilino", {}).execute().data

        assert resultado["charges_pagas_ultimos_30_dias"] == []
        # Também não pode "vazar" para charges_abertas: confirmado/quitado é
        # excluído de lá independente da idade do pagamento (ver Task 1).
        assert resultado["charges_abertas"] == []
