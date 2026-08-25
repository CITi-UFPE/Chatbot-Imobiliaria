from __future__ import annotations

import pytest
from postgrest.exceptions import APIError
from supabase import Client

pytestmark = pytest.mark.integration


def _resolver(anon_client: Client, telefone: object) -> str | None:
    resposta = anon_client.rpc(
        "resolver_contrato_por_telefone", {"p_telefone": telefone}
    ).execute()
    return resposta.data


@pytest.mark.parametrize(
    "telefone",
    (
        "+55 (81) 99876-5420",
        "5581998765420",
        "81998765420",
        "558198765420",
        "8198765420",
    ),
)
def test_telefone_rpc_resolve_movel_atual_e_legado(
    anon_client: Client,
    contrato_telefone_movel_legado: dict,
    telefone: str,
) -> None:
    assert _resolver(anon_client, telefone) == contrato_telefone_movel_legado["contract_id"]


@pytest.mark.parametrize("telefone", ("+55 (81) 3456-7821", "558134567821", "8134567821"))
def test_telefone_rpc_resolve_fixo_sem_transformacao_movel(
    anon_client: Client,
    contrato_telefone_fixo: dict,
    telefone: str,
) -> None:
    assert _resolver(anon_client, telefone) == contrato_telefone_fixo["contract_id"]
    assert _resolver(anon_client, "5581934567821") is None


@pytest.mark.parametrize("telefone", (None, "", "81999", "4481998765420"))
def test_telefone_rpc_retorna_null_para_entrada_invalida(
    anon_client: Client, telefone: object
) -> None:
    assert _resolver(anon_client, telefone) is None


def test_telefone_rpc_retorna_null_sem_contrato(anon_client: Client) -> None:
    assert _resolver(anon_client, "5581998765499") is None


def test_telefone_equivalente_falha_antes_da_busca_do_contrato(
    service_role_client: Client,
    contrato_telefone_movel_legado: dict,
) -> None:
    duplicado = {
        **contrato_telefone_movel_legado["dados"],
        "imovel_identificacao": "Apto Fixture Telefone Duplicado",
        "telefone_whatsapp": "81998765420",
        "status": "pendente_confirmacao",
    }

    with pytest.raises(APIError) as exc_info:
        service_role_client.table("contracts").insert(duplicado).execute()

    assert exc_info.value.code == "23505"
    assert "contracts_telefone_normalizado_operacional_uidx" in str(exc_info.value)
