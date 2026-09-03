"""Testes da WA-04 — resposta do webhook ao inquilino.

Cobre app/orchestrator/processar_mensagem.py::processar_mensagem_recebida e o
parâmetro `responder_via_whatsapp`, que decide se a resposta calculada pelo
processamento também é enviada de volta pelo cliente WhatsApp real
(app/tools/whatsapp_client.py::enviar_texto).

Nenhum teste aqui acessa Supabase, Anthropic ou a Meta de verdade: toda
dependência externa (_resolver_contract_id, obter_client_agente,
rotear_mensagem, rotear_comprovante_a2, rotear_clique_botao_a2 e o despacho
da política de saída) é monkeypatchada no nível do módulo
app.orchestrator.processar_mensagem
(importada por nome direto ali, então sobrescrever o atributo do módulo é
suficiente para afetar as chamadas internas)."""

import base64
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.api.routers import dev_chat
from app.orchestrator import processar_mensagem as pm


class _FakeClientAgente:
    """Substitui o client do Supabase retornado por obter_client_agente.
    Só precisa suportar a cadeia client.rpc(nome, params).execute() usada
    por processar_mensagem.py para registrar mensagens no histórico."""

    def __init__(self):
        self.chamadas: list[tuple[str, dict]] = []
        self._ultimo_nome = ""

    def rpc(self, nome, params):
        self.chamadas.append((nome, params))
        self._ultimo_nome = nome
        return self

    def execute(self):
        if self._ultimo_nome == "agent_get_last_tenant_message_at":
            return MagicMock(data=datetime.now(timezone.utc).isoformat())
        return MagicMock()


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeClientAgente()
    monkeypatch.setattr(pm, "obter_client_agente", lambda contract_id: client)
    return client


def _payload_texto(telefone: str = "+5581999998888", texto: str = "Oi") -> dict:
    mensagem = {"id": "wamid.texto1", "from": telefone, "type": "text", "text": {"body": texto}}
    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


def _payload_midia(telefone: str = "+5581999998888", mime: str = "image/jpeg") -> dict:
    mensagem = {
        "id": "wamid.midia1",
        "from": telefone,
        "type": "image",
        "image": {"mime_type": mime, "_dados_base64": "ZmFrZQ=="},
    }
    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


def _payload_status() -> dict:
    status = {"id": "wamid.status1", "status": "delivered"}
    return {"entry": [{"changes": [{"value": {"statuses": [status]}}]}]}


def _payload_clique(button_id: str = "confirmar|contract-1|charge-1", telefone: str = "+5581900000000") -> dict:
    mensagem = {
        "id": "wamid.clique1",
        "from": telefone,
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": button_id}},
    }
    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


def _capturar_envios(monkeypatch) -> list[tuple[str, str]]:
    enviados: list[tuple[str, str]] = []

    def _fake_enviar_saida(telefone, saida):
        conteudo = saida.texto if saida.tipo == "texto" else saida.nome
        enviados.append((telefone, conteudo))

    monkeypatch.setattr(pm, "enviar_saida", _fake_enviar_saida)
    return enviados


# ======================================================================
# Texto
# ======================================================================


def test_mensagem_texto_real_envia_resposta_para_mesmo_from(monkeypatch, fake_client):
    telefone = "+5581999998888"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    monkeypatch.setattr(pm, "rotear_mensagem", lambda cid, texto: ("Resposta do agente", "a1"))
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_texto(telefone=telefone), responder_via_whatsapp=True)

    assert resposta == "Resposta do agente"
    assert enviados == [(telefone, "Resposta do agente")]


def test_mensagem_simulada_nao_chama_cliente_whatsapp(monkeypatch, fake_client):
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    monkeypatch.setattr(pm, "rotear_mensagem", lambda cid, texto: ("Resposta do agente", "a1"))
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_texto())  # responder_via_whatsapp padrão: False

    assert resposta == "Resposta do agente"
    assert enviados == []


def test_contrato_nao_encontrado_envia_mensagem_segura(monkeypatch):
    telefone = "+5581999990000"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: None)
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_texto(telefone=telefone), responder_via_whatsapp=True)

    assert resposta is not None
    assert "Nenhum contrato ativo encontrado" in resposta
    assert "contract-1" not in resposta  # não revela detalhes internos
    assert enviados == [(telefone, "retomada_atendimento")]


