"""Gravação de mensagens automáticas em conversation_logs.

O fluxo de chat (app/orchestrator/processar_mensagem.py) já grava via
agent_log_message, mas os envios proativos — cobrança do cron, avisos —
iam direto pro WhatsApp sem deixar rastro na tabela. Este módulo é o ponto
único pra esses envios gravarem o que foi dito ao inquilino e, com
`canal="administradora"`, a conversa interna com a administradora (o que o
sistema manda a ela e o que ela responde por botão ou reply).

Mesma política de retry do chat: poucas tentativas, backoff curto. A RPC é
um INSERT único — repetir uma tentativa que falhou nunca duplica a linha.
"""

import logging

from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

CANAL_INQUILINO = "inquilino"
CANAL_ADMINISTRADORA = "administradora"

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
def registrar_mensagem_automatica(
    client_agente,
    *,
    agente: str | None,
    mensagem: str,
    remetente: str = "agente",
    canal: str = CANAL_INQUILINO,
) -> None:
    """Grava uma mensagem no contrato do `client_agente`
    (obter_client_agente já escopa o contrato via JWT).

    `p_canal` só vai na chamada quando o canal NÃO é o do inquilino: assim a
    conversa com o inquilino segue funcionando mesmo antes da Migration 026
    (que acrescenta o parâmetro) ser aplicada no banco.

    Levanta a exceção original depois das tentativas — quem chama decide se
    uma falha de log pode ou não interromper o que está fazendo.
    """
    parametros = {"p_remetente": remetente, "p_agente_responsavel": agente, "p_mensagem": mensagem}
    if canal != CANAL_INQUILINO:
        parametros["p_canal"] = canal
    client_agente.rpc("agent_log_message", parametros).execute()


def envio_foi_real(resultado_envio) -> bool:
    """False só quando o resultado diz explicitamente `simulado=True` (kill
    switch desligado). Qualquer outro resultado conta como envio real."""
    return getattr(resultado_envio, "simulado", False) is not True


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


def registrar_conversa_administradora(
    contract_id: str | None,
    *,
    mensagem: str,
    agente: str | None,
    remetente: str,
    contexto: str,
    enviado: bool = True,
) -> None:
    """Grava no contrato `contract_id` uma mensagem da conversa com a
    administradora (`canal='administradora'`): `remetente='agente'` pro que o
    sistema manda a ela, `'gestora'` pro que ela manda (clique de botão, reply).

    `enviado=False` (envio simulado, kill switch desligado) não grava. Nunca
    levanta, como registrar_se_enviado: o envio ou a ação de negócio já
    aconteceu, falha de log não pode desfazê-la. `contract_id` vazio não
    grava — sem contrato não há onde pendurar a linha (conversation_logs
    exige contract_id)."""
    if not enviado or not contract_id:
        return
    try:
        # Import tardio: app.orchestrator importa deste módulo.
        from app.orchestrator.agent_auth import obter_client_agente

        registrar_mensagem_automatica(
            obter_client_agente(str(contract_id)),
            agente=agente,
            mensagem=mensagem,
            remetente=remetente,
            canal=CANAL_ADMINISTRADORA,
        )
    except Exception:
        logger.exception(
            "Conversa com a administradora ocorreu, mas falhou ao gravar em conversation_logs (%s).",
            contexto,
        )
