"""Orquestrador — roteamento de intenção entre os agentes A1-A5.

Antes de tudo: se já existe uma conversa multi-turno em aberto pra este
contrato (hoje, só o A3 — ver _agente_com_conversa_ativa abaixo e
docs/schemas/015_agente_com_conversa_ativa.sql), a mensagem vai direto pro
agente dono dela, SEM passar por classificar_intencao. Motivo: o
classificador não tem visibilidade do estado da conversa (só a mensagem
atual), então uma resposta ambígua no meio do fluxo do A3 ("hein? que
endereço?") podia ser desviada pra outro agente e quebrar a máquina de
estados no meio do caminho.

Fora esse caso, duas etapas:
  1. classificar_intencao (app/orchestrator/classificador.py) decide qual
     agente deve tratar a mensagem — classificação rasa e rápida, um
     system prompt curto devolvendo {agente, motivo, urgencia}.
  2. Roteamento de fato: só A1 (app/agents/a1_atendimento), A3
     (app/agents/a3_manutencao) e A5 (app/agents/a5_escalonamento) recebem
     texto — classificador.py::AgenteDestino é literalmente restrito a
     esses três valores, então o schema da tool nem permite ao Claude
     devolver A2 ou A4 aqui. Não é um "ainda não" temporário: A4 é só cron
     (não reage a texto — ver app/agents/a4_gestao_contratual/fluxo.py) e
     A2 é só evento (ver abaixo) — nenhum dos dois vai ganhar uma
     integração de texto no futuro, então não existe bloco placeholder
     esperando ser preenchido pra eles. Um inquilino perguntando algo do
     universo de A2/A4 (pagamento, renovação) cai em A1 (se for
     informativo) ou A5 (se precisar mesmo de uma decisão humana).

     Diferença importante do A3 em relação ao A1/A5: é multi-turno (máquina
     de estados), então depende de persistência de estado entre mensagens —
     ver docs/schemas/007_estado_conversa_agente.sql e
     app/agents/a3_manutencao/atendimento.py, que carrega/salva esse estado
     a cada chamada.

  O A2 (app/agents/a2_cobranca) É DIFERENTE dos outros: não é acionado por
  texto classificado, e sim por TIPO de mensagem — imagem/PDF (comprovante)
  ou clique de botão interativo (decisão da Fernanda). Por isso não entra em
  rotear_mensagem/classificar_intencao; app/orchestrator/processar_mensagem.py
  decide o tipo de mensagem ANTES de chegar aqui e chama
  rotear_comprovante_a2/rotear_clique_botao_a2 diretamente, pulando a
  classificação de texto (não haveria texto pra classificar numa imagem).

  Exceção pontual a essa separação: quando o A5 (via _rotear_para_a5 abaixo)
  identifica motivo='desconto_renegociacao', este módulo chama
  pausar_charges_em_negociacao (API pública do A2) — é aqui, não no A1, que
  o escalonamento de fato acontece no caminho principal (o classificador já
  manda pedido de desconto/renegociação direto pro A5, nunca pro A1 — ver
  SYSTEM_PROMPT de classificador.py). `charges` continua sendo dado do
  domínio do A2; este módulo só decide QUANDO chamar, não COMO a pausa é
  feita.
"""

import logging
from typing import Optional

from app.agents.a1_atendimento import responder_inquilino
from app.agents.a2_cobranca import EntradaA2, TipoEntradaA2, pausar_charges_em_negociacao, processar_entrada_a2
from app.agents.a2_cobranca.button_ids import (
    ACAO_COMBINADO_TODOS,
    ACAO_CONFIRMAR,
    ACAO_DIVERGENTE,
    decodificar_button_id,
)
from app.agents.a3_manutencao import responder_manutencao
from app.agents.a5_escalonamento import avaliar_escalonamento, executar_escalonamento
from app.orchestrator.agent_auth import obter_client_agente
from app.orchestrator.classificador import classificar_intencao

logger = logging.getLogger(__name__)

_RESPOSTA_A2_COMPROVANTE_RECEBIDO = (
    "Recebemos seu comprovante! Vamos confirmar e te avisamos assim que possível."
)

_RESPOSTA_A2_COMPROVANTE_ERRO = (
    "Desculpe, tive um problema para processar seu comprovante agora. "
    "Ele foi registrado, mas pode ser necessário reenviar — nossa equipe vai verificar."
)

# Fallback de defesa em profundidade: com AgenteDestino restrito a A1/A3/A5
# (ver classificador.py), o schema da tool nem permite mais o Claude devolver
# outra coisa — este branch deveria ser inalcançável. Mantido só por
# segurança, e por isso o texto é genérico de propósito: nunca deve
# mencionar nome de agente, "ambiente", "implementado" ou qualquer outra
# palavra que denuncie arquitetura interna pro inquilino (o inquilino nunca
# pode perceber que está falando com um sistema multiagente).
_RESPOSTA_FALLBACK_GENERICO = (
    "Recebi sua mensagem! Já deixei registrado por aqui e alguém da nossa equipe "
    "te retorna em breve."
)

