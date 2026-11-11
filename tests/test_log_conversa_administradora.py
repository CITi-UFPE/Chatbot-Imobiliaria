"""Conversa com a administradora em conversation_logs (Migration 026): o que o
sistema manda a ela e o que ela responde (clique de botão, reply a
escalonamento) é gravado com canal='administradora', no contrato a que se
refere. Envio simulado e contrato desconhecido não gravam; falha de log nunca
interrompe o fluxo."""

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.agents.a2_cobranca import notificacao as notif_a2
from app.agents.a2_cobranca.button_ids import montar_button_id_confirmar
from app.agents.a4_gestao_contratual import fluxo as fluxo_a4
from app.agents.a5_escalonamento import notificacao as notif_a5
from app.orchestrator import orchestrator as orq
from app.tools import conversation_log as cl
from app.tools.template_corpos_administradora import renderizar_template_administradora
from app.tools.whatsapp_client import ResultadoEnvio

CONTRATO = "11111111-1111-1111-1111-111111111111"
CHARGE = "22222222-2222-2222-2222-222222222222"
ENVIO_REAL = ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.X")
ENVIO_SIMULADO = ResultadoEnvio(sucesso=True, simulado=True)


# --- módulo de log ---------------------------------------------------------


def test_canal_inquilino_nao_manda_p_canal():
    """Antes da Migration 026 a RPC não conhece p_canal: o chat com o inquilino
    não pode quebrar por causa dela."""
    client = MagicMock()

    cl.registrar_mensagem_automatica(client, agente="A2", mensagem="oi")

    client.rpc.assert_called_once_with(
        "agent_log_message",
        {"p_remetente": "agente", "p_agente_responsavel": "A2", "p_mensagem": "oi"},
    )


def test_canal_administradora_manda_p_canal_e_remetente():
    client = MagicMock()

    cl.registrar_mensagem_automatica(
        client, agente="A5", mensagem="resposta", remetente="gestora", canal=cl.CANAL_ADMINISTRADORA
    )

    client.rpc.assert_called_once_with(
        "agent_log_message",
        {
            "p_remetente": "gestora",
            "p_agente_responsavel": "A5",
            "p_mensagem": "resposta",
            "p_canal": "administradora",
        },
    )


def test_registrar_conversa_administradora_grava_no_contrato_do_client():
    client = MagicMock()
    with patch("app.orchestrator.agent_auth.obter_client_agente", return_value=client) as obter:
        cl.registrar_conversa_administradora(
            CONTRATO, mensagem="x", agente="A2", remetente="agente", contexto="t"
        )

    obter.assert_called_once_with(CONTRATO)
    assert client.rpc.call_args.args[1]["p_canal"] == "administradora"


@pytest.mark.parametrize("contract_id,enviado", [(None, True), ("", True), (CONTRATO, False)])
def test_registrar_conversa_administradora_nao_grava_sem_contrato_ou_simulado(contract_id, enviado):
    with patch("app.orchestrator.agent_auth.obter_client_agente") as obter:
        cl.registrar_conversa_administradora(
            contract_id, mensagem="x", agente="A2", remetente="agente", contexto="t", enviado=enviado
        )

    obter.assert_not_called()


def test_registrar_conversa_administradora_nunca_levanta():
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = RuntimeError("banco fora")
    with patch("app.orchestrator.agent_auth.obter_client_agente", return_value=client), patch(
        "app.tools.conversation_log.registrar_mensagem_automatica.retry.wait", lambda *a, **k: 0
    ):
        cl.registrar_conversa_administradora(
            CONTRATO, mensagem="x", agente="A2", remetente="agente", contexto="t"
        )

    with patch("app.orchestrator.agent_auth.obter_client_agente", side_effect=RuntimeError("sem JWT")):
        cl.registrar_conversa_administradora(
            CONTRATO, mensagem="x", agente="A2", remetente="agente", contexto="t"
        )


def test_envio_foi_real():
    assert cl.envio_foi_real(ENVIO_REAL) is True
    assert cl.envio_foi_real(ENVIO_SIMULADO) is False
    assert cl.envio_foi_real(None) is True


# --- renderização dos templates -------------------------------------------


def test_renderiza_template_com_parametros_no_lugar():
    texto = renderizar_template_administradora(
        "alerta_contratual", ["Reajuste de aluguel", "Contrato X reajusta dia 10."]
    )

    assert texto.startswith("Alerta de gestão contratual — Reajuste de aluguel")
    assert "Contrato X reajusta dia 10." in texto
    assert "{{" not in texto


