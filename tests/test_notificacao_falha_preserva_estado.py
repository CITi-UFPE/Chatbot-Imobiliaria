"""Regressão dos achados do code-review na WA-05: em app/agents/a2_cobranca/
cobranca.py e app/agents/a5_escalonamento/escalonamento.py, a gravação no
banco acontecia ANTES do aviso por WhatsApp, mas se o aviso falhasse a
exceção subia e "apagava" o efeito da gravação aos olhos de quem chamou —
mesmo o dado já estando salvo de verdade. Estes testes fixam o
comportamento corrigido: falha de transporte é logada, mas nunca desfaz
nem esconde um efeito de negócio que já aconteceu.

Só mocka a camada que fala com o Supabase (obter_client_agente /
obter_client_cron_batch) e o transporte de WhatsApp (enviar_mensagem_cobranca
/ notificar_staff) — mesmo padrão de tests/testar_a2_manual.py.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.agents.a5_escalonamento.escalonamento import AvaliacaoEscalonamento, executar_escalonamento

HOJE = date(2026, 7, 17)

DADOS_CONTRATO_PADRAO = {
    "telefone_whatsapp": "+5581999990000",
    "inquilino_nome": "João Pereira",
    "imovel_identificacao": "Apto 305, Ed. Girassol",
    "multa_moratoria_percentual": 0.02,
    "juros_moratorio_mensal": 0.01,
}


def _charge_raw(*, dias_offset: int, status: str, mensagem_estagio, dias_atraso_salvo: int) -> dict:
    vencimento = HOJE - timedelta(days=dias_offset)
    return {
        "contract_id": "11111111-1111-1111-1111-111111111111",
        "charge_id": "charge-teste",
        "tipo": "aluguel",
        "mes_referencia": vencimento.replace(day=1).isoformat(),
        "valor_esperado": 2200.0,
        "data_vencimento": vencimento.isoformat(),
        "data_pagamento": None,
        "dias_atraso": dias_atraso_salvo,
        "status": status,
        "mensagem_estagio": mensagem_estagio,
    }


def _client_agente_fake(updates_registrados: list) -> MagicMock:
    client = MagicMock()

    def _rpc(nome_funcao: str, parametros: dict):
        builder = MagicMock()
        if nome_funcao == "buscar_dados_cobranca_contrato":
            builder.execute.return_value = MagicMock(data=DADOS_CONTRATO_PADRAO)
        elif nome_funcao == "agent_update_charge_status":
            updates_registrados.append(parametros)
            builder.execute.return_value = MagicMock(data=None)
        else:
            raise ValueError(f"RPC não mockada neste teste: {nome_funcao}")
        return builder

    client.rpc.side_effect = _rpc
    return client


class TestFalhaDeEnvioNaoBloqueiaRecalculoDiarioDoCron:
    def test_d5_falha_no_envio_ainda_atualiza_dias_atraso_e_status(self):
        """D-5 simples: mesmo se o WhatsApp falhar, dias_atraso/status têm
        que ser recalculados hoje (não podem ficar travados esperando o
        envio dar certo)."""
        charge_raw = _charge_raw(
            dias_offset=-5, status="pendente", mensagem_estagio=None, dias_atraso_salvo=999
        )
        updates: list = []
        client_agente_fake = _client_agente_fake(updates)

        with patch(
            "app.agents.a2_cobranca.cobranca.obter_client_agente", return_value=client_agente_fake
        ), patch(
            "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca",
            side_effect=RuntimeError("Meta fora do ar"),
        ):
            from app.agents.a2_cobranca.cobranca import _processar_charge

            _processar_charge(charge_raw, HOJE)  # não deve levantar

        assert len(updates) == 1
        assert updates[0]["p_dias_atraso"] == -5
        assert updates[0]["p_status"] == "pendente"
        # mensagem_estagio NÃO avança pra "d-5" — o envio falhou, então o
        # cron de amanhã precisa continuar achando que ainda não mandou.
        assert updates[0]["p_mensagem_estagio"] is None

    def test_d15_falha_no_envio_nao_marca_estagio_nem_escala(self):
        """D+15: se o envio falhar, nem o estágio pode ser marcado como
        enviado, nem o escalonamento automático pode disparar — os dois
        dependem da mensagem ter saído de verdade."""
        charge_raw = _charge_raw(
            dias_offset=15, status="atrasado", mensagem_estagio="d+10", dias_atraso_salvo=10
        )
        updates: list = []
        client_agente_fake = _client_agente_fake(updates)
        escalonamentos: list = []

        with patch(
            "app.agents.a2_cobranca.cobranca.obter_client_agente", return_value=client_agente_fake
        ), patch(
            "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca",
            side_effect=RuntimeError("Meta fora do ar"),
        ), patch(
            "app.agents.a2_cobranca.cobranca.executar_escalonamento",
            side_effect=lambda *a, **k: escalonamentos.append((a, k)),
        ):
            from app.agents.a2_cobranca.cobranca import _processar_charge

            _processar_charge(charge_raw, HOJE)

        assert len(updates) == 1
        assert updates[0]["p_dias_atraso"] == 15
        assert updates[0]["p_status"] == "atrasado"
        assert updates[0]["p_mensagem_estagio"] == "d+10"  # continua o antigo, não virou "d+15"
        assert escalonamentos == []  # não escala sem a mensagem ter saído

    def test_d15_sucesso_no_envio_marca_estagio_e_escala_normalmente(self):
        """Regressão de compatibilidade: quando o envio dá certo, o
        comportamento continua o mesmo de antes da correção — estágio
        avança e o escalonamento automático dispara."""
        charge_raw = _charge_raw(
            dias_offset=15, status="atrasado", mensagem_estagio="d+10", dias_atraso_salvo=10
        )
        updates: list = []
        client_agente_fake = _client_agente_fake(updates)
        escalonamentos: list = []

        with patch(
            "app.agents.a2_cobranca.cobranca.obter_client_agente", return_value=client_agente_fake
        ), patch(
            "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca", return_value=None
        ), patch(
            "app.agents.a2_cobranca.cobranca.executar_escalonamento",
            side_effect=lambda contract_id, avaliacao: escalonamentos.append((contract_id, avaliacao)),
        ):
            from app.agents.a2_cobranca.cobranca import _processar_charge

            _processar_charge(charge_raw, HOJE)

        assert updates[0]["p_mensagem_estagio"] == "d+15"
        assert len(escalonamentos) == 1
        assert escalonamentos[0][1].motivo == "atraso_severo"


class TestExecutarEscalonamentoSobreviveAFalhaDeNotificacao:
    def test_falha_ao_notificar_staff_nao_apaga_protocolo_ja_gravado(self):
        client_fake = MagicMock()
        client_fake.rpc.return_value.execute.return_value = MagicMock(data="ESC-2026-00042")

        avaliacao = AvaliacaoEscalonamento(
            motivo="pedido_humano",
            descricao="Inquilino pediu falar com uma pessoa.",
            resposta_para_inquilino="Encaminhamos seu caso para a equipe.",
        )

        with patch(
            "app.agents.a5_escalonamento.escalonamento.obter_client_agente", return_value=client_fake
        ), patch(
            "app.agents.a5_escalonamento.escalonamento.notificar_staff",
            side_effect=RuntimeError("Meta fora do ar"),
        ):
            protocolo = executar_escalonamento("22222222-2222-2222-2222-222222222222", avaliacao)

        # A escalação já estava gravada no banco (RPC acima) — o protocolo
        # tem que voltar pro chamador mesmo com o aviso à equipe falhando.
        assert protocolo == "ESC-2026-00042"

    def test_sucesso_ao_notificar_staff_continua_funcionando_normalmente(self):
        client_fake = MagicMock()
        client_fake.rpc.return_value.execute.return_value = MagicMock(data="ESC-2026-00043")
        chamadas_staff: list = []

        avaliacao = AvaliacaoEscalonamento(
            motivo="ameaca_juridica",
            descricao="Inquilino ameaçou processar a imobiliária.",
            resposta_para_inquilino="Seu caso foi encaminhado para a equipe.",
        )

        with patch(
            "app.agents.a5_escalonamento.escalonamento.obter_client_agente", return_value=client_fake
        ), patch(
            "app.agents.a5_escalonamento.escalonamento.notificar_staff",
            side_effect=lambda mensagem: chamadas_staff.append(mensagem),
        ):
            protocolo = executar_escalonamento("33333333-3333-3333-3333-333333333333", avaliacao)

        assert protocolo == "ESC-2026-00043"
        assert len(chamadas_staff) == 1
        assert "ESC-2026-00043" in chamadas_staff[0]
