"""Gravação de mensagens automáticas em conversation_logs.

O fluxo de chat (app/orchestrator/processar_mensagem.py) já grava via
agent_log_message, mas os envios proativos — cobrança do cron, avisos —
iam direto pro WhatsApp sem deixar rastro na tabela. Este módulo é o ponto
único pra esses envios gravarem o que foi dito ao inquilino.

Mesma política de retry do chat: poucas tentativas, backoff curto. A RPC é
um INSERT único — repetir uma tentativa que falhou nunca duplica a linha.
"""

import logging

from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_LOG_RETRY_MAX_TENTATIVAS = 3
_LOG_RETRY_ESPERA_MULTIPLICADOR_SEGUNDOS = 0.5
_LOG_RETRY_ESPERA_MAX_SEGUNDOS = 4.0


@retry(
    stop=stop_after_attempt(_LOG_RETRY_MAX_TENTATIVAS),
    wait=wait_exponential(
        multiplier=_LOG_RETRY_ESPERA_MULTIPLICADOR_SEGUNDOS, max=_LOG_RETRY_ESPERA_MAX_SEGUNDOS
    ),
    reraise=True,
)
def registrar_mensagem_automatica(client_agente, *, agente: str, mensagem: str) -> None:
    """Grava uma mensagem enviada pelo sistema ao inquilino do contrato do
    `client_agente` (obter_client_agente já escopa o contrato via JWT).

    Levanta a exceção original depois das tentativas — quem chama decide se
    uma falha de log pode ou não interromper o que está fazendo.
    """
    client_agente.rpc(
        "agent_log_message",
        {"p_remetente": "agente", "p_agente_responsavel": agente, "p_mensagem": mensagem},
    ).execute()


def registrar_se_enviado(resultado_envio, client_agente, *, agente: str, mensagem: str, contexto: str) -> None:
    """Grava `mensagem` em conversation_logs só se o envio foi REAL e nunca
    levanta: a mensagem já saiu pro inquilino, então falha de log é só
    logada e não pode desfazer nem interromper o que veio antes.

    Envio simulado (kill switch WHATSAPP_ENVIO_ATIVO desligado) não grava —
    nada chegou ao inquilino, então não houve conversa a registrar.
    `contexto` identifica o envio na mensagem de erro (ex.: "charge X").
    """
    if getattr(resultado_envio, "simulado", False) is True:
        return
    try:
        registrar_mensagem_automatica(client_agente, agente=agente, mensagem=mensagem)
    except Exception:
        logger.exception("Mensagem enviada, mas falhou ao gravar em conversation_logs (%s).", contexto)
