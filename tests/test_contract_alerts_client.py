from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from app.tools.contract_alerts_client import (
    aplicar_reajuste,
    listar_clausulas_financeiras,
    listar_contratos_ativos,
    listar_reajustes_para_aplicar,
    registrar_alerta_renovacao,
    registrar_calculo_reajuste,
)

CONTRACT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _mock_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-publica")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "segredo-de-teste")


@patch("app.tools.contract_alerts_client.obter_client_cron_batch")
def test_listar_contratos_ativos_valida_como_modelo(mock_obter_client, monkeypatch):
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(
        data=[
            {
                "id": str(CONTRACT_ID),
                "imovel_identificacao": "Apto 302, Ed. X",
                "inquilino_nome": "João Silva",
                "telefone_whatsapp": "+5581999999999",
                "data_inicio": "2025-01-15",
                "data_termino": "2026-01-15",
                "indice_reajuste": "igpm",
                "valor_aluguel": 1500.0,
            }
        ]
    )
    mock_obter_client.return_value = mock_client

    contratos = listar_contratos_ativos()

    mock_client.rpc.assert_called_once_with("cron_listar_contratos_ativos", {})
    assert len(contratos) == 1
    assert contratos[0].id == CONTRACT_ID
    assert contratos[0].indice_reajuste == "igpm"


@patch("app.tools.contract_alerts_client.obter_client_cron_batch")
def test_listar_clausulas_financeiras(mock_obter_client, monkeypatch):
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(
        data=[{"numero_clausula": "5.2", "texto_clausula": "Reajuste anual pelo IGPM."}]
    )
    mock_obter_client.return_value = mock_client

    clausulas = listar_clausulas_financeiras(CONTRACT_ID)

    mock_client.rpc.assert_called_once_with(
        "cron_listar_clausulas_financeiras", {"p_contract_id": str(CONTRACT_ID)}
    )
    assert clausulas == [("5.2", "Reajuste anual pelo IGPM.")]


@patch("app.tools.contract_alerts_client.obter_client_agente")
def test_registrar_alerta_renovacao_true_quando_inserido(mock_obter_client, monkeypatch):
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=str(uuid4()))
    mock_obter_client.return_value = mock_client

    assert registrar_alerta_renovacao(CONTRACT_ID, date(2026, 7, 15)) is True
    mock_obter_client.assert_called_once_with(CONTRACT_ID)


@patch("app.tools.contract_alerts_client.obter_client_agente")
def test_registrar_alerta_renovacao_false_quando_ja_existia(mock_obter_client, monkeypatch):
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=None)
    mock_obter_client.return_value = mock_client

    assert registrar_alerta_renovacao(CONTRACT_ID, date(2026, 7, 15)) is False


@patch("app.tools.contract_alerts_client.obter_client_agente")
def test_registrar_calculo_reajuste_chama_rpc_com_parametros_certos(mock_obter_client, monkeypatch):
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=str(uuid4()))
    mock_obter_client.return_value = mock_client

    resultado = registrar_calculo_reajuste(CONTRACT_ID, date(2026, 7, 15), 3.18, 1547.7)

    mock_obter_client.assert_called_once_with(CONTRACT_ID)
    mock_client.rpc.assert_called_once_with(
        "agent_registrar_calculo_reajuste",
        {
            "p_data_disparo": "2026-07-15",
            "p_percentual_reajuste": 3.18,
            "p_valor_sugerido": 1547.7,
        },
    )
    assert resultado is True


@patch("app.tools.contract_alerts_client.obter_client_cron_batch")
def test_listar_reajustes_para_aplicar(mock_obter_client, monkeypatch):
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    alerta_id = str(uuid4())
    mock_client.rpc.return_value.execute.return_value = MagicMock(
        data=[{"alerta_id": alerta_id, "contract_id": str(CONTRACT_ID), "valor_sugerido": 1547.7}]
    )
    mock_obter_client.return_value = mock_client

    resultado = listar_reajustes_para_aplicar(date(2026, 8, 14))

    mock_client.rpc.assert_called_once_with(
        "cron_listar_reajustes_para_aplicar", {"p_data_referencia": "2026-08-14"}
    )
    # PostgREST devolve uuid como string — a função deve converter de volta
    # para UUID, não repassar a string crua (ver docstring da função).
    assert resultado == [{"alerta_id": UUID(alerta_id), "contract_id": CONTRACT_ID, "valor_sugerido": 1547.7}]
    assert isinstance(resultado[0]["alerta_id"], UUID)


@patch("app.tools.contract_alerts_client.obter_client_agente")
def test_aplicar_reajuste_true_quando_condicao_bate(mock_obter_client, monkeypatch):
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=str(uuid4()))
    mock_obter_client.return_value = mock_client
    alerta_id = uuid4()

    resultado = aplicar_reajuste(alerta_id, CONTRACT_ID, 1547.7)

    mock_obter_client.assert_called_once_with(CONTRACT_ID)
    mock_client.rpc.assert_called_once_with(
        "agent_aplicar_reajuste",
        {"p_alerta_id": str(alerta_id), "p_valor_aplicado": 1547.7},
    )
    assert resultado is True


@patch("app.tools.contract_alerts_client.obter_client_agente")
def test_aplicar_reajuste_false_quando_condicao_nao_bate_mais(mock_obter_client, monkeypatch):
    """decisao_gestora mudou ou o alerta já foi aplicado entre a leitura da
    lista do dia e a escrita deste item — agent_aplicar_reajuste devolve
    null (via RETURNING) em vez de aplicar; o client não deve assumir
    sucesso silencioso."""
    _mock_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=None)
    mock_obter_client.return_value = mock_client

    resultado = aplicar_reajuste(uuid4(), CONTRACT_ID, 1547.7)

    assert resultado is False
