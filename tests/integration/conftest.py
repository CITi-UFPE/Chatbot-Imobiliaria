"""Harness dos testes de integração (A1-A5) — fala com um projeto Supabase
de TESTE real (banco, RLS, triggers, RPCs), nunca com mocks.

Ver tests/integration/README.md para como provisionar o projeto de teste e
rodar esta suíte. Sem `.env.test` preenchido, todo teste aqui é pulado
(nunca falha "quebrado" por falta de credencial — ver
`_validar_ambiente_de_teste` abaixo).
"""

import os
import uuid
from pathlib import Path
from typing import Callable, Iterator

import pytest
from dotenv import load_dotenv
from supabase import Client, create_client

# Star-import (não `pytest_plugins`, que só é suportado no conftest.py de
# rootdir em versões recentes do pytest, e este conftest não é o de
# rootdir): traz PREFIXO_TELEFONE_FIXTURE e os 8 fixtures de contrato
# (@pytest.fixture) de tests/integration/fixtures/contratos.py pro
# namespace deste módulo, onde o pytest de fato procura por fixtures.
# Nomes com "_" na frente (helpers privados do módulo) não vêm — Python já
# exclui por padrão num `import *` sem __all__.
from tests.integration.fixtures.contratos import *  # noqa: F401,F403

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_TEST_FILE = _REPO_ROOT / ".env.test"

# override=True: se o processo já tinha um .env de produção carregado (ex:
# rodando a suíte inteira do repo de uma vez), o de teste vence — nunca o
# contrário. Um teste de integração rodando contra o banco de produção por
# engano é exatamente o tipo de acidente que este arquivo existe pra evitar.
load_dotenv(_ENV_TEST_FILE, override=True)

_VARS_OBRIGATORIAS = (
    "SUPABASE_TEST_URL",
    "SUPABASE_TEST_ANON_KEY",
    "SUPABASE_TEST_SERVICE_ROLE_KEY",
    "SUPABASE_TEST_JWT_SECRET",
)


@pytest.fixture(scope="session", autouse=True)
def _validar_ambiente_de_teste() -> None:
    """Autouse + session-scoped: roda antes de qualquer outra fixture desta
    pasta (regra de ordenação do pytest: autouse vence fixtures explícitas
    do mesmo escopo). Se faltar alguma variável, PULA a suíte inteira com
    uma mensagem clara — nunca falha com um traceback de conexão."""
    faltando = [v for v in _VARS_OBRIGATORIAS if not os.environ.get(v)]
    if faltando:
        pytest.skip(
            "Testes de integração pulados — variáveis faltando no .env.test: "
            f"{', '.join(faltando)}. Copie .env.test.example para .env.test, "
            "preencha com as credenciais do projeto Supabase de TESTE (nunca "
            "produção) e rode de novo. Ver tests/integration/README.md."
        )

    # app/orchestrator/agent_auth.py e app/orchestrator/processar_mensagem.py
    # só conhecem SUPABASE_URL/SUPABASE_ANON_KEY/SUPABASE_JWT_SECRET — nunca
    # os nomes SUPABASE_TEST_*. Mapeamos aqui pra apontar o código de
    # produção pro projeto de teste, sem nenhum "if ENVIRONMENT==test" dentro
    # de app/.
    os.environ["SUPABASE_URL"] = os.environ["SUPABASE_TEST_URL"]
    os.environ["SUPABASE_ANON_KEY"] = os.environ["SUPABASE_TEST_ANON_KEY"]
    os.environ["SUPABASE_JWT_SECRET"] = os.environ["SUPABASE_TEST_JWT_SECRET"]
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("TIMEZONE", "America/Recife")


