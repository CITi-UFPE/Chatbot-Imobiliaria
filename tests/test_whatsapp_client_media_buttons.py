"""Testes de enviar_botoes e baixar_midia (WA-03). Toda chamada HTTP é
interceptada via httpx.MockTransport — nenhum destes testes acessa a Meta
de verdade."""

import json

import httpx
import pytest

from app.agents.a2_cobranca.button_ids import decodificar_button_id, montar_button_id_confirmar
from app.tools import whatsapp_client as wc


def _client_mockado(handler):
    def _fabrica() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=wc.TIMEOUT_PADRAO_SEGUNDOS)

    return _fabrica


@pytest.fixture(autouse=True)
def _credenciais_ativas(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-fake-de-teste")
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v21.0")
    monkeypatch.delenv("WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB", raising=False)


def _ler_json(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ======================================================================
# enviar_botoes — validação (antes de qualquer HTTP, mesmo simulado)
# ======================================================================


def test_zero_botoes_falha_antes_do_http(monkeypatch):
    chamadas = {"n": 0}

    def handler(request):
        chamadas["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_botoes("5581999998888", "Confirma?", [])
    assert chamadas["n"] == 0


def test_mais_de_3_botoes_falha():
    botoes = [{"id": f"id{i}", "titulo": f"Op {i}"} for i in range(4)]
    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_botoes("5581999998888", "Escolha", botoes)


def test_titulo_vazio_falha():
    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_botoes("5581999998888", "Confirma?", [{"id": "a", "titulo": ""}])


def test_titulo_acima_de_20_caracteres_falha():
    titulo = "x" * 21
    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_botoes("5581999998888", "Confirma?", [{"id": "a", "titulo": titulo}])


def test_titulo_com_20_caracteres_e_valido(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"messages": [{"id": "wamid.B"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))
    titulo = "x" * 20

    resultado = wc.enviar_botoes("5581999998888", "Confirma?", [{"id": "a", "titulo": titulo}])
    assert resultado.sucesso is True


def test_id_vazio_falha():
    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_botoes("5581999998888", "Confirma?", [{"id": "", "titulo": "Confirmar"}])


def test_id_acima_de_256_caracteres_falha():
    id_longo = "a" * 257
    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_botoes("5581999998888", "Confirma?", [{"id": id_longo, "titulo": "Confirmar"}])


def test_validacao_falha_mesmo_com_kill_switch_desligado(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")
    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.enviar_botoes("5581999998888", "Confirma?", [])


# ======================================================================
# enviar_botoes — payload e simulação
# ======================================================================


def test_payload_interativo_no_formato_esperado(monkeypatch):
    capturado = {}

    def handler(request):
        capturado["json"] = _ler_json(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.BTN"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    botoes = [
        {"id": "a2:confirmar:c1:ch1", "titulo": "Confirmar"},
        {"id": "a2:divergente:c1:ch1", "titulo": "Valor diverge"},
    ]
    resultado = wc.enviar_botoes("5581999998888", "Recebemos seu comprovante", botoes)

    assert resultado.message_id == "wamid.BTN"
    interactive = capturado["json"]["interactive"]
    assert interactive["type"] == "button"
    assert interactive["body"]["text"] == "Recebemos seu comprovante"
    assert interactive["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "a2:confirmar:c1:ch1", "title": "Confirmar"}},
        {"type": "reply", "reply": {"id": "a2:divergente:c1:ch1", "title": "Valor diverge"}},
    ]


def test_enviar_botoes_simulado_nao_chama_http(monkeypatch):
    chamadas = {"n": 0}

    def handler(request):
        chamadas["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")
    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.enviar_botoes(
        "5581999998888", "Confirma?", [{"id": "a", "titulo": "Confirmar"}]
    )

    assert resultado.simulado is True
    assert chamadas["n"] == 0


def test_id_montado_por_button_ids_e_aceito_por_enviar_botoes_e_decodificavel(monkeypatch):
    """Round-trip leve: o ID que button_ids.py monta passa pela validação
    de enviar_botoes sem erro, e decodificar_button_id reconhece de volta o
    mesmo ID depois — round-trip completo (envio -> clique) é formalizado
    na WA-06, aqui só confirmamos que os dois lados já são compatíveis."""

    def handler(request):
        return httpx.Response(200, json={"messages": [{"id": "wamid.RT"}]})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    button_id = montar_button_id_confirmar("contrato-123", "charge-456")
    resultado = wc.enviar_botoes(
        "5581999998888", "Confirma?", [{"id": button_id, "titulo": "Confirmar"}]
    )

    assert resultado.sucesso is True
    decodificado = decodificar_button_id(button_id)
    assert decodificado is not None
    assert decodificado.acao == "confirmar"
    assert decodificado.contract_id == "contrato-123"


# ======================================================================
# baixar_midia — download em duas etapas, sucesso
# ======================================================================


def test_baixar_midia_sucesso_duas_etapas(monkeypatch):
    chamadas = {"metadados": 0, "arquivo": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/media-id-123"):
            chamadas["metadados"] += 1
            return httpx.Response(
                200,
                json={
                    "url": "https://mock-cdn.example.com/arquivo-real",
                    "mime_type": "image/jpeg",
                    "file_size": 4,
                },
            )
        chamadas["arquivo"] += 1
        return httpx.Response(200, content=b"1234")

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.baixar_midia("media-id-123")

    assert resultado.conteudo == b"1234"
    assert resultado.mime_type == "image/jpeg"
    assert chamadas["metadados"] == 1
    assert chamadas["arquivo"] == 1


def test_baixar_midia_nao_e_afetado_pelo_kill_switch(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")

    def handler(request: httpx.Request) -> httpx.Response:
        if "media-id" in str(request.url):
            return httpx.Response(
                200, json={"url": "https://mock-cdn.example.com/f", "mime_type": "application/pdf"}
            )
        return httpx.Response(200, content=b"%PDF-1.4")

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    resultado = wc.baixar_midia("media-id-abc")
    assert resultado.conteudo == b"%PDF-1.4"


# ======================================================================
# baixar_midia — MIME inválido
# ======================================================================


def test_baixar_midia_mime_nao_permitido_falha_antes_do_download(monkeypatch):
    chamadas = {"arquivo": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "media-id" in str(request.url):
            return httpx.Response(
                200, json={"url": "https://mock-cdn.example.com/f", "mime_type": "application/zip"}
            )
        chamadas["arquivo"] += 1
        return httpx.Response(200, content=b"PK...")

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppConteudoInvalidoError, match="MIME"):
        wc.baixar_midia("media-id-zip")
    assert chamadas["arquivo"] == 0


# ======================================================================
# baixar_midia — arquivo grande demais
# ======================================================================


def test_baixar_midia_tamanho_informado_nos_metadados_acima_do_limite(monkeypatch):
    monkeypatch.setenv("WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB", "0.000001")  # ~1 byte
    chamadas = {"arquivo": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "media-id" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "url": "https://mock-cdn.example.com/f",
                    "mime_type": "image/png",
                    "file_size": 999999,
                },
            )
        chamadas["arquivo"] += 1
        return httpx.Response(200, content=b"x" * 999999)

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.baixar_midia("media-id-grande")
    assert chamadas["arquivo"] == 0  # rejeitado pelos metadados, nem chega a baixar


def test_baixar_midia_estoura_limite_durante_o_download_sem_file_size_confiavel(monkeypatch):
    monkeypatch.setenv("WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB", "0.000001")  # ~1 byte

    def handler(request: httpx.Request) -> httpx.Response:
        if "media-id" in str(request.url):
            # Sem file_size nos metadados — só o corte durante o streaming
            # protege aqui.
            return httpx.Response(200, json={"url": "https://mock-cdn.example.com/f", "mime_type": "image/png"})
        return httpx.Response(200, content=b"x" * 5000)

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.baixar_midia("media-id-sem-tamanho")


# ======================================================================
# baixar_midia — erro HTTP e resposta malformada
# ======================================================================


def test_baixar_midia_metadados_404_vira_permanente(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": 100, "message": "media não encontrada"}})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppPermanentError):
        wc.baixar_midia("media-id-inexistente")


def test_baixar_midia_metadados_corpo_nao_json_falha(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="isso não é json")

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppError):
        wc.baixar_midia("media-id-malformado")


def test_baixar_midia_metadados_sem_url_falha(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"mime_type": "image/png"})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppError, match="URL"):
        wc.baixar_midia("media-id-sem-url")


def test_baixar_midia_url_nao_https_e_recusada(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"url": "http://inseguro.example.com/f", "mime_type": "image/png"}
        )

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppError, match="https"):
        wc.baixar_midia("media-id-http")


def test_baixar_midia_media_id_vazio_falha_sem_http(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(200, json={})

    monkeypatch.setattr(wc, "_construir_client", _client_mockado(handler))

    with pytest.raises(wc.WhatsAppConteudoInvalidoError):
        wc.baixar_midia("")
    assert chamadas["n"] == 0
