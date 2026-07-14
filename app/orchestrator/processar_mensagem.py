"""Ponto de entrada do processamento assíncrono de uma mensagem recebida.

Executado em BackgroundTasks pelo webhook do WhatsApp
(app/api/routers/whatsapp.py), fora do ciclo request/response que responde
à Meta. Ainda não faz classificação de intenção nem roteamento real entre
A1-A5 — isso depende do design do orquestrador (fora do escopo das 3 tarefas
atuais: JWT do agente, webhook assíncrono e A5). O que existe aqui hoje:
resolve o contrato a partir do telefone, registra a mensagem recebida em
conversation_logs, e deixa marcado onde o roteamento real vai entrar.
"""

import logging
import os

from supabase import create_client

from app.orchestrator.agent_auth import obter_client_agente

logger = logging.getLogger(__name__)


def processar_mensagem_recebida(payload: dict) -> None:
    """Processa uma mensagem do WhatsApp em background.

    Qualquer exceção aqui é responsabilidade desta função tratar e logar —
    como isso roda via BackgroundTasks, depois que o webhook já respondeu
    200 pra Meta, uma exceção não tratada não chega a lugar nenhum além do
    log do processo (não derruba o request, mas também não avisa ninguém
    sozinha).
    """
    try:
        entrada = payload["entry"][0]["changes"][0]["value"]
        mensagens = entrada.get("messages")
        if not mensagens:
            return  # evento de status (entregue/lido), não é mensagem nova

        mensagem = mensagens[0]
        telefone = mensagem["from"]
        texto = mensagem.get("text", {}).get("body", "")
    except (KeyError, IndexError, TypeError):
        logger.exception("Payload do WhatsApp em formato inesperado, ignorando.")
        return

    try:
        contract_id = _resolver_contract_id(telefone)
    except Exception:
        logger.exception("Falha ao resolver contract_id para o telefone %s", telefone)
        return

    if contract_id is None:
        logger.warning("Nenhum contrato ativo encontrado para o telefone %s", telefone)
        # TODO: acionar A5 (motivo=sem_clausula ou pedido_humano) quando não
        # há contrato correspondente — depende do roteamento do orquestrador.
        return

    try:
        client = obter_client_agente(contract_id)
        client.rpc(
            "agent_log_message",
            {"p_remetente": "inquilino", "p_agente_responsavel": None, "p_mensagem": texto},
        ).execute()
    except Exception:
        logger.exception("Falha ao registrar mensagem para contrato %s", contract_id)
        return

    # TODO: classificação de intenção + roteamento pra A1-A5. Ainda não
    # implementado — depende do design do orquestrador (fora do escopo das
    # 3 tarefas atuais). O A5 (app/agents/a5_escalonamento) já está pronto
    # pra ser chamado a partir daqui assim que o roteamento existir.


def _resolver_contract_id(telefone_whatsapp: str) -> str | None:
    """Descobre o contract_id ativo vinculado a um número de WhatsApp.

    Usa um client "anon" (sem token assinado) chamando a RPC
    resolver_contrato_por_telefone (docs/schemas/004_...) — não a
    service_role key. Antes de ter o contract_id ainda não dá para montar o
    JWT escopado do agente (é exatamente o dado que falta pra assinar o
    token), então esta é a única chamada ao Supabase neste módulo que não
    passa por obter_client_agente().
    """
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY não configurados.")

    client = create_client(url, anon_key)
    resposta = client.rpc("resolver_contrato_por_telefone", {"p_telefone": telefone_whatsapp}).execute()
    return resposta.data
