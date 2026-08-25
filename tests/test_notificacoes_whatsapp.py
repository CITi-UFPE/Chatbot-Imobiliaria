"""Testes do transporte WhatsApp do A2 (cobrança/comprovante) e do A5
(escalonamento) — WA-05/WA-06. Cobre todas as funções públicas de
app/agents/a2_cobranca/notificacao.py e app/agents/a5_escalonamento/
notificacao.py em modo simulado (kill switch desligado), sucesso (cliente
mockado) e falha (cliente mockado levantando). Nenhum destes testes acessa
a Meta de verdade: em modo simulado, whatsapp_client.enviar_texto/
enviar_template/enviar_botoes já retornam sem chamada HTTP sozinhos; nos
demais casos, essas funções são substituídas por um fake via monkeypatch,
igual ao padrão de tests/test_a4_whatsapp_notification.py.

WA-06: notificar_fernanda_comprovante e notificar_fernanda_pagamento_combinado
passaram a enviar botões nativos via whatsapp_client.enviar_botoes (não mais
enviar_texto com rótulos entre colchetes) — os testes dessas duas classes
foram atualizados de acordo. O round-trip completo id-montado ->
decodificar_button_id, e o payload de "Cobre os dois" sem "Só uma delas",
ficam em tests/test_a2_whatsapp_buttons.py.
"""

import pytest

from app.agents.a2_cobranca import button_ids
from app.agents.a2_cobranca import notificacao as notif_a2
from app.agents.a5_escalonamento import notificacao as notif_a5
from app.tools import whatsapp_client as wc


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
        notif_a2.enviar_mensagem_cobranca("+5581999990000", "Lembrete de pagamento.")

    def test_sucesso_chama_enviar_template_com_texto_como_parametro(self, monkeypatch):
        chamadas = []

        def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
            chamadas.append((telefone, nome, parametros))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.COB1")

        monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

        notif_a2.enviar_mensagem_cobranca("+5581999990000", "Lembrete de pagamento.")

        assert chamadas == [
            ("+5581999990000", notif_a2._TEMPLATE_COBRANCA_MENSAGEM, ["Lembrete de pagamento."])
        ]

    def test_falha_do_cliente_propaga_e_loga_telefone_mascarado(self, monkeypatch, caplog):
        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("Meta fora do ar")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        telefone = "+5581999990000"
        with caplog.at_level("ERROR"):
            with pytest.raises(wc.WhatsAppTransientError):
                notif_a2.enviar_mensagem_cobranca(telefone, "Lembrete de pagamento.")

        assert telefone not in caplog.text
        assert wc.mascarar_telefone(telefone) in caplog.text


# ======================================================================
# A2 — notificações à Fernanda e resposta ao inquilino — reativo, texto livre
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

    def test_sucesso_chama_enviar_botoes_com_conteudo_e_ids_corretos(self, monkeypatch):
        chamadas = []

        def fake_enviar_botoes(telefone, corpo, botoes):
            chamadas.append((telefone, corpo, botoes))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.FER1")

        monkeypatch.setattr(wc, "enviar_botoes", fake_enviar_botoes)

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
        telefone, corpo, botoes = chamadas[0]
        assert telefone == "+5581988880000"
        assert "João Pereira" in corpo
        assert "Apto 305" in corpo
        assert "Identificado automaticamente como aluguel." in corpo

        assert [b["titulo"] for b in botoes] == ["Confirmar", "Valor diverge"]
        confirmar = button_ids.decodificar_button_id(botoes[0]["id"])
        assert confirmar.acao == button_ids.ACAO_CONFIRMAR
        assert confirmar.contract_id == self.CONTRACT_ID
        assert confirmar.charge_ids == [self.CHARGE_ID]
        divergente = button_ids.decodificar_button_id(botoes[1]["id"])
        assert divergente.acao == button_ids.ACAO_DIVERGENTE
        assert divergente.contract_id == self.CONTRACT_ID
        assert divergente.charge_ids == [self.CHARGE_ID]

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_botoes_com_falha(*args, **kwargs):
            raise wc.WhatsAppPermanentError("número inválido")

        monkeypatch.setattr(wc, "enviar_botoes", enviar_botoes_com_falha)

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

    def test_sucesso_chama_enviar_botoes_com_conteudo_e_ids_corretos(self, monkeypatch):
        chamadas = []

        def fake_enviar_botoes(telefone, corpo, botoes):
            chamadas.append((telefone, corpo, botoes))
            return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.COMB1")

        monkeypatch.setattr(wc, "enviar_botoes", fake_enviar_botoes)

        notif_a2.notificar_fernanda_pagamento_combinado(
            "+5581988880000", self.CONTRACT_ID, "João Pereira", "Apto 305", 2300.0, "2026-07-17", self.CHARGES
        )

        assert len(chamadas) == 1
        telefone, corpo, botoes = chamadas[0]
        assert telefone == "+5581988880000"
        assert "Aluguel: R$ 2200.00" in corpo
        assert "resolver manualmente" in corpo

        # 2 botões: "Cobre os dois" e "Só uma delas" (fluxo de 2 etapas da
        # WA-06 — ver notificacao.py e tests/test_a2_whatsapp_buttons.py
        # pro round-trip completo). Sem "Valor diverge" nesta mensagem.
        assert [b["titulo"] for b in botoes] == ["Cobre os dois", "Só uma delas"]
        decod_todos = button_ids.decodificar_button_id(botoes[0]["id"])
        assert decod_todos.acao == button_ids.ACAO_COMBINADO_TODOS
        assert decod_todos.contract_id == self.CONTRACT_ID
        assert decod_todos.charge_ids == ["charge-aluguel", "charge-agua"]

        decod_escolher = button_ids.decodificar_button_id(botoes[1]["id"])
        assert decod_escolher.acao == button_ids.ACAO_ESCOLHER_PARCIAL
        assert decod_escolher.contract_id == self.CONTRACT_ID
        assert decod_escolher.charge_ids == ["charge-aluguel", "charge-agua"]

    def test_falha_do_cliente_propaga(self, monkeypatch):
        def enviar_botoes_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("timeout")

        monkeypatch.setattr(wc, "enviar_botoes", enviar_botoes_com_falha)

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
