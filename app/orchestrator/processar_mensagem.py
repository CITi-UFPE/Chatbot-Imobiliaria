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

Três tipos de mensagem tratados, cada um com seu próprio caminho:
  - "text" (ou ausente): fluxo de sempre — resolve contract_id pelo
    telefone do inquilino, classifica e roteia entre A1/A3/A5 (ver
    app/orchestrator/orchestrator.py::rotear_mensagem).
  - "image"/"document": comprovante de pagamento (A2) — mesmo contract_id
    resolvido pelo telefone do inquilino, mas SEM passar pelo classificador
    de texto (não há texto pra classificar); vai direto pra
    rotear_comprovante_a2.
  - "interactive" (button_reply): clique de botão da FERNANDA (staff), não
    de um inquilino — não resolve contract_id por telefone (o telefone dela
    não está em contracts.telefone_whatsapp), o contract_id/charge_id vêm
    decodificados do próprio id do botão. Vai direto pra
    rotear_clique_botao_a2, sem passar por agent_log_message.

Roteamento de intenção real entre A1-A5 vive em app/orchestrator/orchestrator.py.
"""

import logging
import os
from typing import Optional

from supabase import create_client
from tenacity import retry, stop_after_attempt, wait_exponential

from app.orchestrator.agent_auth import obter_client_agente
from app.orchestrator.orchestrator import (
    rotear_clique_botao_a2,
    rotear_comprovante_a2,
    rotear_mensagem,
)
from app.tools.whatsapp_client import enviar_texto, mascarar_telefone

logger = logging.getLogger(__name__)

# Retry da gravação de log no banco (agent_log_message) — mesma política
# aplicada ao transporte HTTP do WhatsApp (app/tools/whatsapp_client.py):
# poucas tentativas, backoff curto, nunca segurar demais um BackgroundTask
# do webhook. A RPC é atômica (um INSERT só) — repetir uma tentativa que
# falhou nunca duplica a linha no histórico.
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
def _registrar_log_mensagem(client, params: dict) -> None:
    """Grava uma linha em conversation_logs via agent_log_message, tentando
    de novo automaticamente em caso de falha transitória (rede/banco
    instável) antes de desistir e propagar a exceção pro chamador."""
    client.rpc("agent_log_message", params).execute()


def processar_mensagem_recebida(payload: dict, *, responder_via_whatsapp: bool = False) -> Optional[str]:
    """Processa uma mensagem do WhatsApp (real ou simulada).

    Devolve a resposta do agente (texto) quando há uma, ou uma mensagem de
    erro/diagnóstico curta quando algo falha — útil pro chat simulado
    mostrar na tela. O webhook real ignora esse retorno (roda em
    BackgroundTasks); qualquer exceção aqui é tratada e logada, nunca deixada
    subir, porque depois que o webhook já respondeu 200 pra Meta uma exceção
    não tratada não chegaria a lugar nenhum além do log do processo mesmo.

    `responder_via_whatsapp` (WA-04): quando True, a resposta não vazia dos
    fluxos de texto/mídia também é enviada de volta ao remetente pelo
    cliente WhatsApp real (app/tools/whatsapp_client.py). Só o webhook real
    (app/api/routers/whatsapp.py) passa True; o chat simulado
    (app/api/routers/dev_chat.py) mantém o padrão False — ele só precisa do
    texto de retorno pra mostrar na tela, nunca deve disparar mensagem
    externa de verdade. Cliques de botão da Fernanda (staff) nunca são
    enviados de volta por este mecanismo, mesmo com a flag ligada: o
    telefone do clique é o dela, não o do inquilino que deveria receber a
    resposta.
    """
    try:
        entrada = payload["entry"][0]["changes"][0]["value"]
        mensagens = entrada.get("messages")
        if not mensagens:
            return None  # evento de status (entregue/lido), não é mensagem nova
        mensagem = mensagens[0]
        tipo_mensagem = mensagem.get("type", "text")
    except (KeyError, IndexError, TypeError):
        logger.exception("Payload do WhatsApp em formato inesperado, ignorando.")
        return "Erro: payload em formato inesperado (ver logs)."

    if tipo_mensagem == "interactive":
        return _processar_clique_botao(mensagem)

    if tipo_mensagem in ("image", "document"):
        return _processar_comprovante(mensagem, responder_via_whatsapp=responder_via_whatsapp)

    return _processar_mensagem_texto(mensagem, responder_via_whatsapp=responder_via_whatsapp)


def _enviar_resposta_se_necessario(
    telefone: Optional[str], resposta: Optional[str], responder_via_whatsapp: bool
) -> None:
    """Envia `resposta` ao remetente pelo WhatsApp real, quando solicitado.

    Chamada só pelos fluxos de texto/mídia (mensagem de um inquilino) —
    nunca pelo clique de botão da Fernanda. Falha no envio é logada e NUNCA
    propagada: a esta altura os efeitos de negócio (RPC de log, resposta do
    agente) já aconteceram e não devem ser desfeitos por um problema de
    transporte (regra explícita da WA-04).
    """
    if not responder_via_whatsapp or not telefone or not resposta:
        return
    try:
        enviar_texto(telefone, resposta)
    except Exception:
        logger.exception(
            "Falha ao enviar resposta via WhatsApp para %s (efeitos do agente já concluídos).",
            mascarar_telefone(telefone),
        )


def _processar_mensagem_texto(mensagem: dict, *, responder_via_whatsapp: bool = False) -> Optional[str]:
    """Fluxo original: mensagem de texto de um inquilino, classificada e
    roteada entre A1/A3/A5."""
    try:
        telefone = mensagem["from"]
        texto = mensagem.get("text", {}).get("body", "")
    except (KeyError, TypeError):
        logger.exception("Mensagem de texto em formato inesperado, ignorando.")
        return "Erro: payload em formato inesperado (ver logs)."

    try:
        contract_id = _resolver_contract_id(telefone)
    except Exception:
        logger.exception("Falha ao resolver contract_id para o telefone %s", telefone)
        resposta = "Erro ao resolver o contrato para esse telefone (ver logs)."
        _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
        return resposta

    if contract_id is None:
        logger.warning("Nenhum contrato ativo encontrado para o telefone %s", telefone)
        # TODO: acionar A5 (motivo=sem_clausula ou pedido_humano) quando não
        # há contrato correspondente — depende do roteamento do orquestrador
        # também cobrir esse caso (hoje rotear_mensagem só é chamado quando
        # já existe um contrato resolvido).
        resposta = f"Nenhum contrato ativo encontrado para o telefone {telefone}."
        _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
        return resposta

    try:
        client = obter_client_agente(contract_id)
        _registrar_log_mensagem(
            client, {"p_remetente": "inquilino", "p_agente_responsavel": None, "p_mensagem": texto}
        )

        resposta, agente_responsavel = rotear_mensagem(contract_id, texto)
    except Exception:
        logger.exception("Falha ao processar mensagem para contrato %s", contract_id)
        resposta = "Erro ao processar a mensagem (ver logs)."
        _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
        return resposta

    try:
        _registrar_log_mensagem(
            client,
            {
                "p_remetente": "agente",
                "p_agente_responsavel": agente_responsavel,
                "p_mensagem": resposta,
            },
        )
    except Exception:
        # Diferente de uma falha ANTES de rotear_mensagem: aqui a resposta já
        # foi calculada com sucesso — uma falha só no REGISTRO dela no
        # histórico não deve descartar uma resposta válida (mesmo raciocínio
        # já aplicado ao fluxo de comprovante, ver _processar_comprovante).
        logger.exception("Falha ao registrar resposta do agente para contrato %s", contract_id)

    _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
    return resposta


def _processar_comprovante(mensagem: dict, *, responder_via_whatsapp: bool = False) -> Optional[str]:
    """Mensagem de imagem/PDF — tratada como comprovante de pagamento (A2).
    O inquilino ainda é resolvido pelo telefone (é ele quem manda a mídia
    numa conversa do contrato dele), mas não passa pelo classificador de
    texto: a suposição de que toda mídia numa conversa de contrato é
    comprovante já está documentada em
    app/agents/a2_cobranca/orquestrador_a2.py."""
    try:
        telefone = mensagem["from"]
        tipo_midia = mensagem.get("type", "image")
        midia = mensagem.get(tipo_midia, {})
    except (KeyError, TypeError):
        logger.exception("Mensagem de mídia em formato inesperado, ignorando.")
        return "Erro: payload em formato inesperado (ver logs)."

    media_type = midia.get("mime_type", "application/octet-stream")
    # "_dados_base64" não existe no payload real da Meta — só no payload
    # simulado (app/api/routers/dev_chat.py), que embute a imagem direto
    # sem precisar baixar nada. No payload real, só existe o media_id, que
    # exige uma chamada autenticada à Media API da Meta pra baixar o
    # conteúdo de fato — ver _baixar_midia_whatsapp.
    imagem_base64 = midia.get("_dados_base64")
    if imagem_base64 is None:
        try:
            imagem_base64 = _baixar_midia_whatsapp(midia.get("id"))
        except Exception:
            logger.exception("Falha ao baixar mídia %s do WhatsApp.", midia.get("id"))
            resposta = (
                "Recebemos seu arquivo, mas ainda não conseguimos baixá-lo automaticamente "
                "(integração de mídia do WhatsApp Business pendente). Registrado para análise manual."
            )
            _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
            return resposta

    try:
        contract_id = _resolver_contract_id(telefone)
    except Exception:
        logger.exception("Falha ao resolver contract_id para o telefone %s", telefone)
        resposta = "Erro ao resolver o contrato para esse telefone (ver logs)."
        _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
        return resposta

    if contract_id is None:
        logger.warning("Nenhum contrato ativo encontrado para o telefone %s", telefone)
        resposta = f"Nenhum contrato ativo encontrado para o telefone {telefone}."
        _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
        return resposta

    resposta, agente_responsavel = rotear_comprovante_a2(contract_id, imagem_base64, media_type)

    try:
        client = obter_client_agente(contract_id)
        _registrar_log_mensagem(
            client,
            {
                "p_remetente": "inquilino",
                "p_agente_responsavel": None,
                "p_mensagem": "[comprovante recebido]",
            },
        )
        _registrar_log_mensagem(
            client,
            {
                "p_remetente": "agente",
                "p_agente_responsavel": agente_responsavel,
                "p_mensagem": resposta,
            },
        )
    except Exception:
        # Diferente do fluxo de texto: uma falha no LOG do comprovante não
        # deve esconder do inquilino que o comprovante já foi processado
        # (rotear_comprovante_a2 acima já rodou) — só loga o problema de
        # registro e segue devolvendo a resposta real.
        logger.exception("Falha ao registrar log de comprovante para contrato %s", contract_id)

    _enviar_resposta_se_necessario(telefone, resposta, responder_via_whatsapp)
    return resposta


def _processar_clique_botao(mensagem: dict) -> Optional[str]:
    """Clique de botão interativo — vem do telefone da FERNANDA (staff), não
    de um inquilino, então não passa por _resolver_contract_id nem por
    agent_log_message (não é mensagem de conversa de contrato, é ação
    administrativa). contract_id/charge_id vêm decodificados do próprio
    button_id dentro de rotear_clique_botao_a2."""
    interactive = mensagem.get("interactive", {})
    if interactive.get("type") != "button_reply":
        logger.warning("Mensagem interactive de tipo não suportado: %r", interactive.get("type"))
        return None

    button_id = interactive.get("button_reply", {}).get("id", "")
    return rotear_clique_botao_a2(button_id)


def _baixar_midia_whatsapp(media_id: Optional[str]) -> str:
    """Baixa o arquivo de mídia real da Meta Cloud API a partir do media_id
    do webhook — exige WHATSAPP_ACCESS_TOKEN (ainda não configurado, mesma
    lacuna documentada em app/agents/a2_cobranca/notificacao.py). Sempre
    levanta por ora; quando o token existir, trocar pelo GET autenticado
    (1. GET /{media_id} pra resolver a URL assinada, 2. GET nessa URL pra
    baixar o conteúdo) + base64-encode do resultado."""
    if not os.environ.get("WHATSAPP_ACCESS_TOKEN") or not media_id:
        raise RuntimeError(
            "Download de mídia real do WhatsApp ainda não implementado "
            "(sem WHATSAPP_ACCESS_TOKEN configurado)."
        )
    raise NotImplementedError("Download de mídia via Meta Cloud API ainda não implementado.")


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