_RESPOSTA_A5_SEM_CRITERIO = (
    "Entendido! Já deixei registrado por aqui — se for necessário, alguém da "
    "nossa equipe entra em contato."
)


def rotear_mensagem(
    contract_id: str, texto: str, historico_conversa: str = ""
) -> tuple[str, Optional[str]]:
    """Classifica a intenção da mensagem e roteia pro agente correspondente.

    Devolve (resposta, agente_responsavel) — agente_responsavel é um dos
    valores aceitos por conversation_logs.agente_responsavel ('A1'..'A5')
    ou None se nem a classificação funcionou.
    """
    agente_ativo = _agente_com_conversa_ativa(contract_id)
    if agente_ativo == "A3":
        return _rotear_para_a3(contract_id, texto, historico_conversa)

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

    if classificacao.agente == "A1":
        return _rotear_para_a1(contract_id, texto, historico_conversa)

    if classificacao.agente == "A3":
        return _rotear_para_a3(contract_id, texto, historico_conversa)

    if classificacao.agente == "A5":
        return _rotear_para_a5(contract_id, texto, historico_conversa)

    # Inalcançável: AgenteDestino só aceita "A1"/"A3"/"A5" (ver
    # classificador.py) — o schema da tool nem permite ao Claude devolver
    # outro valor. Mantido por defesa em profundidade, não por expectativa
    # real de uso.
    logger.error(
        "classificar_intencao devolveu agente inesperado %r para contrato %s — "
        "isso não deveria ser possível com o schema atual.",
        classificacao.agente,
        contract_id,
    )
    return _RESPOSTA_FALLBACK_GENERICO, None


def _agente_com_conversa_ativa(contract_id: str) -> Optional[str]:
    """Se já existe uma conversa multi-turno em aberto pra este contrato (ex:
    A3 aguardando confirmação do imóvel ou a descrição do problema — ver
    agent_conversation_states, Migration 007), a mensagem atual pertence a
    ELA: reclassificar do zero via LLM arrisca desviar pra outro agente no
    meio do fluxo (uma resposta ambígua como "hein? que endereço?" não tem
    contexto suficiente pra classificar sozinha). Hoje só o A3 é multi-turno.

    Falha (RPC fora do ar, contract_id inválido etc.) cai em None — segue pro
    caminho normal de classificação em vez de travar a mensagem."""
    try:
        client = obter_client_agente(contract_id)
        return client.rpc("agent_get_active_agent", {}).execute().data
    except Exception:
        logger.exception(
            "Falha ao checar conversa ativa para contrato %s — seguindo para classificação normal.",
            contract_id,
        )
        return None


def _rotear_para_a1(contract_id: str, texto: str, historico_conversa: str) -> tuple[str, Optional[str]]:
    """O A1 já faz sua própria checagem de escalonamento (chama avaliar_escalonamento
    antes de tentar responder) e pode escalar sozinho no meio da resposta (ex:
    pergunta sem cláusula correspondente, ou loop de tool-use sem convergir) —
    por isso devolve sempre agente_responsavel='A1' aqui, mesmo quando o
    resultado final foi uma escalação: quem processou a mensagem foi o A1."""
    try:
        resposta = responder_inquilino(contract_id, texto, historico_conversa)
    except Exception:
        logger.exception("Falha ao processar mensagem no A1 para contrato %s", contract_id)
        resposta = (
            "Desculpe, tive um problema para consultar seus dados agora. "
            "Tente novamente em instantes."
        )
    return resposta, "A1"


def _rotear_para_a3(contract_id: str, texto: str, historico_conversa: str) -> tuple[str, Optional[str]]:
    """Diferente do A1 (stateless por mensagem), o A3 é uma máquina de
    estados multi-turno — responder_manutencao carrega o estado salvo (se
    houver), processa o turno, e persiste o estado atualizado antes de
    devolver. Ver app/agents/a3_manutencao/atendimento.py."""
    try:
        resposta = responder_manutencao(contract_id, texto, historico_conversa)
    except Exception:
        logger.exception("Falha ao processar mensagem no A3 para contrato %s", contract_id)
        resposta = (
            "Desculpe, tive um problema para registrar seu chamado agora. "
            "Tente novamente em instantes."
        )
    return resposta, "A3"


