"""Testes do transporte real de enviar_texto/enviar_template (WA-02).

Toda chamada HTTP é interceptada via httpx.MockTransport — nenhum destes
testes acessa a Meta de verdade (regra comum da sprint). O transport é
injetado monkeypatchando whatsapp_client._construir_client, que é a única
fábrica de client httpx do módulo (ver docstring dela em WA-01/02)."""

import httpx
import pytest

from app.tools import whatsapp_client as wc


def _client_mockado(handler):
    """Substitui _construir_client por uma versão que devolve um
    httpx.Client com MockTransport(handler) — mesmo timeout do cliente
    real, só troca o transport."""

    def _fabrica() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=wc.TIMEOUT_PADRAO_SEGUNDOS)

    return _fabrica


@pytest.fixture(autouse=True)
def _credenciais_ativas(monkeypatch):
    """Toda a suíte deste arquivo testa o caminho de envio REAL — liga o
    kill switch e configura credenciais fake por padrão. Testes que
    precisam de outro estado sobrescrevem localmente."""
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-fake-de-teste")
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v21.0")


# ======================================================================
# Sucesso e payload — enviar_texto
# ======================================================================


def test_enviar_texto_sucesso_retorna_message_id(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.ABC123"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.enviar_texto("+55 81 99999-8888", "Olá, tudo bem?")

    assert resultado.sucesso is True
    assert resultado.simulado is False
    assert resultado.message_id == "wamid.ABC123"


def test_enviar_texto_payload_no_formato_esperado(monkeypatch):
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        capturado["json"] = _ler_json(request)
        capturado["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    wc.enviar_texto("+55 (81) 99999-8888", "Oi")

    assert capturado["json"] == {
        "messaging_product": "whatsapp",
        "to": "5581999998888",
        "type": "text",
        "text": {"body": "Oi"},
    }
    assert capturado["url"] == "https://graph.facebook.com/v21.0/1234567890/messages"
    assert capturado["auth"] == "Bearer token-fake-de-teste"


def _ler_json(request: httpx.Request) -> dict:
    import json

    return json.loads(request.content)


# ======================================================================
# Sucesso e payload — enviar_template
# ======================================================================


def test_enviar_template_payload_com_parametros_ordenados(monkeypatch):
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["json"] = _ler_json(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.T1"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.enviar_template(
        "5581999998888", "aviso_vencimento", ["João", "R$ 1.000,00", "10/09/2026"]
    )

    assert resultado.message_id == "wamid.T1"
    assert capturado["json"]["type"] == "template"
    assert capturado["json"]["template"]["name"] == "aviso_vencimento"
    assert capturado["json"]["template"]["language"] == {"code": "pt_BR"}
    parametros_enviados = capturado["json"]["template"]["components"][0]["parameters"]
    assert parametros_enviados == [
        {"type": "text", "text": "João"},
        {"type": "text", "text": "R$ 1.000,00"},
        {"type": "text", "text": "10/09/2026"},
    ]


def test_enviar_template_remove_quebra_de_linha_e_tab_dos_parametros(monkeypatch):
    """A Graph API rejeita (HTTP 400) parametro de template com \n ou \t --
    mensagens montadas para leitura humana com \n\n (ex:
    montar_alerta_renovacao/montar_calculo_reajuste, WA-09) precisam chegar
    aqui como texto corrido."""
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["json"] = _ler_json(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.T2"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    wc.enviar_template(
        "5581999998888",
        "alerta_contratual",
        ["Reajuste de aluguel", "Primeira linha.\n\nSegunda linha.\tcom tab."],
    )

    parametros_enviados = capturado["json"]["template"]["components"][0]["parameters"]
    assert parametros_enviados == [
        {"type": "text", "text": "Reajuste de aluguel"},
        {"type": "text", "text": "Primeira linha. Segunda linha. com tab."},
    ]


def test_enviar_template_sem_parametros_omite_components(monkeypatch):
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["json"] = _ler_json(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.T2"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    wc.enviar_template("5581999998888", "escalonamento_equipe", [])

    assert "components" not in capturado["json"]["template"]


def test_enviar_template_lang_customizado(monkeypatch):
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["json"] = _ler_json(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.T3"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    wc.enviar_template("5581999998888", "teste", ["x"], lang="en_US")

    assert capturado["json"]["template"]["language"] == {"code": "en_US"}


def test_enviar_template_com_quick_replies_mantem_ordem_e_payloads(monkeypatch):
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["json"] = _ler_json(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.T4"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    wc.enviar_template(
        "5581999998888",
        "comprovante_para_conferencia",
        ["João", "Apto 305"],
        botoes=["confirmar|contract-1|charge-1", "divergente|contract-1|charge-1"],
    )

    componentes = capturado["json"]["template"]["components"]
    assert componentes == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "João"},
                {"type": "text", "text": "Apto 305"},
            ],
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [
                {"type": "payload", "payload": "confirmar|contract-1|charge-1"}
            ],
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "1",
            "parameters": [
                {"type": "payload", "payload": "divergente|contract-1|charge-1"}
            ],
        },
    ]