@pytest.fixture(scope="session")
def service_role_client(_validar_ambiente_de_teste: None) -> Client:
    """Client com a service_role key do projeto de TESTE — bypassa RLS
    inteiramente. Uso EXCLUSIVO de setup/teardown dos fixtures de contrato
    (inserir/apagar os dados fictícios) e de asserções sobre o estado final
    do banco. NUNCA usar para simular o caminho de um agente — isso é
    `agente_client_factory` abaixo, o único jeito de exercitar RLS de
    verdade (o mesmo client que a aplicação usa em produção)."""
    return create_client(
        os.environ["SUPABASE_TEST_URL"], os.environ["SUPABASE_TEST_SERVICE_ROLE_KEY"]
    )


@pytest.fixture(scope="session")
def anon_client(_validar_ambiente_de_teste: None) -> Client:
    """Cliente anon do Supabase de teste, igual ao usado para resolver contrato."""
    return create_client(os.environ["SUPABASE_TEST_URL"], os.environ["SUPABASE_TEST_ANON_KEY"])


@pytest.fixture(scope="session")
def agente_client_factory(_validar_ambiente_de_teste: None) -> Callable[[str | uuid.UUID], Client]:
    """Devolve `obter_client_agente`, a MESMA função que
    app/orchestrator/processar_mensagem.py usa em produção para autenticar
    como agente_ia escopado a um contract_id. Testes que querem verificar
    isolamento por RLS (não só a lógica Python) devem ler/escrever através
    deste client, nunca do service_role_client."""
    from app.orchestrator.agent_auth import obter_client_agente

    return obter_client_agente


@pytest.fixture(scope="session")
def api_client(_validar_ambiente_de_teste: None):
    """TestClient do FastAPI real (app/api/main.py), em processo — sem
    precisar de um `uvicorn` rodando à parte. Usado para bater no endpoint
    /dev/chat-simulado/mensagem, o caminho mais próximo do webhook de
    produção sem depender da conta real do WhatsApp (ver
    app/api/routers/dev_chat.py)."""
    from fastapi.testclient import TestClient

    from app.api.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def enviar_mensagem_simulada(api_client) -> Callable[..., dict]:
    """Atalho pro POST /dev/chat-simulado/mensagem. Uso:
    enviar_mensagem_simulada(telefone="+55...", texto="...") ou
    button_id=... ou imagem_base64=...+media_type=... (mutuamente
    exclusivos, ver MensagemSimulada em app/api/routers/dev_chat.py)."""

    def _enviar(telefone: str, **kwargs) -> dict:
        resposta = api_client.post(
            "/dev/chat-simulado/mensagem", json={"telefone": telefone, **kwargs}
        )
        resposta.raise_for_status()
        return resposta.json()

    return _enviar


def limpar_dados_por_telefone(service_role_client: Client, telefone: str) -> None:
    """Apaga o(s) contrato(s) fictício(s) com este telefone — usado tanto na
    limpeza defensiva no início da sessão (dado órfão de uma execução
    anterior que quebrou no meio) quanto no teardown normal. Todo o resto
    (charges, contract_clauses, maintenance_tickets, escalations,
    contract_alerts, conversation_logs, agent_conversation_states,
    charge_negotiations via charges) tem `on delete cascade` até contracts —
    ver docs/schemas/001_create_tables.sql e 007_estado_conversa_agente.sql
    — então apagar o contrato já é suficiente."""
    service_role_client.table("contracts").delete().eq("telefone_whatsapp", telefone).execute()


@pytest.fixture(scope="session", autouse=True)
def _limpeza_defensiva_de_sessao(
    _validar_ambiente_de_teste: None, service_role_client: Client
) -> Iterator[None]:
    """Limpa qualquer dado órfão (telefones com o prefixo de fixture) antes
    E depois da sessão inteira — cobre tanto "execução anterior crashou no
    meio" quanto o teardown normal desta execução."""
    telefones = [f"{PREFIXO_TELEFONE_FIXTURE}{n:03d}" for n in range(1, 20)]
    telefones.extend(TELEFONES_FIXTURE_NORMALIZACAO)
    for telefone in telefones:
        limpar_dados_por_telefone(service_role_client, telefone)

    yield

    for telefone in telefones:
        limpar_dados_por_telefone(service_role_client, telefone)
