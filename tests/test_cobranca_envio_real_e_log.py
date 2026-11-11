"""Cron de cobrança do A2 com o kill switch (WHATSAPP_ENVIO_ATIVO) e o
registro em conversation_logs.

Contexto: com o envio desligado o whatsapp_client devolve sucesso simulado
sem mandar nada, e o cron marcava mensagem_estagio como "avisado" (e, no
d+15, abria escalonamento) sem o inquilino ter recebido a cobrança. Estes
testes fixam: envio simulado não marca estágio nem escala; envio real marca
estágio e grava em conversation_logs; falha ao gravar o log nunca desfaz um
envio que já saiu.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from tenacity import wait_none

from app.agents.a2_cobranca.mensagens import renderizar_template_cobranca
from app.tools.conversation_log import registrar_mensagem_automatica
from app.tools.whatsapp_client import ResultadoEnvio
from app.tools.whatsapp_message_policy import MensagemTemplate

HOJE = date(2026, 10, 26)

DADOS_CONTRATO = {
    "telefone_whatsapp": "+5581999990000",
    "inquilino_nome": "Ewerton",
    "imovel_identificacao": "Apto 2702, Ed. Golden Beach",
    "multa_moratoria_percentual": 0.02,
    "juros_moratorio_mensal": 0.01,
}

REAL = ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.TESTE")
SIMULADO = ResultadoEnvio(sucesso=True, simulado=True)


def _charge_raw(*, dias_atraso_hoje: int, mensagem_estagio, status="atrasado") -> dict:
    vencimento = HOJE - timedelta(days=dias_atraso_hoje)
    return {
        "contract_id": "11111111-1111-1111-1111-111111111111",
        "charge_id": "charge-teste",
        "tipo": "aluguel",
        "mes_referencia": vencimento.replace(day=1).isoformat(),
        "valor_esperado": 3150.0,
        "data_vencimento": vencimento.isoformat(),
        "data_pagamento": None,
        "dias_atraso": dias_atraso_hoje - 1,
        "status": status,
        "mensagem_estagio": mensagem_estagio,
    }


def _client_agente_fake(updates: list, logs: list) -> MagicMock:
    client = MagicMock()

    def _rpc(nome_funcao: str, parametros: dict):
        builder = MagicMock()
        if nome_funcao == "buscar_dados_cobranca_contrato":
            builder.execute.return_value = MagicMock(data=DADOS_CONTRATO)
        elif nome_funcao == "agent_update_charge_status":
            updates.append(parametros)
            builder.execute.return_value = MagicMock(data=None)
        elif nome_funcao == "agent_log_message":
            logs.append(parametros)
            builder.execute.return_value = MagicMock(data=None)
        else:
            raise ValueError(f"RPC não mockada neste teste: {nome_funcao}")
        return builder

    client.rpc.side_effect = _rpc
    return client


def _processar(charge_raw: dict, *, resultado_envio, escalonamentos: list, **patch_extra):
    updates: list = []
    logs: list = []
    client = _client_agente_fake(updates, logs)
    with patch(
        "app.agents.a2_cobranca.cobranca.obter_client_agente", return_value=client
    ), patch(
        "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca", return_value=resultado_envio
    ), patch(
        "app.agents.a2_cobranca.cobranca.executar_escalonamento",
        side_effect=lambda *a, **k: escalonamentos.append((a, k)),
    ):
        from app.agents.a2_cobranca.cobranca import _processar_charge

        _processar_charge(charge_raw, HOJE)
    return updates, logs


class TestEnvioSimuladoNaoMarcaEstagio:
    def test_d5_simulado_nao_marca_estagio_nem_grava_log(self):
        escalonamentos: list = []
        updates, logs = _processar(
            _charge_raw(dias_atraso_hoje=5, mensagem_estagio="d0"),
            resultado_envio=SIMULADO,
            escalonamentos=escalonamentos,
        )

        assert len(updates) == 1
        assert updates[0]["p_dias_atraso"] == 5  # recálculo diário continua
        assert updates[0]["p_mensagem_estagio"] == "d0"  # NÃO virou d+5
        assert logs == []

    def test_d15_simulado_nao_marca_estagio_nem_escala(self):
        escalonamentos: list = []
        updates, logs = _processar(
            _charge_raw(dias_atraso_hoje=15, mensagem_estagio="d+10"),
            resultado_envio=SIMULADO,
            escalonamentos=escalonamentos,
        )

        assert updates[0]["p_mensagem_estagio"] == "d+10"
        assert escalonamentos == []
        assert logs == []


class TestEnvioRealMarcaEstagioEGravaLog:
    def test_d5_real_marca_estagio_e_grava_texto_do_template(self):
        escalonamentos: list = []
        updates, logs = _processar(
            _charge_raw(dias_atraso_hoje=5, mensagem_estagio="d0"),
            resultado_envio=REAL,
            escalonamentos=escalonamentos,
        )

        assert updates[0]["p_mensagem_estagio"] == "d+5"
        assert len(logs) == 1
        assert logs[0]["p_remetente"] == "agente"
        assert logs[0]["p_agente_responsavel"] == "A2"
        assert "Ewerton" in logs[0]["p_mensagem"]
        assert "o aluguel do Apto 2702, Ed. Golden Beach" in logs[0]["p_mensagem"]
        assert "{{" not in logs[0]["p_mensagem"]  # nenhum parâmetro ficou sem substituir

    def test_d15_real_marca_estagio_e_escala(self):
        escalonamentos: list = []
        updates, logs = _processar(
            _charge_raw(dias_atraso_hoje=15, mensagem_estagio="d+10"),
            resultado_envio=REAL,
            escalonamentos=escalonamentos,
        )

        assert updates[0]["p_mensagem_estagio"] == "d+15"
        assert len(escalonamentos) == 1
        assert len(logs) == 1

    def test_falha_ao_gravar_log_nao_desfaz_envio_que_ja_saiu(self):
        escalonamentos: list = []
        with patch(
            "app.tools.conversation_log.registrar_mensagem_automatica",
            side_effect=RuntimeError("banco fora"),
        ):
            updates, _ = _processar(
                _charge_raw(dias_atraso_hoje=15, mensagem_estagio="d+10"),
                resultado_envio=REAL,
                escalonamentos=escalonamentos,
            )

        assert updates[0]["p_mensagem_estagio"] == "d+15"  # estágio marcado mesmo assim
        assert len(escalonamentos) == 1  # e o escalonamento não foi perdido


class TestRenderizarTemplateCobranca:
    def test_aviso_vencimento_substitui_parametros(self):
        texto = renderizar_template_cobranca(
            MensagemTemplate(
                nome="aviso_vencimento",
                parametros=("Ewerton", "o aluguel do Apto 2702", "21/10/2026"),
            )
        )
        assert texto == (
            "Olá, Ewerton! Passando para lembrar que o aluguel do Apto 2702 vence dia "
            "21/10/2026. Qualquer dúvida, é só chamar por aqui."
        )

    def test_aviso_atraso_usa_os_oito_parametros(self):
        texto = renderizar_template_cobranca(
            MensagemTemplate(
                nome="aviso_atraso",
                parametros=(
                    "Ewerton",
                    "sua conta de água",
                    "21/10/2026",
                    "5",
                    "29,71",
                    "0,59",
                    "0,25",
                    "30,55",
                ),
            )
        )
        assert "{{" not in texto
        assert "há 5 dias" in texto
        assert "Valor total atualizado: R$ 30,55" in texto

    def test_template_desconhecido_nao_levanta(self):
        texto = renderizar_template_cobranca(MensagemTemplate(nome="outro", parametros=("a", "b")))
        assert texto == "[outro] a | b"


class TestRegistrarMensagemAutomatica:
    def test_grava_como_agente_com_o_agente_informado(self):
        client = MagicMock()
        registrar_mensagem_automatica(client, agente="A2", mensagem="texto")

        client.rpc.assert_called_once_with(
            "agent_log_message",
            {"p_remetente": "agente", "p_agente_responsavel": "A2", "p_mensagem": "texto"},
        )

    def test_tenta_de_novo_em_falha_transitoria(self):
        client = MagicMock()
        builder = MagicMock()
        builder.execute.side_effect = [RuntimeError("rede"), MagicMock()]
        client.rpc.return_value = builder

        with patch.object(registrar_mensagem_automatica.retry, "wait", wait_none()):
            registrar_mensagem_automatica(client, agente="A2", mensagem="texto")

        assert builder.execute.call_count == 2

    def test_levanta_depois_de_esgotar_as_tentativas(self):
        client = MagicMock()
        client.rpc.return_value.execute.side_effect = RuntimeError("banco fora")

        with patch.object(registrar_mensagem_automatica.retry, "wait", wait_none()):
            with pytest.raises(RuntimeError):
                registrar_mensagem_automatica(client, agente="A2", mensagem="texto")


def test_enviar_mensagem_cobranca_devolve_o_resultado_do_transporte():
    from app.agents.a2_cobranca.notificacao import enviar_mensagem_cobranca

    with patch("app.agents.a2_cobranca.notificacao.enviar_saida", return_value=SIMULADO):
        resultado = enviar_mensagem_cobranca(
            "+5581999990000", MensagemTemplate(nome="aviso_vencimento", parametros=("a", "b", "c"))
        )

    assert resultado.simulado is True


class TestConfirmacaoDePagamentoGravaNoLog:
    def _responder(self, resultado_envio, client):
        from app.agents.a2_cobranca.notificacao import responder_confirmacao_pagamento
        from app.tools.whatsapp_message_policy import MensagemTexto

        with patch(
            "app.agents.a2_cobranca.notificacao.decidir_saida_para_contrato",
            return_value=MensagemTexto(texto="saida"),
        ), patch("app.agents.a2_cobranca.notificacao.enviar_saida", return_value=resultado_envio):
            responder_confirmacao_pagamento(client, "+5581999990000", "Ewerton")

    def test_envio_real_grava_o_texto_da_confirmacao(self):
        client = MagicMock()
        self._responder(REAL, client)

        client.rpc.assert_called_once_with(
            "agent_log_message",
            {
                "p_remetente": "agente",
                "p_agente_responsavel": "A2",
                "p_mensagem": "Recebemos seu comprovante, Ewerton. Pagamento confirmado, obrigado!",
            },
        )

    def test_envio_simulado_nao_grava(self):
        client = MagicMock()
        self._responder(SIMULADO, client)

        client.rpc.assert_not_called()

    def test_falha_ao_gravar_log_nao_levanta(self):
        client = MagicMock()
        client.rpc.return_value.execute.side_effect = RuntimeError("banco fora")

        with patch.object(registrar_mensagem_automatica.retry, "wait", wait_none()):
            self._responder(REAL, client)  # não deve levantar
