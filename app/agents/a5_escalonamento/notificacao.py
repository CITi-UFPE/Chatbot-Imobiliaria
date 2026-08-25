"""Notificação da equipe humana quando um caso é escalado pelo A5.

WA-05: transporte real via app/tools/whatsapp_client.py (WA-01/02/03),
mesmo padrão de app/agents/a4_gestao_contratual/fluxo.py::
_notificar_staff_alerta_contratual (WA-09): o destinatário é sempre a
equipe (Domingos/Fernanda), nunca o inquilino, e nunca é quem acabou de
mandar mensagem — mesmo quando `executar_escalonamento` é chamado
reativamente (avaliar_escalonamento, a partir de uma mensagem do
inquilino), do ponto de vista da equipe é sempre um contato novo. Por isso
este caminho vai sempre como TEMPLATE, mesmo nos dois casos de chamada
(reativo pelo webhook e proativo pelo cron do A2 no D+15 — atraso_severo).

O telefone reaproveita WHATSAPP_STAFF_PHONE_NUMBER (introduzida na WA-09
para o A4) via whatsapp_client.telefone_staff() — helper compartilhado com
app/agents/a4_gestao_contratual/fluxo.py, em vez de cada agente duplicar a
mesma checagem. Só é exigido quando o envio está de fato ativo; com o kill
switch desligado (padrão), a notificação fica em modo simulado sem exigir
nenhuma variável de WhatsApp configurada — mesmo comportamento de
_notificar_staff_alerta_contratual, coberto pelos testes equivalentes em
tests/test_a4_whatsapp_notification.py.
"""

import logging

from app.tools import whatsapp_client
from app.tools.whatsapp_message_policy import MensagemTemplate, enviar_saida

logger = logging.getLogger(__name__)

_TEMPLATE_ESCALONAMENTO_EQUIPE = "escalonamento_equipe"


def _enviar_template_staff(parametros: list[str]) -> None:
    if not whatsapp_client.envio_ativo():
        logger.info("whatsapp_client: operacao=notificar_staff simulado=True")
        return

    destino = whatsapp_client.telefone_staff()
    try:
        enviar_saida(
            destino,
            MensagemTemplate(
                nome=_TEMPLATE_ESCALONAMENTO_EQUIPE,
                parametros=tuple(parametros),
            ),
        )
    except Exception as erro:
        logger.error(
            "whatsapp_client: falha ao enviar (operacao=notificar_staff telefone=%s): %s",
            whatsapp_client.mascarar_telefone(destino),
            erro,
        )
        raise


def notificar_staff(mensagem: str) -> None:
    """Compatibilidade do notificador genérico usado pelo A3.

    O A3 ainda fornece apenas uma mensagem pronta de manutenção. Esse fluxo
    será mantido como veio da WA-05 até existir uma decisão específica de
    template para manutenção; não deve ser confundido com o template
    estruturado do escalonamento A5 abaixo.
    """
    _enviar_template_staff([mensagem])


def notificar_staff_escalonamento(protocolo: str, motivo: str, descricao: str) -> None:
    """A5 estruturado: protocolo, motivo e descrição na ordem da Meta."""
    _enviar_template_staff([protocolo, motivo, descricao])
