"""Orquestrador — roteamento de intenção entre os agentes A1-A5.

Duas etapas:
  1. classificar_intencao (app/orchestrator/classificador.py) decide qual
     agente deve tratar a mensagem — classificação rasa e rápida, um
     system prompt curto devolvendo {agente, motivo, urgencia}.
  2. Roteamento de fato: hoje só o A5 tem lógica de agente implementada de
     verdade (app/agents/a5_escalonamento — critério próprio mais fino,
     protocolo, notificação). A1-A4 ainda são placeholders: as pastas
     app/agents/{a1_atendimento,a2_cobranca,a3_manutencao,
     a4_gestao_contratual}/ existem mas estão vazias. Quando cada uma
     ganhar lógica de negócio, o bloco correspondente abaixo passa a
     chamá-la — a estrutura do roteamento não deveria precisar mudar.
"""

import logging
from typing import Optional

from app.agents.a5_escalonamento import avaliar_escalonamento, executar_escalonamento
from app.orchestrator.classificador import classificar_intencao

logger = logging.getLogger(__name__)

_RESPOSTA_AGENTE_NAO_IMPLEMENTADO = (
    "Recebido! Sua mensagem foi identificada como assunto do Agente {agente} ({motivo}), "
    "mas esse agente ainda não está implementado neste ambiente. Sua mensagem foi registrada."
)

_RESPOSTA_A5_SEM_CRITERIO = (
    "Recebido! Isso pareceu um caso para a equipe humana, mas na análise mais detalhada "
    "não se encaixou em nenhum critério objetivo de escalonamento — sua mensagem foi "
    "registrada mesmo assim."
)


def rotear_mensagem(
    contract_id: str, texto: str, historico_conversa: str = ""
) -> tuple[str, Optional[str]]:
    """Classifica a intenção da mensagem e roteia pro agente correspondente.

    Devolve (resposta, agente_responsavel) — agente_responsavel é um dos
    valores aceitos por conversation_logs.agente_responsavel ('A1'..'A5')
    ou None se nem a classificação funcionou.
    """
    try:
        classificacao = classificar_intencao(texto, historico_conversa)
    except Exception:
        logger.exception("Falha ao classificar intenção para contrato %s", contract_id)
        # Sem classificação, cai no caminho mais conservador: trata como A5.
        # O próprio A5 decide se de fato escala; se não, cai no fallback dele.
        return _rotear_para_a5(contract_id, texto, historico_conversa)

    logger.info(
        "Classificação — contrato=%s agente=%s motivo=%r urgencia=%s",
        contract_id,
        classificacao.agente,
        classificacao.motivo,
        classificacao.urgencia,
    )

    if classificacao.agente == "A5":
        return _rotear_para_a5(contract_id, texto, historico_conversa)

    # TODO: A1-A4 ainda não têm lógica de negócio implementada (pastas
    # vazias). agente_responsavel já registra o roteamento correto mesmo
    # sem resposta real — útil para avaliar a precisão da classificação
    # antes desses agentes existirem.
    resposta = _RESPOSTA_AGENTE_NAO_IMPLEMENTADO.format(
        agente=classificacao.agente, motivo=classificacao.motivo
    )
    return resposta, classificacao.agente


def _rotear_para_a5(contract_id: str, texto: str, historico_conversa: str) -> tuple[str, Optional[str]]:
    """O A5 tem critério próprio mais fino (13 motivos objetivos, ver
    app/agents/a5_escalonamento/criterios.py) para decidir SE de fato escala
    e POR QUÊ — a classificação do orquestrador só decide que o assunto é da
    alçada do A5, não qual motivo específico nem se realmente deve escalar."""
    try:
        avaliacao = avaliar_escalonamento(texto, historico_conversa)
    except Exception:
        logger.exception("Falha ao avaliar escalonamento (A5) para contrato %s", contract_id)
        avaliacao = None

    if avaliacao is not None:
        protocolo = executar_escalonamento(contract_id, avaliacao)
        return f"{avaliacao.resposta_para_inquilino} (protocolo {protocolo})", "A5"

    return _RESPOSTA_A5_SEM_CRITERIO, "A5"
