"""Envio de mensagens do A2 — Cobrança.

WA-05: transporte real via app/tools/whatsapp_client.py (fundação/WA-01,
transporte HTTP/WA-02, botões e mídia/WA-03) — antes, todo envio real
(WHATSAPP_ACCESS_TOKEN configurado) caía num NotImplementedError, o que
quebrava o cron assim que alguém preenchesse o token. Com o kill switch
(WHATSAPP_ENVIO_ATIVO) desligado — padrão hoje — o comportamento não muda:
whatsapp_client.enviar_texto/enviar_template já cai em modo simulado
sozinho (loga e devolve sem chamada HTTP), então nada aqui precisa checar
o kill switch explicitamente.

Reativo vs proativo (decisão desta task; a janela de 24h completa da Meta
fica pra WA-08): `enviar_mensagem_cobranca` é disparada pelo cron diário
(app/agents/a2_cobranca/cobranca.py), sem nenhuma mensagem recente do
inquilino no meio — vai como TEMPLATE. As demais quatro funções abaixo são
sempre disparadas de dentro do processamento de um webhook (comprovante
recebido, clique de confirmação) — vão como TEXTO LIVRE.

`notificar_fernanda_comprovante` e `notificar_fernanda_pagamento_combinado`
ainda mandam o texto com os botões representados como rótulos entre
colchetes (ex: "[ Confirmar ]   [ Valor diverge ]"), exatamente como antes
— NÃO viram uma interactive message real (`whatsapp_client.enviar_botoes`,
já disponível desde a WA-03) nesta task, porque isso exige contract_id e
charge_id pra montar o `id` do botão (app/agents/a2_cobranca/button_ids.py)
e essas duas funções não recebem esses parâmetros hoje — mudar a
assinatura pra isso é decisão da WA-06, junto da decodificação do clique.
"""

import logging

from app.tools import whatsapp_client

logger = logging.getLogger(__name__)

# Template genérico para as mensagens de cobrança do cron (D-5/D0/D+5/D+10/
# D+15) — um único parâmetro com o texto já montado por mensagens.py (regra
# desta task: não reescrever esse texto). O catálogo
# (docs/whatsapp/templates-meta.md) desenha 3 templates por estágio, com
# variáveis próprias (nome, valor, multa, juros...) — migrar pra eles exige
# expor esses campos separadamente em vez do texto já pronto que
# enviar_mensagem_cobranca recebe hoje; fica pra quando mensagens.py for
# reestruturado (WA-08).
_TEMPLATE_COBRANCA_MENSAGEM = "cobranca_mensagem"


def _logar_falha_envio(operacao: str, telefone: str, erro: Exception) -> None:
    """Log explícito de falha, com destino mascarado — chamado ANTES de
    repropagar a exceção em toda função deste módulo, pra nunca depender só
    de quem chama (cron, webhook) logar a falha por fora."""
    logger.error(
        "whatsapp_client: falha ao enviar (operacao=%s telefone=%s): %s",
        operacao,
        whatsapp_client.mascarar_telefone(telefone),
        erro,
    )


def enviar_mensagem_cobranca(telefone_whatsapp: str, texto: str) -> None:
    """Envia a mensagem de cobrança D-5/D0/D+5/D+10/D+15 — disparada pelo
    cron diário, portanto proativa (não há mensagem recente do inquilino
    nesta janela): transporta como template."""
    try:
        whatsapp_client.enviar_template(telefone_whatsapp, _TEMPLATE_COBRANCA_MENSAGEM, [texto])
    except Exception as erro:
        _logar_falha_envio("enviar_mensagem_cobranca", telefone_whatsapp, erro)
        raise


def notificar_fernanda_comprovante(
    telefone_fernanda: str,
    nome_inquilino: str,
    imovel_identificacao: str,
    valor_extraido: float | None,
    data_extraida: str | None,
    valor_esperado: float,
    nota_deteccao_automatica: str | None = None,
) -> None:
    """DM para a Fernanda (não o grupo) com os dois botões nativos
    representados como texto (Confirmar / Valor diverge — ver docstring do
    módulo sobre por que ainda não é uma interactive message real).
    `nota_deteccao_automatica` é usada quando havia mais de uma charge em
    aberto e o sistema resolveu qual delas sozinho, por valor batendo
    dentro da margem — ver comprovante.py:_resolver_charge_e_notificar.
    Disparada de dentro do webhook (comprovante recebido): texto livre."""
    nota = f"\n\n{nota_deteccao_automatica}" if nota_deteccao_automatica else ""
    texto = (
        f"Novo comprovante recebido\n\n"
        f"Inquilino: {nome_inquilino}\n"
        f"Imóvel: {imovel_identificacao}\n\n"
        f"Valor identificado: R$ {valor_extraido if valor_extraido is not None else 'não legível'}\n"
        f"Data identificada: {data_extraida or 'não legível'}\n"
        f"Valor esperado (contrato): R$ {valor_esperado:.2f}"
        f"{nota}\n\n"
        f"[ Confirmar ]   [ Valor diverge ]"
    )
    try:
        whatsapp_client.enviar_texto(telefone_fernanda, texto)
    except Exception as erro:
        _logar_falha_envio("notificar_fernanda_comprovante", telefone_fernanda, erro)
        raise


