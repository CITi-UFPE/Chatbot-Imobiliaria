"""Webhook do WhatsApp Business API (Meta Cloud API).

Duas responsabilidades, nada além disso:
  1. Verificação do webhook (GET) — handshake exigido pela Meta ao configurar
     a URL do webhook no painel do WhatsApp Business.
  2. Recebimento de mensagens (POST) — responde 200 pra Meta o mais rápido
     possível e processa a mensagem em BackgroundTasks. Por quê: a Meta
     reenvia a mesma mensagem se não receber 200 dentro de poucos segundos,
     e o processamento real (orquestrador -> agente -> banco, com chamada à
     Claude no meio) pode facilmente ultrapassar isso — sem BackgroundTasks,
     corremos risco de timeout E de processar a mesma mensagem duas vezes.
"""

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.orchestrator.processar_mensagem import processar_mensagem_recebida

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/whatsapp", tags=["whatsapp"])

# Guarda em memória os IDs de mensagem já processados nesta instância, pra
# não duplicar processamento se a Meta reenviar (ex: nosso 200 demorou ou se
# perdeu na rede). Isso NÃO sobrevive a um restart/deploy nem funciona com
# múltiplas instâncias rodando ao mesmo tempo — pra produção multi-instância,
# trocar por uma tabela no Postgres ou uma chave no Redis (já está nas
# variáveis de ambiente do projeto) com constraint/SETNX. Suficiente para o
# estágio atual (uma instância só no Railway).
_mensagens_processadas: set[str] = set()
_LIMITE_CACHE = 10_000  # evita crescimento sem limite em memória


@router.get("")
async def verificar_webhook(request: Request) -> Response:
    modo = request.query_params.get("hub.mode")
    token_recebido = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")

    token_esperado = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
    if modo == "subscribe" and token_esperado and token_recebido == token_esperado:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("")
async def receber_mensagem(request: Request, background_tasks: BackgroundTasks) -> dict:
    corpo_bruto = await request.body()

    if not _assinatura_valida(request, corpo_bruto):
        logger.warning("Webhook recebeu POST com assinatura inválida — ignorando.")
        return {"status": "assinatura_invalida"}

    payload = await request.json()

    message_id = _extrair_message_id(payload)
    if message_id is not None:
        if message_id in _mensagens_processadas:
            logger.info("Mensagem %s já processada — ignorando reenvio da Meta.", message_id)
            return {"status": "ja_processado"}
        _mensagens_processadas.add(message_id)
        if len(_mensagens_processadas) > _LIMITE_CACHE:
            _mensagens_processadas.clear()  # proteção simples contra crescimento ilimitado

    background_tasks.add_task(processar_mensagem_recebida, payload, responder_via_whatsapp=True)
    return {"status": "recebido"}


def _assinatura_valida(request: Request, corpo_bruto: bytes) -> bool:
    """Verifica o header X-Hub-Signature-256 que a Meta envia em todo POST.

    Sem WHATSAPP_APP_SECRET configurado (ainda não existe — a conta do
    WhatsApp Business API ainda não foi contratada), pula a verificação: não
    dá pra validar o que não temos, e bloquear tudo deixaria impossível
    testar o resto do fluxo antes dessas credenciais existirem. Assim que o
    segredo existir, a verificação passa a ser obrigatória automaticamente —
    não precisa mudar código nenhum, só preencher a variável de ambiente.
    """
    segredo = os.environ.get("WHATSAPP_APP_SECRET")
    if not segredo:
        logger.warning(
            "WHATSAPP_APP_SECRET não configurado — pulando verificação de assinatura "
            "do webhook. OK em desenvolvimento, mas isso precisa existir antes de produção."
        )
        return True

    assinatura_recebida = request.headers.get("x-hub-signature-256", "")
    esperado = "sha256=" + hmac.new(segredo.encode(), corpo_bruto, hashlib.sha256).hexdigest()
    return hmac.compare_digest(assinatura_recebida, esperado)


def _extrair_message_id(payload: dict) -> str | None:
    """Extrai o id da mensagem do payload do WhatsApp Cloud API, se presente.

    Formato oficial: payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    Retorna None se o payload não tiver esse formato (ex: eventos de status
    de entrega/leitura, que têm estrutura diferente e não precisam de dedup).
    """
    try:
        return payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    except (KeyError, IndexError, TypeError):
        return None