@pytest.mark.parametrize(
    "botoes",
    [[""], ["1", "2", "3", "4"], ["x" * 257]],
)
def test_enviar_template_rejeita_payloads_de_botao_invalidos_antes_da_rede(
    monkeypatch, botoes
):
    chamadas = []
    monkeypatch.setattr(
        wc,
        "_construir_client",
        lambda: chamadas.append(True),
    )

    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_template("5581999998888", "teste", [], botoes=botoes)

    assert chamadas == []


# ======================================================================
# HTTP 400 — permanente, sem retry
# ======================================================================


def test_erro_400_vira_permanente_sem_retry(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(
            400, json={"error": {"code": 131009, "message": "Parâmetro inválido"}}
        )

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppPermanentError, match="131009"):
        wc.enviar_texto("5581999998888", "Oi")

    assert chamadas["n"] == 1


# ======================================================================
# HTTP 429 — transitório, com retry limitado
# ======================================================================


def test_erro_429_persistente_repete_ate_o_limite_e_falha(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(429, json={"error": {"code": 4, "message": "Rate limit"}})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppTransientError):
        wc.enviar_texto("5581999998888", "Oi")

    assert chamadas["n"] == wc._RETRY_MAX_TENTATIVAS


def test_erro_429_seguido_de_sucesso_eventualmente_retorna(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        if chamadas["n"] < 2:
            return httpx.Response(429, json={"error": {"code": 4, "message": "Rate limit"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.RETRY_OK"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.enviar_texto("5581999998888", "Oi")

    assert resultado.message_id == "wamid.RETRY_OK"
    assert chamadas["n"] == 2


# ======================================================================
# HTTP 500 — transitório, com retry limitado
# ======================================================================


def test_erro_500_persistente_repete_ate_o_limite_e_falha(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(500, json={"error": {"code": 1, "message": "Internal error"}})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppTransientError):
        wc.enviar_template("5581999998888", "aviso_atraso", ["x"])

    assert chamadas["n"] == wc._RETRY_MAX_TENTATIVAS


# ======================================================================
# Timeout / falha de conexão — transitório, com retry
# ======================================================================


def test_timeout_vira_transiente_e_e_retentado(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        raise httpx.ConnectTimeout("timeout simulado", request=request)

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppTransientError):
        wc.enviar_texto("5581999998888", "Oi")

    assert chamadas["n"] == wc._RETRY_MAX_TENTATIVAS


def test_falha_de_conexao_vira_transiente(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada simulada", request=request)

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppTransientError):
        wc.enviar_texto("5581999998888", "Oi")


# ======================================================================
# Resposta sem message_id
# ======================================================================


def test_resposta_sem_message_id_levanta_erro(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messaging_product": "whatsapp", "contacts": []})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppError, match="message_id"):
        wc.enviar_texto("5581999998888", "Oi")


def test_resposta_200_corpo_nao_json_levanta_erro(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="não é json")

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppError):
        wc.enviar_texto("5581999998888", "Oi")


# ======================================================================
# Simulação — kill switch desligado nunca chama o handler
# ======================================================================


def test_enviar_texto_simulado_nao_chama_handler(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "não deveria chegar aqui"}]})

    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")
    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.enviar_texto("5581999998888", "Oi")

    assert resultado.simulado is True
    assert chamadas["n"] == 0


def test_enviar_template_simulado_nao_chama_handler(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")
    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.enviar_template("5581999998888", "aviso_vencimento", ["x"])

    assert resultado.simulado is True
    assert chamadas["n"] == 0


# ======================================================================
# Normalização mínima do destino
# ======================================================================


def test_normalizar_destino_remove_formatacao():
    assert wc._normalizar_destino("+55 (81) 99999-8888") == "5581999998888"


def test_normalizar_destino_telefone_vazio_levanta_conteudo_invalido():
    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc._normalizar_destino("   ")
