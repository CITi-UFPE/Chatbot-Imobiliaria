from unittest.mock import MagicMock, patch

import jwt
import pytest

from app.orchestrator.agent_auth import assinar_token_cron_batch, obter_client_cron_batch


def test_assinar_token_cron_batch_tem_role_cron_batch_sem_contract_id(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "segredo-de-teste")

    token = assinar_token_cron_batch()
    payload = jwt.decode(token, "segredo-de-teste", algorithms=["HS256"])

    assert payload["role"] == "cron_batch"
    assert "contract_id" not in payload


def test_assinar_token_cron_batch_sem_segredo_configurado_levanta_erro(monkeypatch):
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET"):
        assinar_token_cron_batch()


@patch("app.orchestrator.agent_auth.create_client")
def test_obter_client_cron_batch_autentica_com_token_assinado(mock_create_client, monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "segredo-de-teste")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")

    mock_client = MagicMock()
    mock_create_client.return_value = mock_client

    obter_client_cron_batch()

    mock_client.postgrest.auth.assert_called_once()
    token_usado = mock_client.postgrest.auth.call_args[0][0]
    payload = jwt.decode(token_usado, "segredo-de-teste", algorithms=["HS256"])
    assert payload["role"] == "cron_batch"
    assert "contract_id" not in payload
