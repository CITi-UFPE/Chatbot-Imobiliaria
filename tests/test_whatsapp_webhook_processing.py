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
    monkeypatch.setattr(pm, "rotear_clique_botao_a2", lambda button_id: "Confirmado, obrigado.")
    enviados = _capturar_envios(monkeypatch)

    resposta = pm.processar_mensagem_recebida(_payload_clique(), responder_via_whatsapp=True)

    assert resposta == "Confirmado, obrigado."
    assert enviados == []  # telefone do clique é o da Fernanda, não do inquilino


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
