"""Identidade do agente de IA perante o Supabase.

Decisão de arquitetura (ver docs/setup-supabase.md, seção 5): o agente NUNCA
autentica com a service_role key nem com um login Supabase Auth comum. Em vez
disso, o próprio backend assina um JWT HS256 de curta duração por conversa,
contendo `role: agente_ia` e o `contract_id` resolvido a partir do número de
WhatsApp da mensagem recebida. Esse token é o que fala com o PostgREST — a
função `agent_contract_id()` (docs/schemas/002_auth_rbac_rls.sql) lê o claim
`contract_id` desse token para aplicar o isolamento por contrato em toda
política de RLS. Um bug no código do agente que buscasse o contrato errado
não teria como enxergar dados de outro contrato: a trava está no banco, não
na aplicação.

A chave de assinatura é a Standby Key HS256 criada manualmente no projeto
Supabase (Settings -> JWT Keys, "Import an existing secret") — não a chave
assimétrica padrão do projeto, que o Supabase nunca expõe.

Este módulo também assina tokens do papel "cron_batch" (ver
docs/schemas/008_cron_batch_cobranca.sql, origin/develop, e
docs/schemas/010_alertas_contratuais_e_reajuste.sql, seção 10.3) — usado
pelos jobs agendados que precisam ler TODOS os contratos ativos de uma vez
(ex: cron diário de cobrança do A2, cron diário de gestão contratual do A4),
o que o token agente_ia não permite por desenho (ele só enxerga UM
contract_id). Reaproveita a mesma SUPABASE_JWT_SECRET — só muda o valor do
claim "role" e a ausência do claim "contract_id". cron_batch nunca escreve
nada: toda escrita continua indo contrato por contrato, com
assinar_token_agente/obter_client_agente.
"""

import os
import time
import uuid

import jwt
from supabase import Client, create_client

# Curto de propósito: cada mensagem do WhatsApp gera um token novo, então não
# há necessidade de tokens de vida longa — reduz a janela de uso indevido se
# um token vazar (ex: em log de erro ou de request).
TTL_PADRAO_SEGUNDOS = 300

# O cron_batch processa todos os contratos ativos numa única execução — pode
# levar mais tempo que o ciclo de uma resposta de WhatsApp, então o TTL é
# mais generoso. Ainda assim curto o suficiente pra não valer a pena guardar
# um token vazado (o job roda 1x/dia, um token de 15min já expirou bem antes
# da próxima execução).
TTL_CRON_SEGUNDOS = 900


def _segredo_jwt() -> str:
    segredo = os.environ.get("SUPABASE_JWT_SECRET")
    if not segredo:
        raise RuntimeError(
            "SUPABASE_JWT_SECRET não configurado — sem ele o backend não consegue "
            "assinar tokens do agente. Ver docs/setup-supabase.md, seção 5."
        )
    return segredo


def assinar_token_agente(contract_id: str | uuid.UUID, ttl_segundos: int = TTL_PADRAO_SEGUNDOS) -> str:
    """Assina um JWT HS256 com role=agente_ia escopado a UM contrato.

    O claim `contract_id` é o que a função agent_contract_id() do Postgres lê
    para restringir toda política de RLS àquele contrato específico — nunca
    passar um contract_id que não seja o da conversa que está sendo
    processada neste momento.
    """
    agora = int(time.time())
    payload = {
        "role": "agente_ia",
        "contract_id": str(contract_id),
        "iat": agora,
        "exp": agora + ttl_segundos,
    }
    return jwt.encode(payload, _segredo_jwt(), algorithm="HS256")


def _client_com_token(token: str) -> Client:
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY não configurados no ambiente.")

    client = create_client(url, anon_key)
    # client.postgrest.auth() troca o header Authorization pelo nosso token
    # assinado. O apikey (anon) continua sendo enviado normalmente — é o
    # Authorization que o PostgREST usa para resolver "role" e os claims de
    # request.jwt.claims que as funções SECURITY DEFINER leem.
    client.postgrest.auth(token)
    return client


def obter_client_agente(contract_id: str | uuid.UUID, ttl_segundos: int = TTL_PADRAO_SEGUNDOS) -> Client:
    """Devolve um client Supabase autenticado como agente_ia para UM contrato.

    Toda chamada ao Supabase feita a partir do processamento de uma mensagem
    do WhatsApp deve usar o client devolvido por esta função — nunca a
    service_role key e nunca um client "genérico" sem token assinado. Isso
    garante que mesmo um bug de roteamento no orquestrador não consiga
    ler/escrever dados de um contrato diferente do da conversa em andamento.

    Exceção deliberada: resolver_contrato_por_telefone (chamada ANTES de
    existir um contract_id para assinar o token) usa o papel "anon" direto,
    sem passar por esta função — ver app/orchestrator/processar_mensagem.py.
    """
    token = assinar_token_agente(contract_id, ttl_segundos)
    return _client_com_token(token)


def assinar_token_cron_batch(ttl_segundos: int = TTL_CRON_SEGUNDOS) -> str:
    """Assina um JWT HS256 com role=cron_batch — SEM claim de contract_id.

    Só serve pra chamar RPCs explicitamente concedidas ao papel cron_batch
    (hoje: cron_listar_charges_ativas do A2, e as 3 cron_listar_* do A4 —
    ver docs/schemas/010_alertas_contratuais_e_reajuste.sql, seção 10.3).
    Não dá acesso de leitura direto a nenhuma tabela: cron_batch não tem
    GRANT de SELECT nelas, só EXECUTE nas funções de listagem. Nunca usar
    este token pra escrever nada — escrita continua sendo por contrato, com
    assinar_token_agente/obter_client_agente (ver seção 10.4 da migration
    acima para as funções de escrita do A4).
    """
    agora = int(time.time())
    payload = {
        "role": "cron_batch",
        "iat": agora,
        "exp": agora + ttl_segundos,
    }
    return jwt.encode(payload, _segredo_jwt(), algorithm="HS256")


def obter_client_cron_batch(ttl_segundos: int = TTL_CRON_SEGUNDOS) -> Client:
    """Devolve um client Supabase autenticado como cron_batch — cross-contrato,
    só leitura, só através das RPCs de listagem concedidas a esse papel.

    Usar exclusivamente dentro dos scripts de app/jobs/ (ex:
    cron_alertas_contratuais.py, A4), nunca no caminho de processamento de
    mensagem do WhatsApp — ali o token correto continua sendo o de
    obter_client_agente(contract_id), escopado a um contrato só."""
    token = assinar_token_cron_batch(ttl_segundos)
    return _client_com_token(token)
