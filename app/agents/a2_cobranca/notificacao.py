"""Envio de mensagens do A2 — Cobrança.

Mesmo padrão do notificar_staff do A5: sem WHATSAPP_ACCESS_TOKEN configurado
(hoje é o caso), só loga o que seria enviado e retorna — não quebra o fluxo
de cobrança por causa de uma dependência externa que ainda não existe.
Quando as credenciais existirem, trocar o corpo por uma chamada real à Meta
Cloud API, mantendo a mesma assinatura.

notificar_fernanda_comprovante é a mais complexa das três: precisa de
mensagem interativa com 2 botões nativos (Confirmar / Valor diverge), que é
um formato específico da API do WhatsApp Business (não é texto livre) —
ainda não implementado nem quando o token existir, porque depende de decidir
o formato exato da interactive message e de como o webhook vai processar o
callback do botão (ver TODO em comprovante.py sobre o "ponto em aberto" de
timeout de 24h/48h, que também depende dessa peça existir).
"""

import logging
import os

logger = logging.getLogger(__name__)


def enviar_mensagem_cobranca(telefone_whatsapp: str, texto: str) -> None:
    """Envia (ou, por ora, loga) uma mensagem de cobrança D-5/D0/D+5/D+10/D+15."""
    if not os.environ.get("WHATSAPP_ACCESS_TOKEN"):
        logger.warning(
            "WhatsApp Business API ainda não configurada — mensagem de cobrança NÃO "
            "enviada para %s (ficou só neste log):\n%s",
            telefone_whatsapp,
            texto,
        )
        return
    raise NotImplementedError(
        "WHATSAPP_ACCESS_TOKEN já configurado, mas o envio real via Meta Cloud API "
        "ainda não foi implementado neste módulo."
    )


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
    (Confirmar / Valor diverge). `nota_deteccao_automatica` é usada quando
    havia mais de uma charge em aberto e o sistema resolveu qual delas
    sozinho, por valor batendo dentro da margem — ver
    comprovante.py:_processar_com_multiplas_charges_abertas. Formato de
    interactive message da Meta Cloud API ainda não implementado — ver
    docstring do módulo."""
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
    if not os.environ.get("WHATSAPP_ACCESS_TOKEN"):
        logger.warning(
            "WhatsApp Business API ainda não configurada — DM de comprovante NÃO enviada "
            "para Fernanda (%s). Conteúdo que seria enviado:\n%s",
            telefone_fernanda,
            texto,
        )
        return
    raise NotImplementedError(
        "Envio de interactive message com botões nativos ainda não implementado — "
        "formato específico da Meta Cloud API, distinto de texto livre."
    )


def notificar_fernanda_pagamento_combinado(
    telefone_fernanda: str,
    nome_inquilino: str,
    imovel_identificacao: str,
    valor_extraido: float | None,
    data_extraida: str | None,
    charges_envolvidas: list[dict],
) -> None:
    """DM com 3 botões quando o valor do comprovante bate com a SOMA de duas
    (ou mais) charges em aberto — ex: inquilino pagou aluguel + água juntos
    numa PIX só. Botões: 'Cobre os dois' / 'Só uma delas' / 'Valor diverge'.
    Formato de interactive message ainda não implementado (mesma lacuna de
    notificar_fernanda_comprovante)."""
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
    if not os.environ.get("WHATSAPP_ACCESS_TOKEN"):
        logger.warning(
            "WhatsApp Business API ainda não configurada — DM de pagamento combinado NÃO "
            "enviada para Fernanda (%s). Conteúdo que seria enviado:\n%s",
            telefone_fernanda,
            texto,
        )
        return
    raise NotImplementedError(
        "Envio de interactive message com 3 botões ainda não implementado."
    )


def notificar_fernanda_sem_match(
    telefone_fernanda: str,
    nome_inquilino: str,
    imovel_identificacao: str,
    valor_extraido: float | None,
    data_extraida: str | None,
    charges_em_aberto: list[dict],
) -> None:
    """Usada quando o valor do comprovante não bate (dentro da margem) com
    nenhuma charge individual nem com a soma delas — o sistema NÃO tenta
    adivinhar. Só informa a situação; sem botões de ação automática, porque
    não há nenhuma correspondência confiável pra propor. Fernanda resolve
    pelo canal normal, fora do fluxo automatizado (mesmo espírito do "Valor
    diverge" original: nenhuma notificação pro grupo, só pendência com
    ela)."""
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
    if not os.environ.get("WHATSAPP_ACCESS_TOKEN"):
        logger.warning(
            "WhatsApp Business API ainda não configurada — aviso de comprovante sem match "
            "NÃO enviado para Fernanda (%s). Conteúdo que seria enviado:\n%s",
            telefone_fernanda,
            texto,
        )
        return
    raise NotImplementedError(
        "Envio de mensagem informativa (sem botão) ainda não implementado."
    )


def responder_confirmacao_pagamento(telefone_whatsapp: str, nome_inquilino: str) -> None:
    """Resposta automática ao inquilino quando Fernanda confirma o pagamento."""
    texto = f"Recebemos seu comprovante, {nome_inquilino}. Pagamento confirmado, obrigado!"
    if not os.environ.get("WHATSAPP_ACCESS_TOKEN"):
        logger.warning(
            "WhatsApp Business API ainda não configurada — confirmação automática NÃO "
            "enviada para %s. Conteúdo que seria enviado:\n%s",
            telefone_whatsapp,
            texto,
        )
        return
    raise NotImplementedError(
        "WHATSAPP_ACCESS_TOKEN já configurado, mas o envio real via Meta Cloud API "
        "ainda não foi implementado neste módulo."
    )