def test_renderiza_escalonamento_respeitando_a_ordem_dos_parametros():
    texto = renderizar_template_administradora(
        "escalonamento_equipe", ["ESC-1", "pedido_humano", "Quer falar com alguém.", "João", "Apto 1", "+55819"]
    )

    assert "protocolo ESC-1" in texto
    assert "Inquilino: João — Apto 1" in texto
    assert "Telefone: +55819" in texto
    assert "Motivo: pedido_humano" in texto


def test_template_desconhecido_cai_no_formato_simples():
    assert renderizar_template_administradora("novo", ["a", "b"]) == "[novo] a | b"


# --- A2: notificações à Fernanda ------------------------------------------


def _notificar_comprovante():
    notif_a2.notificar_fernanda_comprovante(
        "+5581988887777", CONTRATO, CHARGE, "Ewerton", "Golden Beach 2702", 300.0, "2026-11-10", 300.0
    )


def test_comprovante_para_fernanda_e_gravado_com_o_texto_do_template():
    with patch.object(notif_a2, "enviar_saida", return_value=ENVIO_REAL), patch.object(
        notif_a2, "registrar_conversa_administradora"
    ) as registrar:
        _notificar_comprovante()

    kwargs = registrar.call_args.kwargs
    assert registrar.call_args.args == (CONTRATO,)
    assert kwargs["agente"] == "A2" and kwargs["remetente"] == "agente" and kwargs["enviado"] is True
    assert "Inquilino: Ewerton" in kwargs["mensagem"]
    assert "Imóvel: Golden Beach 2702" in kwargs["mensagem"]


def test_comprovante_para_fernanda_em_envio_simulado_nao_e_gravado():
    with patch.object(notif_a2, "enviar_saida", return_value=ENVIO_SIMULADO), patch.object(
        notif_a2, "registrar_conversa_administradora"
    ) as registrar:
        _notificar_comprovante()

    assert registrar.call_args.kwargs["enviado"] is False


def test_falha_no_envio_a_fernanda_nao_grava_e_propaga():
    with patch.object(notif_a2, "enviar_saida", side_effect=RuntimeError("Meta fora")), patch.object(
        notif_a2, "registrar_conversa_administradora"
    ) as registrar:
        with pytest.raises(RuntimeError):
            _notificar_comprovante()

    registrar.assert_not_called()


def test_pagamento_combinado_manual_grava_so_com_contract_id():
    charges = [
        {"id": "c1", "tipo": "aluguel", "valor_esperado": 4300.0, "data_vencimento": "2026-10-23"},
        {"id": "c2", "tipo": "aluguel", "valor_esperado": 4300.0, "data_vencimento": "2026-09-23"},
    ]

    def _enviar(**extra):
        notif_a2.notificar_fernanda_pagamento_combinado_manual(
            "+5581988887777", "Ewerton", "Golden Beach 2702", 8600.0, "2026-11-10", charges, **extra
        )

    with patch.object(notif_a2, "enviar_saida", return_value=ENVIO_REAL), patch.object(
        notif_a2, "registrar_conversa_administradora"
    ) as registrar:
        _enviar(contract_id=CONTRATO)
        _enviar()

    contratos = [c.args[0] for c in registrar.call_args_list]
    assert contratos == [CONTRATO, None]  # sem contrato, o helper recebe None e não grava


def test_pergunta_qual_cobranca_foi_paga_e_gravada():
    charges = [{"id": "c1", "tipo": "agua"}, {"id": "c2", "tipo": "aluguel"}]
    with patch.object(notif_a2.whatsapp_client, "enviar_botoes", return_value=ENVIO_REAL), patch.object(
        notif_a2, "registrar_conversa_administradora"
    ) as registrar:
        notif_a2.notificar_pergunta_qual_charge_paga("+5581988887777", CONTRATO, charges)

    assert registrar.call_args.args == (CONTRATO,)
    assert registrar.call_args.kwargs["mensagem"] == "Qual das cobranças foi realmente paga? [Agua / Aluguel]"


def test_sem_match_nao_grava_nada():
    """Decisão: comprovante sem correspondência não tem contrato identificado,
    então fica de fora do log (conversation_logs exige contract_id)."""
    with patch.object(notif_a2, "enviar_saida", return_value=ENVIO_REAL), patch.object(
        notif_a2, "registrar_conversa_administradora"
    ) as registrar:
        notif_a2.notificar_fernanda_sem_match(
            "+5581988887777", "Ewerton", "Golden Beach 2702", 300.0, "2026-11-10", []
        )

    registrar.assert_not_called()


# --- A5 / A3: template único para a equipe ---------------------------------


