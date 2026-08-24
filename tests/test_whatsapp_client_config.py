"""Testes da fundação do cliente WhatsApp (WA-01) — config, kill switch e
modo simulado. Nenhum destes testes faz chamada de rede real; os fluxos
HTTP completos (texto/template/botões/mídia) chegam em WA-02/WA-03 e terão
suíte própria."""

import pytest

from app.tools import whatsapp_client as wc


# ======================================================================
# Kill switch — padrão inativo, parsing booleano
# ======================================================================


def test_envio_ativo_padrao_e_false_sem_variavel_configurada(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ENVIO_ATIVO", raising=False)
    assert wc.envio_ativo() is False


@pytest.mark.parametrize("valor", ["true", "True", "TRUE", "1", "yes", "on", "t", "y"])
def test_envio_ativo_reconhece_valores_verdadeiros(monkeypatch, valor):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", valor)
    assert wc.envio_ativo() is True


@pytest.mark.parametrize("valor", ["false", "False", "FALSE", "0", "no", "off", "f", "n", ""])
def test_envio_ativo_reconhece_valores_falsos(monkeypatch, valor):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", valor)
    assert wc.envio_ativo() is False


@pytest.mark.parametrize("valor", ["ativo", "sim", "verdadeiro", "  ", "2"])
def test_envio_ativo_valor_invalido_cai_no_padrao_false(monkeypatch, valor):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", valor)
    assert wc.envio_ativo() is False


def test_importar_modulo_sem_variaveis_configuradas_nao_gera_erro(monkeypatch):
    # Critério de aceite explícito: importar/usar o módulo sem nenhuma
    # variável de ambiente setada não deve lançar nada.
    for var in (
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_ENVIO_ATIVO",
        "WHATSAPP_GRAPH_API_VERSION",
    ):
        monkeypatch.delenv(var, raising=False)

    assert wc.envio_ativo() is False


# ======================================================================
# Modo simulado — envio inativo nunca tenta rede
# ======================================================================


def test_enviar_texto_simulado_nao_faz_rede_mesmo_sem_credenciais(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)

    resultado = wc.enviar_texto("+5581999999999", "Olá")

    assert resultado.sucesso is True
    assert resultado.simulado is True
    assert resultado.message_id is None


def test_enviar_template_simulado_nao_faz_rede(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")

    resultado = wc.enviar_template("+5581999999999", "aviso_vencimento", ["João", "R$ 1.000,00"])

    assert resultado.sucesso is True
    assert resultado.simulado is True


def test_enviar_botoes_simulado_nao_faz_rede(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")

    resultado = wc.enviar_botoes(
        "+5581999999999",
        "Confirma o pagamento?",
        [{"id": "a2:confirmar:x", "titulo": "Confirmar"}],
    )

    assert resultado.sucesso is True
    assert resultado.simulado is True


# ======================================================================
# Envio ativo sem credenciais — erro claro, sem vazar segredo
# ======================================================================


def test_enviar_texto_ativo_sem_phone_number_id_informa_o_que_falta(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-secreto-de-teste")

    with pytest.raises(wc.WhatsAppConfigError) as exc_info:
        wc.enviar_texto("+5581999999999", "Olá")

    mensagem = str(exc_info.value)
    assert "WHATSAPP_PHONE_NUMBER_ID" in mensagem
    assert "token-secreto-de-teste" not in mensagem


def test_enviar_texto_ativo_sem_access_token_informa_o_que_falta(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456")
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)

    with pytest.raises(wc.WhatsAppConfigError) as exc_info:
        wc.enviar_texto("+5581999999999", "Olá")

    assert "WHATSAPP_ACCESS_TOKEN" in str(exc_info.value)


def test_enviar_texto_ativo_sem_nenhuma_credencial_lista_as_duas(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)

    with pytest.raises(wc.WhatsAppConfigError) as exc_info:
        wc.enviar_texto("+5581999999999", "Olá")

    mensagem = str(exc_info.value)
    assert "WHATSAPP_PHONE_NUMBER_ID" in mensagem
    assert "WHATSAPP_ACCESS_TOKEN" in mensagem


def test_baixar_midia_ativo_sem_credenciais_levanta_config_error(monkeypatch):
    # baixar_midia não é bloqueada pelo kill switch (é leitura, não envio —
    # ver docstring), mas ainda exige configuração válida.
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)

    with pytest.raises(wc.WhatsAppConfigError):
        wc.baixar_midia("media-id-123")


# ======================================================================
# Montagem da URL base
# ======================================================================


def test_montar_url_base_usa_versao_configurada_e_phone_number_id(monkeypatch):
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v99.0")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789")

    url = wc.montar_url_base()

    assert url == "https://graph.facebook.com/v99.0/123456789"


def test_montar_url_base_usa_versao_padrao_quando_nao_configurada(monkeypatch):
    monkeypatch.delenv("WHATSAPP_GRAPH_API_VERSION", raising=False)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789")

    url = wc.montar_url_base()

    assert url.endswith("/123456789")
    assert url.startswith("https://graph.facebook.com/v")


def test_montar_url_base_sem_phone_number_id_levanta_config_error(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)

    with pytest.raises(wc.WhatsAppConfigError, match="WHATSAPP_PHONE_NUMBER_ID"):
        wc.montar_url_base()


def test_montar_url_graph_api_nao_exige_phone_number_id(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v21.0")

    assert wc.montar_url_graph_api() == "https://graph.facebook.com/v21.0"


# ======================================================================
# Logging seguro
# ======================================================================


def test_mascarar_telefone_mantem_so_ultimos_4_digitos():
    assert wc.mascarar_telefone("+5581999998888") == "*********8888"


def test_mascarar_telefone_numero_curto_mascara_tudo():
    assert wc.mascarar_telefone("88") == "**"


def test_access_token_nunca_aparece_em_mensagem_de_erro(monkeypatch, caplog):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "EAAG-token-super-secreto")
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)

    with pytest.raises(wc.WhatsAppConfigError) as exc_info:
        wc.enviar_texto("+5581999999999", "Olá")

    assert "EAAG-token-super-secreto" not in str(exc_info.value)
    assert "EAAG-token-super-secreto" not in caplog.text
