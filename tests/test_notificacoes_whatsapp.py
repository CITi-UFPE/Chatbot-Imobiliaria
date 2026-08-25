"""Testes do transporte WhatsApp do A2 (cobrança/comprovante) e do A5
(escalonamento) — WA-05. Cobre todas as funções públicas de
app/agents/a2_cobranca/notificacao.py e app/agents/a5_escalonamento/
notificacao.py em modo simulado (kill switch desligado), sucesso (cliente
mockado) e falha (cliente mockado levantando). Nenhum destes testes acessa
a Meta de verdade: em modo simulado, whatsapp_client.enviar_texto/
enviar_template já retornam sem chamada HTTP sozinhos; nos demais casos,
whatsapp_client.enviar_texto/enviar_template são substituídos por um fake
via monkeypatch, igual ao padrão de tests/test_a4_whatsapp_notification.py.
"""

import pytest

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
# A2 — notificações à Fernanda e resposta ao inquilino — reativo, texto livre
# ======================================================================


class TestNotificarFernandaComprovante:
    def test_modo_simulado_nao_faz_rede(self):
        notif_a2.notificar_fernanda_comprovante(
            "+5581988880000", "João Pereira", "Apto 305", 2200.0, "2026-07-15", 2200.0
        )

    def test_sucesso_chama_enviar_texto_com_conteudo_correto(self, monkeypatch):
        chamadas = []

        def fake_enviar_texto(telefone, texto):
            chamadas.append((telefone, texto))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.FER1")

        monkeypatch.setattr(wc, "enviar_texto", fake_enviar_texto)

        notif_a2.notificar_fernanda_comprovante(
            "+5581988880000",
            "João Pereira",
            "Apto 305",
            2200.0,
            "2026-07-15",
            2200.0,
            nota_deteccao_automatica="Identificado automaticamente como aluguel.",
        )

        assert len(chamadas) == 1
        telefone, texto = chamadas[0]
        assert telefone == "+5581988880000"
        assert "João Pereira" in texto
        assert "Apto 305" in texto
        assert "Identificado automaticamente como aluguel." in texto
        assert "[ Confirmar ]" in texto

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_texto_com_falha(*args, **kwargs):
            raise wc.WhatsAppPermanentError("número inválido")

        monkeypatch.setattr(wc, "enviar_texto", enviar_texto_com_falha)

        with pytest.raises(wc.WhatsAppPermanentError):
            notif_a2.notificar_fernanda_comprovante(
                "+5581988880000", "João Pereira", "Apto 305", 2200.0, "2026-07-15", 2200.0
            )


class TestNotificarFernandaPagamentoCombinado:
    CHARGES = [
        {"tipo": "aluguel", "valor_esperado": 2200.0},
        {"tipo": "agua", "valor_esperado": 100.0},
    ]

    def test_modo_simulado_nao_faz_rede(self):
        notif_a2.notificar_fernanda_pagamento_combinado(
            "+5581988880000", "João Pereira", "Apto 305", 2300.0, "2026-07-17", self.CHARGES
        )

    def test_sucesso_chama_enviar_texto_com_conteudo_correto(self, monkeypatch):
        chamadas = []

        def fake_enviar_texto(telefone, texto):
            chamadas.append((telefone, texto))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.COMB1")

        monkeypatch.setattr(wc, "enviar_texto", fake_enviar_texto)

        notif_a2.notificar_fernanda_pagamento_combinado(
            "+5581988880000", "João Pereira", "Apto 305", 2300.0, "2026-07-17", self.CHARGES
        )

        assert len(chamadas) == 1
        telefone, texto = chamadas[0]
        assert telefone == "+5581988880000"
        assert "Aluguel: R$ 2200.00" in texto
        assert "[ Cobre os dois ]" in texto

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_texto_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("timeout")

        monkeypatch.setattr(wc, "enviar_texto", enviar_texto_com_falha)

        with pytest.raises(wc.WhatsAppTransientError):
            notif_a2.notificar_fernanda_pagamento_combinado(
                "+5581988880000", "João Pereira", "Apto 305", 2300.0, "2026-07-17", self.CHARGES
            )


class TestNotificarFernandaSemMatch:
    CHARGES = [{"tipo": "aluguel", "valor_esperado": 2200.0}]

    def test_modo_simulado_nao_faz_rede(self):
        notif_a2.notificar_fernanda_sem_match(
            "+5581988880000", "João Pereira", "Apto 305", 500.0, "2026-07-17", self.CHARGES
        )

    def test_sucesso_chama_enviar_texto_sem_botoes(self, monkeypatch):
        chamadas = []

        def fake_enviar_texto(telefone, texto):
            chamadas.append((telefone, texto))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.SEM1")

        monkeypatch.setattr(wc, "enviar_texto", fake_enviar_texto)

        notif_a2.notificar_fernanda_sem_match(
            "+5581988880000", "João Pereira", "Apto 305", 500.0, "2026-07-17", self.CHARGES
        )

        assert len(chamadas) == 1
        _, texto = chamadas[0]
        assert "não bate com nenhuma delas" in texto
        assert "[" not in texto  # sem botões, por design

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_texto_com_falha(*args, **kwargs):
            raise wc.WhatsAppConteudoInvalidoError("telefone inválido")

        monkeypatch.setattr(wc, "enviar_texto", enviar_texto_com_falha)

        with pytest.raises(wc.WhatsAppConteudoInvalidoError):
            notif_a2.notificar_fernanda_sem_match(
                "+5581988880000", "João Pereira", "Apto 305", 500.0, "2026-07-17", self.CHARGES
            )


class TestResponderConfirmacaoPagamento:
    def test_modo_simulado_nao_faz_rede(self):
        notif_a2.responder_confirmacao_pagamento("+5581999990000", "João Pereira")

    def test_sucesso_chama_enviar_texto_com_telefone_e_nome_corretos(self, monkeypatch):
        chamadas = []

        def fake_enviar_texto(telefone, texto):
            chamadas.append((telefone, texto))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.CONF1")

        monkeypatch.setattr(wc, "enviar_texto", fake_enviar_texto)

        notif_a2.responder_confirmacao_pagamento("+5581999990000", "João Pereira")

        assert chamadas == [
            ("+5581999990000", "Recebemos seu comprovante, João Pereira. Pagamento confirmado, obrigado!")
        ]

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_texto_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("Meta fora do ar")

        monkeypatch.setattr(wc, "enviar_texto", enviar_texto_com_falha)

        with pytest.raises(wc.WhatsAppTransientError):
            notif_a2.responder_confirmacao_pagamento("+5581999990000", "João Pereira")


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