def notificar_fernanda_pagamento_combinado(
    telefone_fernanda: str,
    nome_inquilino: str,
    imovel_identificacao: str,
    valor_extraido: float | None,
    data_extraida: str | None,
    charges_envolvidas: list[dict],
) -> None:
    """DM com 3 botões (representados como texto — mesma ressalva acima)
    quando o valor do comprovante bate com a SOMA de duas (ou mais) charges
    em aberto. Disparada de dentro do webhook: texto livre."""
    linhas_charges = "\n".join(
        f"- {c['tipo'].capitalize()}: R$ {c['valor_esperado']:.2f}" for c in charges_envolvidas
    )
    soma = sum(c["valor_esperado"] for c in charges_envolvidas)
    texto = (
        f"Comprovante recebido — possível pagamento combinado\n\n"
        f"Inquilino: {nome_inquilino}\n"
        f"Imóvel: {imovel_identificacao}\n\n"
        f"Valor identificado: R$ {valor_extraido if valor_extraido is not None else 'não legível'}\n"
        f"Data identificada: {data_extraida or 'não legível'}\n\n"
        f"Charges em aberto que juntas somam esse valor (R$ {soma:.2f}):\n{linhas_charges}\n\n"
        f"[ Cobre os dois ]   [ Só uma delas ]   [ Valor diverge ]"
    )
    try:
        whatsapp_client.enviar_texto(telefone_fernanda, texto)
    except Exception as erro:
        _logar_falha_envio("notificar_fernanda_pagamento_combinado", telefone_fernanda, erro)
        raise


def notificar_fernanda_sem_match(
    telefone_fernanda: str,
    nome_inquilino: str,
    imovel_identificacao: str,
    valor_extraido: float | None,
    data_extraida: str | None,
    charges_em_aberto: list[dict],
) -> None:
    """Usada quando o valor do comprovante não bate (dentro da margem) com
    nenhuma charge individual nem com a soma delas. Sem botões — Fernanda
    resolve pelo canal normal. Disparada de dentro do webhook: texto livre."""
    linhas_charges = (
        "\n".join(f"- {c['tipo'].capitalize()}: R$ {c['valor_esperado']:.2f}" for c in charges_em_aberto)
        if charges_em_aberto
        else "(nenhuma charge em aberto encontrada para este contrato)"
    )
    texto = (
        f"Comprovante recebido — não foi possível identificar automaticamente a que se refere\n\n"
        f"Inquilino: {nome_inquilino}\n"
        f"Imóvel: {imovel_identificacao}\n\n"
        f"Valor identificado: R$ {valor_extraido if valor_extraido is not None else 'não legível'}\n"
        f"Data identificada: {data_extraida or 'não legível'}\n\n"
        f"Charges em aberto no contrato:\n{linhas_charges}\n\n"
        f"O valor não bate com nenhuma delas nem com a soma — resolver manualmente."
    )
    try:
        whatsapp_client.enviar_texto(telefone_fernanda, texto)
    except Exception as erro:
        _logar_falha_envio("notificar_fernanda_sem_match", telefone_fernanda, erro)
        raise


def responder_confirmacao_pagamento(telefone_whatsapp: str, nome_inquilino: str) -> None:
    """Resposta automática ao inquilino quando Fernanda confirma o
    pagamento — disparada de dentro do processamento do clique de botão
    dela (webhook): texto livre, mesmo padrão de resposta ao inquilino da
    WA-04."""
    texto = f"Recebemos seu comprovante, {nome_inquilino}. Pagamento confirmado, obrigado!"
    try:
        whatsapp_client.enviar_texto(telefone_whatsapp, texto)
    except Exception as erro:
        _logar_falha_envio("responder_confirmacao_pagamento", telefone_whatsapp, erro)
        raise
