"""Notificação da equipe humana quando um caso é escalado pelo A5.

Ainda não implementado de fato — depende da API do WhatsApp Business (Meta
Cloud API) estar contratada e configurada (WHATSAPP_ACCESS_TOKEN /
WHATSAPP_PHONE_NUMBER_ID em .env, hoje vazias). Por ora só loga a mensagem
que seria enviada, pra não quebrar o fluxo de escalonamento por causa de uma
dependência externa que ainda não existe — o resto do A5 (protocolo, gravação
em `escalations`) funciona normalmente mesmo sem notificação real.

Quando as credenciais existirem: trocar o corpo desta função por uma chamada
real à Cloud API (enviar mensagem de template ou texto livre pro número da
equipe) — manter a mesma assinatura, pra não precisar mexer em quem chama
(escalonamento.py).
"""

import logging
import os

logger = logging.getLogger(__name__)


def notificar_staff(mensagem: str) -> None:
    if not os.environ.get("WHATSAPP_ACCESS_TOKEN"):
        logger.warning(
            "WhatsApp Business API ainda não configurada — notificação NÃO enviada "
            "(ficou só neste log). Mensagem que seria enviada:\n%s",
            mensagem,
        )
        return

    raise NotImplementedError(
        "WHATSAPP_ACCESS_TOKEN já configurado, mas o envio real via Meta Cloud API "
        "ainda não foi implementado neste módulo."
    )
