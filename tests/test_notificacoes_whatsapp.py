"""Testes do transporte WhatsApp do A2 (cobrança/comprovante) e do A5
(escalonamento) — WA-05/WA-06. Cobre todas as funções públicas de
app/agents/a2_cobranca/notificacao.py e app/agents/a5_escalonamento/
notificacao.py em modo simulado (kill switch desligado), sucesso (cliente
mockado) e falha (cliente mockado levantando). Nenhum destes testes acessa
a Meta de verdade: em modo simulado, whatsapp_client.enviar_texto/
enviar_template/enviar_botoes já retornam sem chamada HTTP sozinhos; nos
demais casos, essas funções são substituídas por um fake via monkeypatch,
igual ao padrão de tests/test_a4_whatsapp_notification.py.

WA-06/WA-08: notificações iniciais de comprovante para a gestão usam
templates com quick replies e payloads decodificáveis. A segunda etapa
provisória de "Só uma delas" permanece coberta em
tests/test_a2_whatsapp_buttons.py até a aprovação do novo fluxo.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.agents.a2_cobranca import button_ids
from app.agents.a2_cobranca import notificacao as notif_a2
from app.agents.a5_escalonamento import notificacao as notif_a5
from app.tools import whatsapp_client as wc
from app.tools.whatsapp_message_policy import MensagemTemplate


@pytest.fixture(autouse=True)
def _kill_switch_desligado_por_padrao(monkeypatch):
    """Nenhum teste deste arquivo deve depender de variáveis de WhatsApp
    presentes no ambiente real (.env local) — cada teste liga o que
    precisa explicitamente."""
    monkeypatch.delenv("WHATSAPP_ENVIO_ATIVO", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_STAFF_PHONE_NUMBER", raising=False)


# ======================================================================
# A2 — Cobrança (enviar_mensagem_cobranca) — proativo, via template
# ======================================================================


class TestEnviarMensagemCobranca:
    def test_modo_simulado_nao_faz_rede_nem_exige_configuracao(self):
        notif_a2.enviar_mensagem_cobranca(
            "+5581999990000",
            MensagemTemplate(nome="aviso_vencimento", parametros=("João", "aluguel", "10/09/2026")),
        )

    def test_sucesso_chama_enviar_template_estruturado(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome, parametros))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.COB1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        mensagem = MensagemTemplate(
            nome="aviso_vencimento",
            parametros=("João", "o aluguel do Apto 305", "10/09/2026"),
        )
        notif_a2.enviar_mensagem_cobranca("+5581999990000", mensagem)

        assert chamadas == [
            (
                "+5581999990000",
                "aviso_vencimento",
                ["João", "o aluguel do Apto 305", "10/09/2026"],
            )
        ]

    def test_falha_do_cliente_propaga_e_loga_telefone_mascarado(self, monkeypatch, caplog):
        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("Meta fora do ar")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        telefone = "+5581999990000"
        with caplog.at_level("ERROR"):
            with pytest.raises(wc.WhatsAppTransientError):
                notif_a2.enviar_mensagem_cobranca(
                    telefone,
                    MensagemTemplate(nome="aviso_vencimento"),
                )

        assert telefone not in caplog.text
        assert wc.mascarar_telefone(telefone) in caplog.text


# ======================================================================
# A2 — notificações à gestão por template e resposta ao inquilino pela janela
# ======================================================================


class TestNotificarFernandaComprovante:
    CONTRACT_ID = "11111111-1111-1111-1111-111111111111"
    CHARGE_ID = "charge-abc"

    def test_modo_simulado_nao_faz_rede(self):
        notif_a2.notificar_fernanda_comprovante(
            "+5581988880000",
            self.CONTRACT_ID,
            self.CHARGE_ID,
            "João Pereira",
            "Apto 305",
            2200.0,
            "2026-07-15",
            2200.0,
        )

    def test_sucesso_chama_template_com_parametros_e_ids_corretos(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR", *, botoes=None):
            chamadas.append((telefone, nome, parametros, lang, botoes))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.FER1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.notificar_fernanda_comprovante(
            "+5581988880000",
            self.CONTRACT_ID,
            self.CHARGE_ID,
            "João Pereira",
            "Apto 305",
            2200.0,
            "2026-07-15",
            2200.0,
            nota_deteccao_automatica="Identificado automaticamente como aluguel.",
        )

        assert len(chamadas) == 1
        telefone, nome, parametros, idioma, botoes = chamadas[0]
        assert telefone == "+5581988880000"
        assert nome == "comprovante_para_conferencia"
        assert idioma == "pt_BR"
        assert parametros == [
            "João Pereira",
            "Apto 305",
            "R$ 2.200,00",
            "2026-07-15",
            "2.200,00",
            "Correspondência identificada automaticamente pelo valor",
        ]

        confirmar = button_ids.decodificar_button_id(botoes[0])
        assert confirmar.acao == button_ids.ACAO_CONFIRMAR
        assert confirmar.contract_id == self.CONTRACT_ID
        assert confirmar.charge_ids == [self.CHARGE_ID]
        divergente = button_ids.decodificar_button_id(botoes[1])
        assert divergente.acao == button_ids.ACAO_DIVERGENTE
        assert divergente.contract_id == self.CONTRACT_ID
        assert divergente.charge_ids == [self.CHARGE_ID]

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppPermanentError("número inválido")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        with pytest.raises(wc.WhatsAppPermanentError):
            notif_a2.notificar_fernanda_comprovante(
                "+5581988880000",
                self.CONTRACT_ID,
                self.CHARGE_ID,
                "João Pereira",
                "Apto 305",
                2200.0,
                "2026-07-15",
                2200.0,
            )


class TestNotificarFernandaPagamentoCombinado:
    CONTRACT_ID = "22222222-2222-2222-2222-222222222222"
    CHARGES = [
        {"id": "charge-aluguel", "tipo": "aluguel", "valor_esperado": 2200.0},
        {"id": "charge-agua", "tipo": "agua", "valor_esperado": 100.0},
    ]

    def test_modo_simulado_nao_faz_rede(self):
        notif_a2.notificar_fernanda_pagamento_combinado(
            "+5581988880000", self.CONTRACT_ID, "João Pereira", "Apto 305", 2300.0, "2026-07-17", self.CHARGES
        )

    def test_sucesso_chama_template_com_parametros_e_ids_corretos(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR", *, botoes=None):
            chamadas.append((telefone, nome, parametros, botoes))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.COMB1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.notificar_fernanda_pagamento_combinado(
            "+5581988880000", self.CONTRACT_ID, "João Pereira", "Apto 305", 2300.0, "2026-07-17", self.CHARGES
        )

        assert len(chamadas) == 1
        telefone, nome, parametros, botoes = chamadas[0]
        assert telefone == "+5581988880000"
        assert nome == "pagamento_combinado"
        assert parametros == [
            "João Pereira",
            "Apto 305",
            "R$ 2.300,00",
            "2026-07-17",
            "2.300,00",
            "- Aluguel: R$ 2.200,00\n- Água: R$ 100,00",
        ]

        decod_todos = button_ids.decodificar_button_id(botoes[0])
        assert decod_todos.acao == button_ids.ACAO_COMBINADO_TODOS
        assert decod_todos.contract_id == self.CONTRACT_ID
        assert decod_todos.charge_ids == ["charge-aluguel", "charge-agua"]

        decod_agua = button_ids.decodificar_button_id(botoes[1])
        assert decod_agua.acao == button_ids.ACAO_COMBINADO_PARCIAL
        assert decod_agua.contract_id == self.CONTRACT_ID
        assert decod_agua.charge_ids == ["charge-agua", "charge-aluguel"]

        decod_aluguel = button_ids.decodificar_button_id(botoes[2])
        assert decod_aluguel.acao == button_ids.ACAO_COMBINADO_PARCIAL
        assert decod_aluguel.contract_id == self.CONTRACT_ID
        assert decod_aluguel.charge_ids == ["charge-aluguel", "charge-agua"]

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("timeout")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        with pytest.raises(wc.WhatsAppTransientError):
            notif_a2.notificar_fernanda_pagamento_combinado(
                "+5581988880000", self.CONTRACT_ID, "João Pereira", "Apto 305", 2300.0, "2026-07-17", self.CHARGES
            )


class TestNotificarFernandaSemMatch:
    CHARGES = [{"tipo": "aluguel", "valor_esperado": 2200.0}]

    def test_modo_simulado_nao_faz_rede(self):
        notif_a2.notificar_fernanda_sem_match(
            "+5581988880000", "João Pereira", "Apto 305", 500.0, "2026-07-17", self.CHARGES
        )

    def test_sucesso_chama_template_sem_botoes(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome, parametros))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.SEM1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.notificar_fernanda_sem_match(
            "+5581988880000", "João Pereira", "Apto 305", 500.0, "2026-07-17", self.CHARGES
        )

        assert chamadas == [
            (
                "+5581988880000",
                "comprovante_sem_correspondencia",
                [
                    "João Pereira",
                    "Apto 305",
                    "R$ 500,00",
                    "2026-07-17",
                    "- Aluguel: R$ 2.200,00",
                ],
            )
        ]

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppConteudoInvalidoError("telefone inválido")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        with pytest.raises(wc.WhatsAppConteudoInvalidoError):
            notif_a2.notificar_fernanda_sem_match(
                "+5581988880000", "João Pereira", "Apto 305", 500.0, "2026-07-17", self.CHARGES
            )

    def test_destino_vazio_usa_telefone_staff_quando_envio_esta_ativo(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.SEM2")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.notificar_fernanda_sem_match(
            "", "João Pereira", "Apto 305", 500.0, "2026-07-17", self.CHARGES
        )

        assert chamadas == [
            ("+5581988887777", "comprovante_sem_correspondencia")
        ]


class TestResponderConfirmacaoPagamento:
    @staticmethod
    def _client_com_ultima_mensagem(valor):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = MagicMock(data=valor)
        return client

    def test_modo_simulado_nao_faz_rede(self):
        client = self._client_com_ultima_mensagem(datetime.now(timezone.utc).isoformat())
        notif_a2.responder_confirmacao_pagamento(client, "+5581999990000", "João Pereira")

    def test_sucesso_chama_enviar_texto_com_telefone_e_nome_corretos(self, monkeypatch):
        chamadas = []

        def fake_enviar_texto(telefone, texto):
            chamadas.append((telefone, texto))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.CONF1")

        monkeypatch.setattr(wc, "enviar_texto", fake_enviar_texto)

        client = self._client_com_ultima_mensagem(datetime.now(timezone.utc).isoformat())
        notif_a2.responder_confirmacao_pagamento(client, "+5581999990000", "João Pereira")

        assert chamadas == [
            ("+5581999990000", "Recebemos seu comprovante, João Pereira. Pagamento confirmado, obrigado!")
        ]

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_texto_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("Meta fora do ar")

        monkeypatch.setattr(wc, "enviar_texto", enviar_texto_com_falha)

        client = self._client_com_ultima_mensagem(datetime.now(timezone.utc).isoformat())
        with pytest.raises(wc.WhatsAppTransientError):
            notif_a2.responder_confirmacao_pagamento(
                client, "+5581999990000", "João Pereira"
            )

    def test_janela_indeterminada_usa_template_pagamento_confirmado(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome, parametros))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.CONF2")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.responder_confirmacao_pagamento(
            self._client_com_ultima_mensagem(None),
            "+5581999990000",
            "João Pereira",
        )

        assert chamadas == [
            ("+5581999990000", "pagamento_confirmado", ["João Pereira"])
        ]


# ======================================================================
# A5 — notificar_staff — sempre proativo (equipe), via template
# ======================================================================


class TestNotificarStaff:
    def test_modo_simulado_nao_exige_telefone_nem_faz_rede(self):
        resultado = notif_a5.notificar_staff("Novo caso escalado — protocolo ESC-2026-00001")

        assert resultado is None

    def test_ativo_sem_telefone_staff_levanta_erro_claro(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")

        with pytest.raises(RuntimeError, match="WHATSAPP_STAFF_PHONE_NUMBER"):
            notif_a5.notificar_staff("Novo caso escalado — protocolo ESC-2026-00001")

    def test_ativo_com_telefone_envia_template_com_mensagem_completa(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome, parametros))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.ESC1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a5.notificar_staff("Novo caso escalado — protocolo ESC-2026-00001\nMotivo: pedido_humano")

        assert chamadas == [
            (
                "+5581988887777",
                notif_a5._TEMPLATE_ESCALONAMENTO_EQUIPE,
                ["Novo caso escalado — protocolo ESC-2026-00001\nMotivo: pedido_humano"],
            )
        ]

    def test_falha_do_cliente_propaga_e_loga_telefone_mascarado(self, monkeypatch, caplog):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("Meta fora do ar")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        telefone_staff = "+5581988887777"
        with caplog.at_level("ERROR"):
            with pytest.raises(wc.WhatsAppTransientError):
                notif_a5.notificar_staff("Novo caso escalado")

        assert telefone_staff not in caplog.text
        assert wc.mascarar_telefone(telefone_staff) in caplog.text

    def test_escalonamento_usa_tres_parametros_na_ordem_meta(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome, parametros, lang))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.ESC2")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a5.notificar_staff_escalonamento(
            "ESC-2026-00042",
            "pedido_humano",
            "Inquilino pediu atendimento humano.",
        )

        assert chamadas == [
            (
                "+5581988887777",
                "escalonamento_equipe",
                ["ESC-2026-00042", "pedido_humano", "Inquilino pediu atendimento humano."],
                "pt_BR",
            )
        ]


# ======================================================================
# A3 — notificar_staff_manutencao — template próprio (checkup pós-WA-06/WA-08)
# ======================================================================


class TestNotificarStaffManutencao:
    """notificar_staff_manutencao usa o template manutencao_equipe (5
    variáveis), não escalonamento_equipe (3) — o A3 reutilizava o último com
    só 1 parâmetro, o que a Meta rejeitaria com envio real ativo."""

    _PARAMETROS = [
        "MNT-2026-0001",
        "Rua X, 123, apto 302",
        "hidraulica",
        "alta",
        "Vazamento no banheiro",
    ]

    def test_modo_simulado_nao_exige_telefone_nem_faz_rede(self):
        resultado = notif_a5.notificar_staff_manutencao(self._PARAMETROS)

        assert resultado is None

    def test_ativo_sem_telefone_staff_levanta_erro_claro(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")

        with pytest.raises(RuntimeError, match="WHATSAPP_STAFF_PHONE_NUMBER"):
            notif_a5.notificar_staff_manutencao(self._PARAMETROS)

    def test_ativo_usa_template_e_cinco_parametros_na_ordem_recebida(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome, parametros, lang))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.MNT1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a5.notificar_staff_manutencao(self._PARAMETROS)

        assert chamadas == [
            ("+5581988887777", notif_a5._TEMPLATE_MANUTENCAO_EQUIPE, self._PARAMETROS, "pt_BR")
        ]
        # nunca usa o template de escalonamento por engano
        assert notif_a5._TEMPLATE_MANUTENCAO_EQUIPE != notif_a5._TEMPLATE_ESCALONAMENTO_EQUIPE

    def test_falha_do_cliente_propaga_e_loga_telefone_mascarado(self, monkeypatch, caplog):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("Meta fora do ar")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        telefone_staff = "+5581988887777"
        with caplog.at_level("ERROR"):
            with pytest.raises(wc.WhatsAppTransientError):
                notif_a5.notificar_staff_manutencao(self._PARAMETROS)

        assert telefone_staff not in caplog.text
        assert wc.mascarar_telefone(telefone_staff) in caplog.text
