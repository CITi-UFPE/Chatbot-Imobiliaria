from unittest.mock import MagicMock, patch

import pytest

from app.models.maintenance import ClassificacaoManutencao
from app.tools.supabase_client import (
    abrir_ticket_manutencao,
    construir_abrir_ticket_fn,
    construir_criar_escalonamento_fn,
    criar_escalonamento,
    registrar_mensagem,
)


def _classificacao(**overrides) -> ClassificacaoManutencao:
    base = {
        "categoria": "hidraulica",
        "urgencia": "alta",
        "sinais_risco": ["vazamento grande"],
        "justificativa": "Vazamento grande relatado.",
        "categoria_confidence": 0.95,
        "urgencia_confidence": 0.95,
    }
    base.update(overrides)
    return ClassificacaoManutencao(**base)


@patch("app.tools.supabase_client.create_client")
def test_abrir_ticket_manutencao_chama_rpc_com_parametros_certos(mock_create_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(
        data=[{"id": "11111111-1111-1111-1111-111111111111", "protocolo": "MNT-2026-0001"}]
    )
    mock_create_client.return_value = mock_client

    ticket = abrir_ticket_manutencao("token-jwt-agente", _classificacao(), "Vazou muita água", False)

    mock_client.postgrest.auth.assert_called_once_with("token-jwt-agente")
    mock_client.rpc.assert_called_once_with(
        "agent_open_maintenance_ticket",
        {
            "p_categoria": "hidraulica",
            "p_urgencia": "alta",
            "p_descricao": "Vazou muita água",
            "p_sinais_risco": ["vazamento grande"],
            "p_classificacao_incerta": False,
        },
    )
    assert ticket.protocolo == "MNT-2026-0001"


@patch("app.tools.supabase_client.create_client")
def test_abrir_ticket_manutencao_levanta_erro_quando_rpc_retorna_vazio(mock_create_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=[])
    mock_create_client.return_value = mock_client

    with pytest.raises(RuntimeError, match="não retornou nenhuma linha"):
        abrir_ticket_manutencao("token-jwt-agente", _classificacao(), "Vazou muita água", False)


@patch("app.tools.supabase_client.create_client")
def test_construir_abrir_ticket_fn_fecha_access_token(mock_create_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")

    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(
        data=[{"id": "11111111-1111-1111-1111-111111111111", "protocolo": "MNT-2026-0001"}]
    )
    mock_create_client.return_value = mock_client

    abrir_ticket_fn = construir_abrir_ticket_fn("token-jwt-agente")
    ticket = abrir_ticket_fn(_classificacao(), "Vazou muita água", False)

    mock_client.postgrest.auth.assert_called_once_with("token-jwt-agente")
    assert ticket.protocolo == "MNT-2026-0001"


@patch("app.tools.supabase_client.create_client")
def test_construir_criar_escalonamento_fn_fecha_access_token(mock_create_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")

    mock_client = MagicMock()
    mock_create_client.return_value = mock_client

    criar_escalonamento_fn = construir_criar_escalonamento_fn("token-jwt-agente")
    criar_escalonamento_fn("pedido_humano", "Falha de identificação")

    mock_client.postgrest.auth.assert_called_once_with("token-jwt-agente")
    mock_client.rpc.assert_called_once_with(
        "agent_create_escalation",
        {"p_motivo": "pedido_humano", "p_descricao": "Falha de identificação"},
    )


@patch("app.tools.supabase_client.create_client")
def test_criar_escalonamento_chama_rpc_certa(mock_create_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")

    mock_client = MagicMock()
    mock_create_client.return_value = mock_client

    criar_escalonamento("token-jwt-agente", "pedido_humano", "Falha de identificação")

    mock_client.rpc.assert_called_once_with(
        "agent_create_escalation",
        {"p_motivo": "pedido_humano", "p_descricao": "Falha de identificação"},
    )


@patch("app.tools.supabase_client.create_client")
def test_registrar_mensagem_chama_rpc_certa(mock_create_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")

    mock_client = MagicMock()
    mock_create_client.return_value = mock_client

    registrar_mensagem("token-jwt-agente", "inquilino", "A torneira está pingando")

    mock_client.rpc.assert_called_once_with(
        "agent_log_message",
        {"p_remetente": "inquilino", "p_agente_responsavel": "A3", "p_mensagem": "A torneira está pingando"},
    )