def _rotear_para_a5(contract_id: str, texto: str, historico_conversa: str) -> tuple[str, Optional[str]]:
    """O A5 tem critério próprio mais fino (13 motivos objetivos, ver
    app/agents/a5_escalonamento/criterios.py) para decidir SE de fato escala
    e POR QUÊ — a classificação do orquestrador só decide que o assunto é da
    alçada do A5, não qual motivo específico nem se realmente deve escalar.

    Quando o motivo for 'desconto_renegociacao', também aciona
    pausar_charges_em_negociacao (API pública do A2) — é aqui, e não no A1,
    que esse gancho pertence: o classificador já manda pedido de
    desconto/renegociação direto pro A5 (ver SYSTEM_PROMPT de
    classificador.py), então é este é o caminho que de fato roda no fluxo
    principal."""
    try:
        avaliacao = avaliar_escalonamento(texto, historico_conversa)
    except Exception:
        logger.exception("Falha ao avaliar escalonamento (A5) para contrato %s", contract_id)
        avaliacao = None

    if avaliacao is not None:
        protocolo = executar_escalonamento(contract_id, avaliacao)
        if avaliacao.motivo == "desconto_renegociacao":
            pausar_charges_em_negociacao(contract_id)
        return f"{avaliacao.resposta_para_inquilino} (protocolo {protocolo})", "A5"

    return _RESPOSTA_A5_SEM_CRITERIO, "A5"


def rotear_comprovante_a2(
    contract_id: str, imagem_base64: str, media_type: str
) -> tuple[str, Optional[str]]:
    """Chamado direto por app/orchestrator/processar_mensagem.py quando a
    mensagem do inquilino é uma imagem/PDF — não passa por
    classificar_intencao (não há texto pra classificar). A resposta aqui é
    só um reconhecimento imediato pro inquilino; a confirmação de fato
    (pagamento aceito/divergente) chega depois, quando a Fernanda decidir
    pelo botão — ver app/agents/a2_cobranca/comprovante.py."""
    try:
        processar_entrada_a2(
            EntradaA2(
                tipo_entrada=TipoEntradaA2.COMPROVANTE_RECEBIDO,
                contract_id=contract_id,
                imagem_base64=imagem_base64,
                media_type=media_type,
            )
        )
    except Exception:
        logger.exception("Falha ao processar comprovante no A2 para contrato %s", contract_id)
        return _RESPOSTA_A2_COMPROVANTE_ERRO, "A2"

    return _RESPOSTA_A2_COMPROVANTE_RECEBIDO, "A2"


def rotear_clique_botao_a2(button_id: str) -> str:
    """Chamado direto por app/orchestrator/processar_mensagem.py quando a
    mensagem recebida é um clique de botão interativo. Diferente de todo o
    resto deste módulo: quem clicou é a FERNANDA (staff), não um inquilino
    numa conversa de contrato — por isso não recebe contract_id como
    parâmetro (não existe telefone de inquilino pra resolver aqui) e não
    passa por agent_log_message (isso é uma ação administrativa, não uma
    mensagem de conversa). contract_id/charge_id(s) vêm decodificados do
    próprio button_id — ver app/agents/a2_cobranca/button_ids.py.

    Devolve só um texto curto (log/debug), não uma resposta de chat."""
    decodificado = decodificar_button_id(button_id)
    if decodificado is None:
        logger.warning("Clique de botão do A2 com id não reconhecido: %r", button_id)
        return "Não consegui reconhecer essa ação — verifique manualmente no banco."

    try:
        if decodificado.acao == ACAO_CONFIRMAR:
            processar_entrada_a2(
                EntradaA2(
                    tipo_entrada=TipoEntradaA2.CONFIRMACAO_FERNANDA,
                    contract_id=decodificado.contract_id,
                    charge_id=decodificado.charge_ids[0],
                )
            )
            return "Pagamento confirmado."

        if decodificado.acao == ACAO_DIVERGENTE:
            processar_entrada_a2(
                EntradaA2(
                    tipo_entrada=TipoEntradaA2.DIVERGENCIA_FERNANDA,
                    contract_id=decodificado.contract_id,
                    charge_id=decodificado.charge_ids[0],
                )
            )
            return "Marcado como divergente — resolva diretamente com o inquilino."

        if decodificado.acao == ACAO_COMBINADO_TODOS:
            processar_entrada_a2(
                EntradaA2(
                    tipo_entrada=TipoEntradaA2.PAGAMENTO_COMBINADO_CONFIRMADO,
                    contract_id=decodificado.contract_id,
                    charge_ids=decodificado.charge_ids,
                )
            )
            return "Pagamento combinado confirmado — todas as cobranças envolvidas foram quitadas."
    except Exception:
        logger.exception("Falha ao processar clique de botão do A2: %r", button_id)
        return "Tive um problema para registrar essa ação — verifique manualmente no banco."

    # Inalcançável: decodificar_button_id já filtra pra só as 3 ações acima
    # (ACAO_COMBINADO_PARCIAL nunca é decodificado — ver button_ids.py).
    # Mantido por defesa em profundidade.
    return "Ação reconhecida mas ainda não implementada."