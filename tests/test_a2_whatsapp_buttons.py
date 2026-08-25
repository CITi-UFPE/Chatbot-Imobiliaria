"""Testes da WA-06 — botões interativos do fluxo de comprovante do A2.

Cobre quatro frentes:

1. Round-trip dos IDs: todo `id` montado por `montar_button_id_*`
   (app/agents/a2_cobranca/button_ids.py) precisa ser reconhecido de volta
   por `decodificar_button_id`, com a mesma acao/contract_id/charge_ids.
2. Payloads dos templates: `notificar_fernanda_comprovante`,
   `notificar_fernanda_pagamento_combinado` e
   `notificar_pergunta_qual_charge_paga` (app/agents/a2_cobranca/
   notificacao.py) preservam IDs que decodificam de volta para
   ação/contract_id/charge_id(s). A segunda pergunta provisória ainda usa
   `enviar_botoes` até o novo fluxo ser aprovado.
3. Roteamento do clique: cada ação decodificável (confirmar, divergente,
   combinado_todos, escolher_parcial, combinado_parcial) precisa disparar
   o processamento certo em app/orchestrator/orchestrator.py; um id
   genuinamente não reconhecido não deve alterar nada.
4. Fluxo completo do "Só uma delas" (pagamento combinado parcial), em duas
   etapas: 1º clique só pergunta qual charge foi paga (não mexe em nada);
   2º clique (um por charge) é que de fato confirma uma e reverte a(s)
   outra(s) pra pendente — sem ambiguidade, porque o botão da 2ª etapa já
   é específico de uma charge.

Nenhum destes testes acessa a Meta, o Supabase ou a Anthropic de verdade:
`whatsapp_client.enviar_botoes`, `obter_client_agente` e
`app.orchestrator.orchestrator.processar_entrada_a2` são sempre
substituídos por fakes/mocks via monkeypatch.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.a2_cobranca import button_ids
from app.agents.a2_cobranca import comprovante
from app.agents.a2_cobranca import notificacao as notif_a2
from app.tools import whatsapp_client as wc

CONTRACT_ID = "11111111-1111-1111-1111-111111111111"


# ======================================================================
# 1. Round-trip dos IDs
# ======================================================================


class TestRoundTripButtonIds:
    def test_confirmar(self):
        button_id = button_ids.montar_button_id_confirmar(CONTRACT_ID, "charge-1")
        decodificado = button_ids.decodificar_button_id(button_id)

        assert decodificado is not None
        assert decodificado.acao == button_ids.ACAO_CONFIRMAR
        assert decodificado.contract_id == CONTRACT_ID
        assert decodificado.charge_ids == ["charge-1"]

    def test_divergente(self):
        button_id = button_ids.montar_button_id_divergente(CONTRACT_ID, "charge-1")
        decodificado = button_ids.decodificar_button_id(button_id)

        assert decodificado is not None
        assert decodificado.acao == button_ids.ACAO_DIVERGENTE
        assert decodificado.contract_id == CONTRACT_ID
        assert decodificado.charge_ids == ["charge-1"]

    def test_combinado_todos_multiplas_charges(self):
        button_id = button_ids.montar_button_id_combinado_todos(
            CONTRACT_ID, ["charge-aluguel", "charge-agua"]
        )
        decodificado = button_ids.decodificar_button_id(button_id)

        assert decodificado is not None
        assert decodificado.acao == button_ids.ACAO_COMBINADO_TODOS
        assert decodificado.contract_id == CONTRACT_ID
        assert decodificado.charge_ids == ["charge-aluguel", "charge-agua"]

    def test_escolher_parcial(self):
        """1ª etapa do fluxo de "Só uma delas" — carrega TODAS as charges
        envolvidas, ainda sem saber qual foi paga."""
        button_id = button_ids.montar_button_id_escolher_parcial(
            CONTRACT_ID, ["charge-aluguel", "charge-agua"]
        )
        decodificado = button_ids.decodificar_button_id(button_id)

        assert decodificado is not None
        assert decodificado.acao == button_ids.ACAO_ESCOLHER_PARCIAL
        assert decodificado.contract_id == CONTRACT_ID
        assert decodificado.charge_ids == ["charge-aluguel", "charge-agua"]

    def test_combinado_parcial_charge_paga_sempre_primeiro(self):
        """2ª etapa — a charge paga é sempre o primeiro elemento da lista
        codificada, é essa convenção que deixa o clique sem ambiguidade."""
        button_id = button_ids.montar_button_id_combinado_parcial(
            CONTRACT_ID, "charge-agua", ["charge-aluguel"]
        )
        decodificado = button_ids.decodificar_button_id(button_id)

        assert decodificado is not None
        assert decodificado.acao == button_ids.ACAO_COMBINADO_PARCIAL
        assert decodificado.contract_id == CONTRACT_ID
        assert decodificado.charge_ids == ["charge-agua", "charge-aluguel"]

    def test_id_desconhecido_nao_e_decodificavel(self):
        button_id_invalido = f"acao_que_nao_existe|{CONTRACT_ID}|charge-1"
        assert button_ids.decodificar_button_id(button_id_invalido) is None


# ======================================================================
# 2. Payloads de notificação
# ======================================================================


class TestPayloadNotificarFernandaComprovante:
    def test_botoes_confirmar_e_divergente_decodificaveis(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR", *, botoes=None):
            chamadas.append((telefone, nome, parametros, botoes))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.notificar_fernanda_comprovante(
            "+5581988880000",
            CONTRACT_ID,
            "charge-1",
            "João Pereira",
            "Apto 305",
            2200.0,
            "2026-07-15",
            2200.0,
        )

        assert len(chamadas) == 1
        _, nome, parametros, botoes = chamadas[0]
        assert nome == "comprovante_para_conferencia"
        assert parametros[-1] == "Única cobrança em aberto"
        assert len(botoes) == 2

        confirmar, divergente = botoes
        assert all(1 <= len(payload) <= 256 for payload in botoes)

        decod_confirmar = button_ids.decodificar_button_id(confirmar)
        assert decod_confirmar.acao == button_ids.ACAO_CONFIRMAR
        assert decod_confirmar.contract_id == CONTRACT_ID
        assert decod_confirmar.charge_ids == ["charge-1"]

        decod_divergente = button_ids.decodificar_button_id(divergente)
        assert decod_divergente.acao == button_ids.ACAO_DIVERGENTE
        assert decod_divergente.contract_id == CONTRACT_ID
        assert decod_divergente.charge_ids == ["charge-1"]


class TestPayloadNotificarFernandaPagamentoCombinado:
    CHARGES = [
        {"id": "charge-aluguel", "tipo": "aluguel", "valor_esperado": 2200.0},
        {"id": "charge-agua", "tipo": "agua", "valor_esperado": 100.0},
    ]

    def test_botoes_cobre_os_dois_e_so_uma_delas_decodificaveis(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR", *, botoes=None):
            chamadas.append((telefone, nome, parametros, botoes))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.2")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.notificar_fernanda_pagamento_combinado(
            "+5581988880000",
            CONTRACT_ID,
            "João Pereira",
            "Apto 305",
            2300.0,
            "2026-07-17",
            self.CHARGES,
        )

        assert len(chamadas) == 1
        _, nome, parametros, botoes = chamadas[0]
        assert nome == "pagamento_combinado"
        assert parametros[-1] == "- Aluguel: R$ 2.200,00\n- Agua: R$ 100,00"

        assert len(botoes) <= 3
        assert all(1 <= len(payload) <= 256 for payload in botoes)

        cobre_os_dois, so_uma_delas = botoes

        decod_todos = button_ids.decodificar_button_id(cobre_os_dois)
        assert decod_todos.acao == button_ids.ACAO_COMBINADO_TODOS
        assert decod_todos.contract_id == CONTRACT_ID
        assert decod_todos.charge_ids == ["charge-aluguel", "charge-agua"]

        decod_escolher = button_ids.decodificar_button_id(so_uma_delas)
        assert decod_escolher.acao == button_ids.ACAO_ESCOLHER_PARCIAL
        assert decod_escolher.contract_id == CONTRACT_ID
        assert decod_escolher.charge_ids == ["charge-aluguel", "charge-agua"]

        assert all(
            button_ids.decodificar_button_id(payload).acao
            != button_ids.ACAO_DIVERGENTE
            for payload in botoes
        )


class TestPayloadNotificarPerguntaQualChargePaga:
    def test_um_botao_por_charge_decodificavel_e_sem_ambiguidade(self, monkeypatch):
        chamadas = []

        def fake_enviar_botoes(telefone, corpo, botoes):
            chamadas.append((telefone, corpo, botoes))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.3")

        monkeypatch.setattr(wc, "enviar_botoes", fake_enviar_botoes)

        charges = [
            {"id": "charge-aluguel", "tipo": "aluguel"},
            {"id": "charge-agua", "tipo": "agua"},
        ]
        notif_a2.notificar_pergunta_qual_charge_paga("+5581988880000", CONTRACT_ID, charges)

        assert len(chamadas) == 1
        _, _, botoes = chamadas[0]
        assert [b["titulo"] for b in botoes] == ["Aluguel", "Agua"]

        for botao in botoes:
            assert 1 <= len(botao["titulo"]) <= 20
            assert 1 <= len(botao["id"]) <= 256

        # Cada botão, ao decodificar, já resolve sem ambiguidade: a charge
        # daquele botão é a paga, a outra volta pra pendente.
        decod_aluguel = button_ids.decodificar_button_id(botoes[0]["id"])
        assert decod_aluguel.acao == button_ids.ACAO_COMBINADO_PARCIAL
        assert decod_aluguel.charge_ids == ["charge-aluguel", "charge-agua"]

        decod_agua = button_ids.decodificar_button_id(botoes[1]["id"])
        assert decod_agua.acao == button_ids.ACAO_COMBINADO_PARCIAL
        assert decod_agua.charge_ids == ["charge-agua", "charge-aluguel"]

    def test_mais_de_3_charges_cai_pra_texto_em_vez_de_estourar_o_limite_de_botoes(self, monkeypatch):
        """Achado do code-review: com 4+ charges combinadas,
        whatsapp_client.enviar_botoes rejeitaria a chamada (limite de 3
        botões da Meta) — sem esse fallback, a Fernanda nunca recebia
        NENHUMA mensagem de acompanhamento e as charges ficavam presas em
        'aguardando_confirmacao' pra sempre. Confere que agora cai pra
        enviar_texto, listando as 4 charges, em vez de propagar erro."""
        chamadas_texto = []
        chamadas_botoes = []

        monkeypatch.setattr(
            wc, "enviar_texto", lambda telefone, texto: chamadas_texto.append((telefone, texto))
        )
        monkeypatch.setattr(
            wc, "enviar_botoes", lambda *a, **kw: chamadas_botoes.append((a, kw))
        )

        charges = [
            {"id": "charge-aluguel", "tipo": "aluguel"},
            {"id": "charge-agua", "tipo": "agua"},
            {"id": "charge-condominio", "tipo": "condominio"},
            {"id": "charge-iptu", "tipo": "iptu"},
        ]
        notif_a2.notificar_pergunta_qual_charge_paga("+5581988880000", CONTRACT_ID, charges)

        assert chamadas_botoes == []
        assert len(chamadas_texto) == 1
        telefone, texto = chamadas_texto[0]
        assert telefone == "+5581988880000"
        for charge in charges:
            assert charge["tipo"].capitalize() in texto


# ======================================================================
# 3. Roteamento do clique (app/orchestrator/orchestrator.py)
# ======================================================================


class TestRoteamentoClique:
    def test_clique_nao_reconhecido_nao_altera_nada(self):
        from app.orchestrator.orchestrator import rotear_clique_botao_a2

        button_id_invalido = f"acao_que_nao_existe|{CONTRACT_ID}|charge-1"

        with patch("app.orchestrator.orchestrator.processar_entrada_a2") as mock_processar:
            resultado = rotear_clique_botao_a2(button_id_invalido, "+5581988880000")

        mock_processar.assert_not_called()
        assert "não consegui reconhecer" in resultado.lower()

    def test_clique_button_id_vazio_tambem_nao_altera_nada(self):
        from app.orchestrator.orchestrator import rotear_clique_botao_a2

        with patch("app.orchestrator.orchestrator.processar_entrada_a2") as mock_processar:
            resultado = rotear_clique_botao_a2("", "+5581988880000")

        mock_processar.assert_not_called()
        assert "não consegui reconhecer" in resultado.lower()

    @pytest.mark.parametrize(
        "acao",
        [
            button_ids.ACAO_CONFIRMAR,
            button_ids.ACAO_DIVERGENTE,
            button_ids.ACAO_COMBINADO_TODOS,
            button_ids.ACAO_ESCOLHER_PARCIAL,
            button_ids.ACAO_COMBINADO_PARCIAL,
        ],
    )
    def test_todas_as_acoes_decodificaveis_chamam_processar_entrada_a2(self, acao):
        from app.orchestrator.orchestrator import rotear_clique_botao_a2

        montar = {
            button_ids.ACAO_CONFIRMAR: lambda: button_ids.montar_button_id_confirmar(
                CONTRACT_ID, "charge-1"
            ),
            button_ids.ACAO_DIVERGENTE: lambda: button_ids.montar_button_id_divergente(
                CONTRACT_ID, "charge-1"
            ),
            button_ids.ACAO_COMBINADO_TODOS: lambda: button_ids.montar_button_id_combinado_todos(
                CONTRACT_ID, ["charge-1", "charge-2"]
            ),
            button_ids.ACAO_ESCOLHER_PARCIAL: lambda: button_ids.montar_button_id_escolher_parcial(
                CONTRACT_ID, ["charge-1", "charge-2"]
            ),
            button_ids.ACAO_COMBINADO_PARCIAL: lambda: button_ids.montar_button_id_combinado_parcial(
                CONTRACT_ID, "charge-1", ["charge-2"]
            ),
        }
        button_id = montar[acao]()

        with patch("app.orchestrator.orchestrator.processar_entrada_a2") as mock_processar:
            rotear_clique_botao_a2(button_id, "+5581988880000")

        mock_processar.assert_called_once()

    def test_escolher_parcial_repassa_telefone_de_quem_clicou(self):
        """A ação ESCOLHER_PAGAMENTO_PARCIAL é a única que precisa saber
        quem clicou — pra mandar a segunda pergunta de volta pra ela."""
        from app.orchestrator.orchestrator import rotear_clique_botao_a2

        button_id = button_ids.montar_button_id_escolher_parcial(
            CONTRACT_ID, ["charge-aluguel", "charge-agua"]
        )

        with patch("app.orchestrator.orchestrator.processar_entrada_a2") as mock_processar:
            rotear_clique_botao_a2(button_id, "+5581977776666")

        entrada_passada = mock_processar.call_args[0][0]
        assert entrada_passada.telefone_remetente == "+5581977776666"
        assert entrada_passada.contract_id == CONTRACT_ID
        assert entrada_passada.charge_ids == ["charge-aluguel", "charge-agua"]

    def test_combinado_parcial_separa_paga_das_restantes(self):
        from app.orchestrator.orchestrator import rotear_clique_botao_a2

        button_id = button_ids.montar_button_id_combinado_parcial(
            CONTRACT_ID, "charge-agua", ["charge-aluguel"]
        )

        with patch("app.orchestrator.orchestrator.processar_entrada_a2") as mock_processar:
            rotear_clique_botao_a2(button_id, "+5581988880000")

        entrada_passada = mock_processar.call_args[0][0]
        assert entrada_passada.charge_id_paga == "charge-agua"
        assert entrada_passada.charge_ids_restantes == ["charge-aluguel"]


# ======================================================================
# 4. Fluxo completo do "Só uma delas" em duas etapas
# ======================================================================


class TestFluxoPagamentoCombinadoParcialDuasEtapas:
    def test_primeira_etapa_so_pergunta_nao_altera_nenhuma_charge(self, monkeypatch):
        """iniciar_escolha_pagamento_parcial (chamada pelo 1º clique) busca
        o `tipo` de cada charge e manda a pergunta — nenhuma chamada de
        agent_update_charge_status deve acontecer aqui."""
        updates_de_status = []
        perguntas_enviadas = []

        client_fake = MagicMock()
        client_fake.table.return_value.select.return_value.in_.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "charge-aluguel", "tipo": "aluguel"},
                {"id": "charge-agua", "tipo": "agua"},
            ]
        )

        def _rpc_falha_se_chamado(nome, params):
            updates_de_status.append((nome, params))
            raise AssertionError("Nenhum RPC de status deveria rodar na 1ª etapa.")

        client_fake.rpc.side_effect = _rpc_falha_se_chamado

        def fake_notificar_pergunta(telefone, contract_id, charges):
            perguntas_enviadas.append((telefone, contract_id, charges))

        monkeypatch.setattr(comprovante, "obter_client_agente", lambda contract_id: client_fake)
        monkeypatch.setattr(comprovante, "notificar_pergunta_qual_charge_paga", fake_notificar_pergunta)

        comprovante.iniciar_escolha_pagamento_parcial(
            CONTRACT_ID, ["charge-aluguel", "charge-agua"], "+5581988880000"
        )

        assert updates_de_status == []
        assert len(perguntas_enviadas) == 1
        telefone, contract_id, charges = perguntas_enviadas[0]
        assert telefone == "+5581988880000"
        assert contract_id == CONTRACT_ID
        assert {c["tipo"] for c in charges} == {"aluguel", "agua"}

    def test_segunda_etapa_confirma_a_escolhida_e_reverte_as_demais(self, monkeypatch):
        """marcar_apenas_uma_paga (chamada pelo 2º clique) é quem de fato
        mexe no banco: confirma a paga, devolve as demais pra pendente."""
        updates_de_status = []

        client_fake = MagicMock()
        client_fake.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"data_identificada_comprovante": "2026-07-17"}
        )

        def _rpc(nome, params):
            builder = MagicMock()
            if nome == "agent_update_charge_status":
                updates_de_status.append(params)
                builder.execute.return_value = MagicMock(data=None)
            elif nome == "buscar_dados_cobranca_contrato":
                builder.execute.return_value = MagicMock(
                    data={"telefone_whatsapp": "+5581999990000", "inquilino_nome": "João"}
                )
            else:
                raise AssertionError(f"RPC inesperada: {nome}")
            return builder

        client_fake.rpc.side_effect = _rpc

        monkeypatch.setattr(comprovante, "obter_client_agente", lambda contract_id: client_fake)
        monkeypatch.setattr(comprovante, "responder_confirmacao_pagamento", lambda **kwargs: None)

        comprovante.marcar_apenas_uma_paga(CONTRACT_ID, "charge-agua", ["charge-aluguel"])

        assert {"p_charge_id": "charge-agua", "p_status": "confirmado", "p_data_pagamento": "2026-07-17"} in updates_de_status
        assert {"p_charge_id": "charge-aluguel", "p_status": "pendente"} in updates_de_status
        # A charge paga nunca aparece revertida pra pendente também.
        assert not any(u["p_charge_id"] == "charge-agua" and u["p_status"] == "pendente" for u in updates_de_status)