class _ClientFalhaNoLogDoAgente:
    """Fake client cujo agent_log_message SEMPRE falha quando o remetente é
    'agente' (independente de quantas vezes for chamado), pra simular uma
    falha persistente que sobrevive a todo o retry. Chamadas com remetente
    'inquilino' funcionam normalmente."""

    def __init__(self, falhar_sempre: bool):
        self.chamadas: list[dict] = []
        self._falhar_sempre = falhar_sempre
        self._tentativas_de_agente = 0
        self._ultimo_params: dict = {}
        self._ultimo_nome = ""

    def rpc(self, nome, params):
        self.chamadas.append(params)
        self._ultimo_params = params
        self._ultimo_nome = nome
        return self

    def execute(self):
        if self._ultimo_nome == "agent_get_last_tenant_message_at":
            return MagicMock(data=datetime.now(timezone.utc).isoformat())
        if self._ultimo_params.get("p_remetente") == "agente":
            self._tentativas_de_agente += 1
            if self._falhar_sempre or self._tentativas_de_agente == 1:
                raise RuntimeError("falha simulada ao registrar log")
        return MagicMock()


def test_falha_ao_registrar_resposta_do_agente_nao_descarta_resposta_valida(monkeypatch):
    """Regressão: mesmo esgotando todas as tentativas de retry, uma falha
    persistente ao registrar a resposta do agente NÃO pode descartar uma
    resposta já calculada com sucesso por rotear_mensagem."""
    telefone = "+5581999998888"
    client = _ClientFalhaNoLogDoAgente(falhar_sempre=True)
    monkeypatch.setattr(pm, "obter_client_agente", lambda contract_id: client)
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    monkeypatch.setattr(pm, "rotear_mensagem", lambda cid, texto: ("Resposta do agente", "a1"))
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_texto(telefone=telefone), responder_via_whatsapp=True)

    assert resposta == "Resposta do agente"  # não deve virar "Erro ao processar a mensagem"
    assert enviados == [(telefone, "Resposta do agente")]
    # esgotou as _LOG_RETRY_MAX_TENTATIVAS tentativas antes de desistir
    assert client._tentativas_de_agente == pm._LOG_RETRY_MAX_TENTATIVAS


def test_falha_transitoria_no_log_e_recuperada_pelo_retry(monkeypatch):
    """Uma falha passageira (rede/banco piscou uma vez só) não deve virar
    log incompleto: o retry recupera sozinho, sem intervenção manual."""
    telefone = "+5581999998888"
    client = _ClientFalhaNoLogDoAgente(falhar_sempre=False)  # só falha na 1ª tentativa
    monkeypatch.setattr(pm, "obter_client_agente", lambda contract_id: client)
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    monkeypatch.setattr(pm, "rotear_mensagem", lambda cid, texto: ("Resposta do agente", "a1"))
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_texto(telefone=telefone), responder_via_whatsapp=True)

    assert resposta == "Resposta do agente"
    assert enviados == [(telefone, "Resposta do agente")]
    assert client._tentativas_de_agente == 2  # falhou 1x, teve sucesso na 2ª tentativa


def test_falha_do_cliente_whatsapp_nao_apaga_logs_nem_efeitos(monkeypatch, fake_client):
    telefone = "+5581999998888"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    monkeypatch.setattr(pm, "rotear_mensagem", lambda cid, texto: ("Resposta do agente", "a1"))

    def _falha_transporte(tel, msg):
        raise RuntimeError("falha de transporte simulada")

    monkeypatch.setattr(pm, "enviar_saida", _falha_transporte)

    resposta = pm.processar_mensagem_recebida(_payload_texto(telefone=telefone), responder_via_whatsapp=True)

    # A falha de envio não deve subir nem apagar o que o agente já fez.
    assert resposta == "Resposta do agente"
    nomes_chamados = [nome for nome, _ in fake_client.chamadas]
    assert nomes_chamados == [
        "agent_log_message",
        "agent_log_message",
        "agent_get_last_tenant_message_at",
    ]


# ======================================================================
# Mídia (comprovante)
# ======================================================================