@pytest.fixture
def envio_staff_ativo(monkeypatch):
    monkeypatch.setattr(notif_a5.whatsapp_client, "envio_ativo", lambda: True)
    monkeypatch.setattr(notif_a5.whatsapp_client, "telefone_staff", lambda: "+5581988887777")


def test_escalonamento_para_a_equipe_e_gravado(envio_staff_ativo):
    with patch.object(notif_a5, "enviar_saida", return_value=ENVIO_REAL), patch.object(
        notif_a5, "registrar_conversa_administradora"
    ) as registrar:
        wamid = notif_a5.notificar_staff_escalonamento(
            "ESC-1", "pedido_humano", "Quer falar com alguém.", "João", "Apto 1", "+55819", contract_id=CONTRATO
        )

    assert wamid == "wamid.X"
    kwargs = registrar.call_args.kwargs
    assert registrar.call_args.args == (CONTRATO,)
    assert kwargs["agente"] == "A5" and kwargs["remetente"] == "agente" and kwargs["enviado"] is True
    assert "protocolo ESC-1" in kwargs["mensagem"]


def test_manutencao_para_a_equipe_e_gravada_como_a3(envio_staff_ativo):
    parametros = ["MAN-1", "Apto 1", "hidraulica", "alta", "Vazamento na pia"]
    with patch.object(notif_a5, "enviar_saida", return_value=ENVIO_REAL), patch.object(
        notif_a5, "registrar_conversa_administradora"
    ) as registrar:
        notif_a5.notificar_staff_manutencao(parametros, contract_id=CONTRATO)

    assert registrar.call_args.kwargs["agente"] == "A3"
    assert "Descrição do inquilino: Vazamento na pia" in registrar.call_args.kwargs["mensagem"]


def test_notificacao_da_equipe_simulada_nao_chega_a_gravar():
    """Kill switch desligado: _enviar_template_staff devolve antes de enviar."""
    with patch.object(notif_a5.whatsapp_client, "envio_ativo", return_value=False), patch.object(
        notif_a5, "registrar_conversa_administradora"
    ) as registrar:
        assert notif_a5.notificar_staff_escalonamento("ESC-1", "m", "d", contract_id=CONTRATO) is None

    registrar.assert_not_called()


# --- A4: alertas contratuais ----------------------------------------------


@pytest.mark.parametrize("message_id,enviado", [("wamid.A", True), (None, False)])
def test_alerta_contratual_so_e_gravado_quando_saiu(message_id, enviado):
    contrato_id = UUID(CONTRATO)
    with patch.object(fluxo_a4, "registrar_conversa_administradora") as registrar:
        fluxo_a4._registrar_alerta_na_conversa(contrato_id, "Renovação de contrato", "Vence em 60 dias.", message_id)

    kwargs = registrar.call_args.kwargs
    assert registrar.call_args.args == (CONTRATO,)
    assert kwargs["agente"] == "A4" and kwargs["enviado"] is enviado
    assert "Alerta de gestão contratual — Renovação de contrato" in kwargs["mensagem"]
    assert "Vence em 60 dias." in kwargs["mensagem"]


# --- entrada: clique de botão ----------------------------------------------


def test_clique_de_botao_e_gravado_como_gestora_no_contrato_do_botao():
    with patch.object(orq, "registrar_conversa_administradora") as registrar, patch.object(
        orq, "processar_entrada_a2"
    ) as processar:
        orq.rotear_clique_botao_a2(montar_button_id_confirmar(CONTRATO, CHARGE), "+5581988887777")

    processar.assert_called_once()
    kwargs = registrar.call_args.kwargs
    assert registrar.call_args.args == (CONTRATO,)
    assert kwargs["remetente"] == "gestora" and kwargs["agente"] == "A2"
    assert kwargs["mensagem"] == f"[Botão] Confirmar pagamento — cobrança(s) {CHARGE}"


def test_clique_e_gravado_mesmo_quando_a_acao_de_negocio_falha():
    with patch.object(orq, "registrar_conversa_administradora") as registrar, patch.object(
        orq, "processar_entrada_a2", side_effect=RuntimeError("banco fora")
    ):
        resposta = orq.rotear_clique_botao_a2(montar_button_id_confirmar(CONTRATO, CHARGE), "+55819")

    registrar.assert_called_once()
    assert "verifique manualmente" in resposta


def test_clique_com_id_desconhecido_nao_grava():
    with patch.object(orq, "registrar_conversa_administradora") as registrar:
        orq.rotear_clique_botao_a2("lixo", "+55819")

    registrar.assert_not_called()
