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

Resposta da gestora (Migration 022): as três funções abaixo agora devolvem
o `message_id` (wamid) que a Meta atribuiu ao envio — `None` em modo
simulado, quando não há chamada HTTP nenhuma. `executar_escalonamento`
(escalonamento.py) usa esse wamid para gravar a correlação
(agent_registrar_wamid_escalonamento) que depois permite identificar a
qual escalação um reply nativo da Fernanda se refere — ver
resposta_gestora.py.
"""

import logging
from typing import Optional

from app.tools import whatsapp_client
from app.tools.whatsapp_message_policy import MensagemTemplate, enviar_saida

logger = logging.getLogger(__name__)

_TEMPLATE_ESCALONAMENTO_EQUIPE = "escalonamento_equipe"

# Checkup pós-WA-06/WA-08 (Ponto 3): o A3 reutilizava escalonamento_equipe
# (3 variáveis) mandando só 1 parâmetro (a mensagem pronta) — a Meta
# rejeitaria isso com envio real ativo (contagem de variáveis não bate).
# Template próprio de manutenção, com suas 5 variáveis
# (protocolo/imóvel/categoria/urgência/descrição) — ver
# app/tools/mensagens_manutencao.py::montar_parametros_notificacao_gestora e
# docs/whatsapp/templates-meta.md.
_TEMPLATE_MANUTENCAO_EQUIPE = "manutencao_equipe"


def _enviar_template_staff(
    nome_template: str, parametros: list[str], *, operacao: str
) -> Optional[str]:
    if not whatsapp_client.envio_ativo():
        logger.info("whatsapp_client: operacao=%s simulado=True", operacao)
        return None

    destino = whatsapp_client.telefone_staff()
    try:
        resultado = enviar_saida(
            destino,
            MensagemTemplate(
                nome=nome_template,
                parametros=tuple(parametros),
            ),
        )
    except Exception as erro:
        logger.error(
            "whatsapp_client: falha ao enviar (operacao=%s telefone=%s): %s",
            operacao,
            whatsapp_client.mascarar_telefone(destino),
            erro,
        )
        raise
    return resultado.message_id


def notificar_staff(mensagem: str) -> Optional[str]:
    """Notificador genérico de 1 parâmetro, via template
    `escalonamento_equipe` (3 variáveis — Meta rejeitaria com só 1
    parâmetro se chamado direto com envio real ativo; ver
    notificar_staff_escalonamento pro uso estruturado correto desse
    template). Mantido por compatibilidade (assinatura pública testada em
    tests/test_notificacoes_whatsapp.py) mas o A3 não usa mais esta função —
    ver notificar_staff_manutencao abaixo, que usa o template próprio de
    manutenção (checkup pós-WA-06/WA-08, Ponto 3).
    """
    return _enviar_template_staff(_TEMPLATE_ESCALONAMENTO_EQUIPE, [mensagem], operacao="notificar_staff")


def notificar_staff_escalonamento(
    protocolo: str,
    motivo: str,
    descricao: str,
    nome_inquilino: str = "",
    imovel_identificacao: str = "",
    telefone_inquilino: str = "",
) -> Optional[str]:
    """A5 estruturado: protocolo, motivo, descrição, e agora também
    nome/imóvel/telefone do inquilino — sem isso a equipe recebia a
    notificação sem saber PRA QUEM ligar de volta (ver
    docs/superpowers/plans/2026-09-03-correcoes-fluxo-escalonamento/02-...).
    Os 3 últimos têm default "" só para não quebrar quem já chamava esta
    função antes; `executar_escalonamento` (único chamador real) sempre
    passa os 6."""
    return _enviar_template_staff(
        _TEMPLATE_ESCALONAMENTO_EQUIPE,
        [
            protocolo,
            motivo,
            descricao,
            nome_inquilino or "não informado",
            imovel_identificacao or "não informado",
            telefone_inquilino or "não informado",
        ],
        operacao="notificar_staff_escalonamento",
    )


def notificar_staff_manutencao(parametros: list[str]) -> Optional[str]:
    """A3 estruturado (checkup pós-WA-06/WA-08, Ponto 3): `parametros` já
    vem pronto de app/tools/mensagens_manutencao.py::
    montar_parametros_notificacao_gestora, na ordem protocolo/imóvel/
    categoria/urgência/descrição do template `manutencao_equipe` — esta
    função só transporta, não reformata nada."""
    return _enviar_template_staff(
        _TEMPLATE_MANUTENCAO_EQUIPE, parametros, operacao="notificar_staff_manutencao"
    )