def test_midia_real_envia_resposta_para_mesmo_from(monkeypatch, fake_client):
    telefone = "+5581999998888"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    monkeypatch.setattr(
        pm, "rotear_comprovante_a2", lambda cid, b64, mime: ("Comprovante recebido, obrigado.", "a2")
    )
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_midia(telefone=telefone), responder_via_whatsapp=True)

    assert resposta == "Comprovante recebido, obrigado."
    assert enviados == [(telefone, resposta)]


def _payload_midia_real(
    telefone: str = "+5581999998888", media_id: str = "wamid-media-1", mime: str = "image/jpeg"
) -> dict:
    """Payload real da Meta — sem _dados_base64 (isso só existe no payload
    simulado do dev_chat), só o media_id que exige baixar_midia de verdade
    (ver app/tools/whatsapp_client.py, WA-03)."""
    mensagem = {
        "id": "wamid.midia2",
        "from": telefone,
        "type": "image",
        "image": {"mime_type": mime, "id": media_id},
    }
    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


class _ResultadoMidiaFake:
    def __init__(self, conteudo: bytes, mime_type: str):
        self.conteudo = conteudo
        self.mime_type = mime_type


def test_midia_real_sem_dados_base64_baixa_via_whatsapp_client_e_usa_mime_do_client(
    monkeypatch, fake_client
):
    """Checkup do Daniel, Ponto 1: payload real (sem _dados_base64) precisa
    chamar whatsapp_client.baixar_midia de verdade, converter os bytes pra
    base64 corretamente, e usar o mime_type DEVOLVIDO PELO CLIENTE (que pode
    divergir do mime_type do payload inicial do webhook) — não o do payload
    inicial."""
    telefone = "+5581999998888"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")

    chamadas_baixar = []

    def _fake_baixar_midia(media_id):
        chamadas_baixar.append(media_id)
        return _ResultadoMidiaFake(b"conteudo-real-do-comprovante", "application/pdf")

    monkeypatch.setattr(pm, "baixar_midia", _fake_baixar_midia)

    chamadas_rotear = []

    def _fake_rotear(cid, b64, mime):
        chamadas_rotear.append((cid, b64, mime))
        return ("Comprovante recebido, obrigado.", "a2")

    monkeypatch.setattr(pm, "rotear_comprovante_a2", _fake_rotear)
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(
        _payload_midia_real(telefone=telefone, media_id="wamid-media-1", mime="image/jpeg"),
        responder_via_whatsapp=True,
    )

    assert resposta == "Comprovante recebido, obrigado."
    assert chamadas_baixar == ["wamid-media-1"]
    assert chamadas_rotear == [
        (
            "contract-1",
            base64.b64encode(b"conteudo-real-do-comprovante").decode("ascii"),
            "application/pdf",  # mime do CLIENTE, não "image/jpeg" do payload inicial
        )
    ]
    assert enviados == [(telefone, resposta)]


def test_midia_real_falha_no_download_produz_fallback_controlado(monkeypatch, fake_client):
    """Erro de download (rede, host recusado, MIME inválido, etc.) nunca
    deve propagar pro webhook nem chegar a chamar o A2 — cai no fallback já
    existente, pedindo análise manual."""
    telefone = "+5581999998888"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")

    def _fake_baixar_midia_com_falha(media_id):
        raise RuntimeError("Meta fora do ar")

    monkeypatch.setattr(pm, "baixar_midia", _fake_baixar_midia_com_falha)

    chamadas_rotear = []
    monkeypatch.setattr(
        pm, "rotear_comprovante_a2", lambda cid, b64, mime: chamadas_rotear.append((cid, b64, mime))
    )
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(
        _payload_midia_real(telefone=telefone), responder_via_whatsapp=True
    )

    assert "não conseguimos baixá-lo" in resposta
    assert chamadas_rotear == []  # nunca chegou a chamar o A2
    # client_agente ainda não foi obtido nesse ramo de falha precoce (mesmo
    # padrão de test_contrato_nao_encontrado_envia_mensagem_segura) — a
    # política de saída, sem cliente pra checar a janela de 24h, cai no
    # template seguro em vez do texto livre.
    assert enviados == [(telefone, "retomada_atendimento")]


