"""Ponto de entrada do processamento de uma mensagem recebida.

Chamado de dois lugares, com o MESMO payload no formato do WhatsApp Cloud
API (só a origem muda):
  - app/api/routers/whatsapp.py — webhook real, via BackgroundTasks (não
    espera o retorno, a Meta só precisa do 200 imediato).
  - app/api/routers/dev_chat.py — chat simulado de teste, chamado de forma
    síncrona (espera o retorno pra mostrar a resposta na tela).

Isso é proposital: quando a API real do WhatsApp entrar (Semana 4), só a
FONTE do payload muda (Meta em vez do formulário de teste) — a lógica de
recebimento, esta função, não precisa ser reescrita.

Roteamento de intenção real entre A1-A5 vive em app/orchestrator/orchestrator.py.
"""

import logging
import os
from typing import Optional

from supabase import create_client

from app.orchestrator.agent_auth import obter_client_agente
from app.orchestrator.orchestrator import rotear_mensagem

logger = logging.getLogger(__name__)


def processar_mensagem_recebida(payload: dict) -> Optional[str]:
    """Processa uma mensagem do WhatsApp (real ou simulada).

    Devolve a resposta do agente (texto) quando há uma, ou uma mensagem de
    erro/diagnóstico curta quando algo falha — útil pro chat simulado
    mostrar na tela. O webhook real ignora esse retorno (roda em
    BackgroundTasks); qualquer exceção aqui é tratada e logada, nunca deixada
    subir, porque depois que o webhook já respondeu 200 pra Meta uma exceção
    não tratada não chegaria a lugar nenhum além do log do processo mesmo.
    """
    try:
        entrada = payload["entry"][0]["changes"][0]["value"]
        mensagens = entrada.get("messages")
        if not mensagens:
            return None  # evento de status (entregue/lido), não é mensagem nova

        mensagem = mensagens[0]
        telefone = mensagem["from"]
        texto = mensagem.get("text", {}).get("body", "")
    except (KeyError, IndexError, TypeError):
        logger.exception("Payload do WhatsApp em formato inesperado, ignorando.")
        return "Erro: payload em formato inesperado (ver logs)."

    try:
        contract_id = _resolver_contract_id(telefone)
    except Exception:
        logger.exception("Falha ao resolver contract_id para o telefone %s", telefone)
        return "Erro ao resolver o contrato para esse telefone (ver logs)."

    if contract_id is None:
        logger.warning("Nenhum contrato ativo encontrado para o telefone %s", telefone)
        # TODO: acionar A5 (motivo=sem_clausula ou pedido_humano) quando não
        # há contrato correspondente — depende do roteamento do orquestrador
        # também cobrir esse caso (hoje rotear_mensagem só é chamado quando
        # já existe um contrato resolvido).
        return f"Nenhum contrato ativo encontrado para o telefone {telefone}."

    try:
        client = obter_client_agente(contract_id)
        client.rpc(
            "agent_log_message",
            {"p_remetente": "inquilino", "p_agente_responsavel": None, "p_mensagem": texto},
        ).execute()

        resposta, agente_responsavel = rotear_mensagem(contract_id, texto)

        client.rpc(
            "agent_log_message",
            {
                "p_remetente": "agente",
                "p_agente_responsavel": agente_responsavel,
                "p_mensagem": resposta,
            },
        ).execute()
    except Exception:
        logger.exception("Falha ao processar mensagem para contrato %s", contract_id)
        return "Erro ao processar a mensagem (ver logs)."

    return resposta


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