def test_midia_simulada_com_dados_base64_nao_chama_baixar_midia(monkeypatch, fake_client):
    """Regressão: o caminho simulado (_dados_base64, usado pelo dev_chat)
    continua funcionando sem passar pelo download real."""
    telefone = "+5581999998888"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")

    chamadas_baixar = []
    monkeypatch.setattr(pm, "baixar_midia", lambda media_id: chamadas_baixar.append(media_id))
    monkeypatch.setattr(
        pm, "rotear_comprovante_a2", lambda cid, b64, mime: ("Comprovante recebido, obrigado.", "a2")
    )
    _capturar_envios(monkeypatch)

    pm.processar_mensagem_recebida(_payload_midia(telefone=telefone), responder_via_whatsapp=True)

    assert chamadas_baixar == []


# ======================================================================
# Áudio — nunca vira texto vazio, nunca passa por classificação
# ======================================================================


def _payload_audio(telefone: str = "+5581999998888", media_id: str = "wamid-audio-1") -> dict:
    mensagem = {
        "id": "wamid.audio1",
        "from": telefone,
        "type": "audio",
        "audio": {"mime_type": "audio/ogg; codecs=opus", "id": media_id},
    }
    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


def test_audio_nunca_chama_roteamento_de_texto(monkeypatch, fake_client):
    """Regressão do bug relatado: antes desta correção, um áudio virava
    texto="" e caía no roteamento normal (classificar_intencao/rotear_mensagem),
    quase sempre terminando na mensagem genérica do A5."""
    telefone = "+5581999998888"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")

    chamou_rotear = []
    monkeypatch.setattr(pm, "rotear_mensagem", lambda cid, texto: chamou_rotear.append((cid, texto)) or ("x", "A1"))
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_audio(telefone=telefone), responder_via_whatsapp=True)

    assert chamou_rotear == []  # nunca passou pelo roteamento normal
    assert resposta is not None
    assert "áudio" in resposta.lower() or "audio" in resposta.lower()
    assert "texto" in resposta.lower()  # deixa claro que precisa mandar em texto
    assert enviados == [(telefone, resposta)]


def test_audio_sem_contrato_encontrado_usa_fallback_seguro(monkeypatch):
    telefone = "+5581999990000"
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: None)
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_audio(telefone=telefone), responder_via_whatsapp=True)

    assert resposta is not None
    assert "Nenhum contrato ativo encontrado" in resposta
    assert enviados == [(telefone, "retomada_atendimento")]


def test_audio_simulado_nao_chama_whatsapp(monkeypatch, fake_client):
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_audio())  # responder_via_whatsapp padrão: False

    assert resposta is not None
    assert enviados == []


# ======================================================================
# Evento de status (sem "messages")
# ======================================================================


def test_evento_de_status_nao_envia_nada(monkeypatch):
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_status(), responder_via_whatsapp=True)

    assert resposta is None
    assert enviados == []


# ======================================================================
# Clique interativo (Fernanda) — nunca recebe resposta automática
# ======================================================================


def test_clique_interativo_nao_envia_resposta_automatica(monkeypatch):
    chamadas_roteamento = []

    def fake_rotear(button_id, telefone_remetente):
        chamadas_roteamento.append((button_id, telefone_remetente))
        return "Confirmado, obrigado."

    monkeypatch.setattr(pm, "rotear_clique_botao_a2", fake_rotear)
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_clique(), responder_via_whatsapp=True)

    assert resposta == "Confirmado, obrigado."
    assert enviados == []  # telefone do clique é o da Fernanda, não do inquilino
    # O telefone de quem clicou é repassado adiante (WA-06), mesmo que a
    # maioria das ações não precise dele.
    assert chamadas_roteamento == [("confirmar|contract-1|charge-1", "+5581900000000")]


# ======================================================================
# Regressão do dev_chat (chat simulado)
# ======================================================================


def test_dev_chat_regressao_nao_chama_whatsapp(monkeypatch, fake_client):
    monkeypatch.setattr(pm, "_resolver_contract_id", lambda tel: "contract-1")
    monkeypatch.setattr(pm, "rotear_mensagem", lambda cid, texto: ("Resposta simulada", "a1"))
    enviados = _capturar_envios(monkeypatch)

    msg = dev_chat.MensagemSimulada(telefone="+5581999998888", texto="Oi")
    resultado = dev_chat.enviar_mensagem_simulada(msg)

    assert resultado == {"resposta": "Resposta simulada"}
    assert enviados == []
