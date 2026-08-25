"""Envio de mensagens do A2 — Cobrança.

WA-05: transporte real via app/tools/whatsapp_client.py (fundação/WA-01,
transporte HTTP/WA-02, botões e mídia/WA-03) — antes, todo envio real
(WHATSAPP_ACCESS_TOKEN configurado) caía num NotImplementedError, o que
quebrava o cron assim que alguém preenchesse o token. Com o kill switch
(WHATSAPP_ENVIO_ATIVO) desligado — padrão hoje — o comportamento não muda:
whatsapp_client.enviar_texto/enviar_template/enviar_botoes já caem em modo
simulado sozinhos (logam e devolvem sem chamada HTTP), então nada aqui
precisa checar o kill switch explicitamente.

WA-08: `enviar_mensagem_cobranca` recebe agora um template estruturado por
estágio. Os fluxos de comprovante abaixo mantêm as assinaturas, botões e IDs
definidos pela WA-06 e serão integrados ao transporte de templates depois da
resolução do cherry-pick.

WA-06: `notificar_fernanda_comprovante` e
`notificar_fernanda_pagamento_combinado` agora mandam botões nativos de
verdade (`whatsapp_client.enviar_botoes`), com o `id` de cada botão
montado exclusivamente pelas funções `montar_button_id_*` de
app/agents/a2_cobranca/button_ids.py — nunca um id construído à mão aqui.
Isso é o que garante que o clique, do lado do webhook, é reconhecido por
`decodificar_button_id` (ver app/orchestrator/orchestrator.py::
rotear_clique_botao_a2). Por isso as duas funções agora exigem
contract_id (e charge_id, quando aplicável) como parâmetro — antes não
precisavam, porque só desenhavam rótulos de botão em texto.

"Só uma delas" (pagamento combinado parcial) — um clique sozinho nunca diz
QUAL charge foi de fato paga, então isso vira uma conversa em DUAS etapas
em vez de um botão só:

  1. `notificar_fernanda_pagamento_combinado` manda "Cobre os dois" e "Só
     uma delas". Clicar em "Só uma delas" não confirma nem reverte
     NENHUMA charge ainda — só decodifica pra ACAO_ESCOLHER_PARCIAL, que
     dispara `notificar_pergunta_qual_charge_paga` (abaixo).
  2. Essa segunda mensagem manda um botão por charge (ex: "Aluguel",
     "Água") — cada um já sem ambiguidade nenhuma, porque o clique agora
     diz exatamente qual charge é a paga. Só nesse ponto o webhook confirma
     a charge escolhida e devolve as demais pra 'pendente' (ver
     comprovante.py::marcar_apenas_uma_paga).

Continua sem suporte pra "Valor diverge" na mensagem de pagamento
combinado especificamente: montar_button_id_divergente só aceita UM
charge_id, e usá-lo ali marcaria uma única charge como divergente
deixando a(s) outra(s) presa em 'aguardando_confirmacao' — esse caso
ainda é resolvido escrevendo (ver corpo da mensagem).
"""

import logging

from app.agents.a2_cobranca.button_ids import (
    montar_button_id_combinado_parcial,
    montar_button_id_combinado_todos,
    montar_button_id_confirmar,
    montar_button_id_divergente,
    montar_button_id_escolher_parcial,
)
from app.tools import whatsapp_client
from app.tools.whatsapp_message_policy import MensagemTemplate, enviar_saida

logger = logging.getLogger(__name__)

# Limite de botões de uma interactive message da Meta (whatsapp_client.
# _MAX_BOTOES) — duplicado aqui só pra decidir ANTES de montar qualquer
# botão se notificar_pergunta_qual_charge_paga cabe no formato de botões ou
# precisa cair pra texto livre (ver docstring da função).
_MAX_CHARGES_BOTAO_QUAL_PAGA = 3

# Template genérico para as mensagens de cobrança do cron (D-5/D0/D+5/D+10/
# D+15) — um único parâmetro com o texto já montado por mensagens.py (regra
# desta task: não reescrever esse texto). O catálogo
# (docs/whatsapp/templates-meta.md) desenha 3 templates por estágio, com
# variáveis próprias (nome, valor, multa, juros...) — migrar pra eles exige
# expor esses campos separadamente em vez do texto já pronto que
# enviar_mensagem_cobranca recebe hoje; fica pra quando mensagens.py for
# reestruturado (WA-08).
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


def _enviar_com_log(operacao: str, telefone: str, enviar) -> None:
    """Chama `enviar` (uma lambda/closure sem argumentos, já fechada sobre
    os parâmetros reais do envio) e, se falhar, loga via _logar_falha_envio
    ANTES de repropagar. Toda função deste módulo que envia algo pelo
    whatsapp_client usa este helper — antes cada uma repetia o mesmo
    try/except-log-reraise na mão."""
    try:
        enviar()
    except Exception as erro:
        _logar_falha_envio(operacao, telefone, erro)
        raise

def enviar_mensagem_cobranca(
    telefone_whatsapp: str,
    mensagem: MensagemTemplate,
) -> None:
    """Envia a mensagem de cobrança D-5/D0/D+5/D+10/D+15 — disparada pelo
    cron diário, portanto sempre proativa e já estruturada como template."""
    try:
        enviar_saida(telefone_whatsapp, mensagem)
    except Exception as erro:
        _logar_falha_envio("enviar_mensagem_cobranca", telefone_whatsapp, erro)
        raise


def notificar_fernanda_comprovante(
    telefone_fernanda: str,
    contract_id: str,
    charge_id: str,
    nome_inquilino: str,
    imovel_identificacao: str,
    valor_extraido: float | None,
    data_extraida: str | None,
    valor_esperado: float,
    nota_deteccao_automatica: str | None = None,
) -> None:
    """DM para a Fernanda (não o grupo) com os dois botões nativos
    Confirmar / Valor diverge (WA-06: interactive message de verdade — o
    `id` de cada botão é montado por button_ids.montar_button_id_*, único
    jeito de o clique ser reconhecido depois por decodificar_button_id).
    `nota_deteccao_automatica` é usada quando havia mais de uma charge em
    aberto e o sistema resolveu qual delas sozinho, por valor batendo
    dentro da margem — ver comprovante.py:_resolver_charge_e_notificar.
    Disparada de dentro do webhook (comprovante recebido)."""
    nota = f"\n\n{nota_deteccao_automatica}" if nota_deteccao_automatica else ""
    corpo = (
        f"Novo comprovante recebido\n\n"
        f"Inquilino: {nome_inquilino}\n"
        f"Imóvel: {imovel_identificacao}\n\n"
        f"Valor identificado: R$ {valor_extraido if valor_extraido is not None else 'não legível'}\n"
        f"Data identificada: {data_extraida or 'não legível'}\n"
        f"Valor esperado (contrato): R$ {valor_esperado:.2f}"
        f"{nota}"
    )
    botoes = [
        {"id": montar_button_id_confirmar(contract_id, charge_id), "titulo": "Confirmar"},
        {"id": montar_button_id_divergente(contract_id, charge_id), "titulo": "Valor diverge"},
    ]
    _enviar_com_log(
        "notificar_fernanda_comprovante",
        telefone_fernanda,
        lambda: whatsapp_client.enviar_botoes(telefone_fernanda, corpo, botoes),
    )


def notificar_fernanda_pagamento_combinado(
    telefone_fernanda: str,
    contract_id: str,
    nome_inquilino: str,
    imovel_identificacao: str,
    valor_extraido: float | None,
    data_extraida: str | None,
    charges_envolvidas: list[dict],
) -> None:
    """DM com 2 botões nativos ("Cobre os dois" / "Só uma delas") quando o
    valor do comprovante bate com a SOMA de duas (ou mais) charges em
    aberto.

    "Cobre os dois": `id` montado por montar_button_id_combinado_todos com
    TODAS as charge_ids envolvidas — sem ambiguidade, confirma tudo de
    uma vez (button_ids.py já assume múltiplos charge_id separados por
    vírgula nesse caso).

    "Só uma delas": só inicia a 1ª etapa do fluxo de duas etapas (ver
    docstring do módulo) — `id` montado por montar_button_id_escolher_parcial,
    que NÃO confirma nem reverte nenhuma charge sozinho. Só quando a
    segunda mensagem (notificar_pergunta_qual_charge_paga) for respondida
    é que alguma charge muda de status.

    Ainda NÃO tem "Valor diverge" NESTA mensagem especificamente:
    montar_button_id_divergente só aceita UM charge_id — usá-lo aqui
    marcaria uma única charge como divergente e deixaria a(s) outra(s)
    permanentemente em 'aguardando_confirmacao' (a ação "Valor diverge" já
    tem seu botão de verdade em notificar_fernanda_comprovante, onde há
    sempre uma única charge). Esse caso (valor que na real não bate com
    nada) o corpo da mensagem orienta a Fernanda a resolver manualmente —
    sem alterar nenhuma charge automaticamente. Disparada de dentro do
    webhook (comprovante recebido)."""
    linhas_charges = "\n".join(
        f"- {c['tipo'].capitalize()}: R$ {c['valor_esperado']:.2f}" for c in charges_envolvidas
    )
    soma = sum(c["valor_esperado"] for c in charges_envolvidas)
    corpo = (
        f"Comprovante recebido — possível pagamento combinado\n\n"
        f"Inquilino: {nome_inquilino}\n"
        f"Imóvel: {imovel_identificacao}\n\n"
        f"Valor identificado: R$ {valor_extraido if valor_extraido is not None else 'não legível'}\n"
        f"Data identificada: {data_extraida or 'não legível'}\n\n"
        f"Charges em aberto que juntas somam esse valor (R$ {soma:.2f}):\n{linhas_charges}\n\n"
        f"Se o valor na real não bater com nada disso, responda por aqui pra resolver "
        f"manualmente — não confirme automaticamente nesse caso."
    )
    charge_ids = [c["id"] for c in charges_envolvidas]
    botoes = [
        {
            "id": montar_button_id_combinado_todos(contract_id, charge_ids),
            "titulo": "Cobre os dois",
        },
        {
            "id": montar_button_id_escolher_parcial(contract_id, charge_ids),
            "titulo": "Só uma delas",
        },
    ]
    _enviar_com_log(
        "notificar_fernanda_pagamento_combinado",
        telefone_fernanda,
        lambda: whatsapp_client.enviar_botoes(telefone_fernanda, corpo, botoes),
    )


def notificar_pergunta_qual_charge_paga(
    telefone_fernanda: str, contract_id: str, charges: list[dict]
) -> None:
    """2ª etapa do fluxo de pagamento combinado parcial (WA-06) — disparada
    só depois que a Fernanda já apertou "Só uma delas" na 1ª mensagem (ver
    notificar_fernanda_pagamento_combinado). Um botão por charge (`charges`
    é `[{"id":..., "tipo":...}, ...]`), com título = tipo capitalizado (ex:
    "Aluguel", "Água") — cada clique agora é inequívoco: diz exatamente
    qual charge foi a paga.

    `id` de cada botão é montado por montar_button_id_combinado_parcial,
    com a PRÓPRIA charge daquele botão como paga e todas as outras
    (`charges`, exceto ela) como charge_ids_restantes — quem decodificar
    do outro lado (comprovante.py::marcar_apenas_uma_paga) já sabe
    confirmar uma e reverter o resto pra 'pendente'.

    Limite de 3 botões da Meta = limite de 3 charges combinadas nesta
    etapa. Se `charges` tiver mais que isso (pagamento combinado de 4+
    cobranças — hoje improvável, mas não impossível), NÃO tenta montar os
    botões: `whatsapp_client.enviar_botoes` rejeitaria a chamada inteira
    (WhatsAppConteudoInvalidoError), e isso deixaria a Fernanda sem
    NENHUMA mensagem de acompanhamento — as charges ficariam presas em
    'aguardando_confirmacao' pra sempre. Em vez disso, cai pra texto livre
    listando as charges, pedindo pra ela responder qual foi."""
    if len(charges) > _MAX_CHARGES_BOTAO_QUAL_PAGA:
        linhas = "\n".join(f"- {c['tipo'].capitalize()} (id: {c['id']})" for c in charges)
        texto = (
            f"Qual das cobranças foi realmente paga? São {len(charges)} — mais do que cabe "
            f"em botões (limite de {_MAX_CHARGES_BOTAO_QUAL_PAGA} da Meta), responda por aqui "
            f"dizendo qual delas:\n{linhas}"
        )
        _enviar_com_log(
            "notificar_pergunta_qual_charge_paga",
            telefone_fernanda,
            lambda: whatsapp_client.enviar_texto(telefone_fernanda, texto),
        )
        return

    ids_todas = [c["id"] for c in charges]
    corpo = "Qual das cobranças foi realmente paga?"
    botoes = [
        {
            "id": montar_button_id_combinado_parcial(
                contract_id, charge["id"], [cid for cid in ids_todas if cid != charge["id"]]
            ),
            "titulo": charge["tipo"].capitalize(),
        }
        for charge in charges
    ]
    _enviar_com_log(
        "notificar_pergunta_qual_charge_paga",
        telefone_fernanda,
        lambda: whatsapp_client.enviar_botoes(telefone_fernanda, corpo, botoes),
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
    _enviar_com_log(
        "notificar_fernanda_sem_match",
        telefone_fernanda,
        lambda: whatsapp_client.enviar_texto(telefone_fernanda, texto),
    )


def responder_confirmacao_pagamento(telefone_whatsapp: str, nome_inquilino: str) -> None:
    """Resposta automática ao inquilino quando Fernanda confirma o
    pagamento — disparada de dentro do processamento do clique de botão
    dela (webhook): texto livre, mesmo padrão de resposta ao inquilino da
    WA-04."""
    texto = f"Recebemos seu comprovante, {nome_inquilino}. Pagamento confirmado, obrigado!"
    _enviar_com_log(
        "responder_confirmacao_pagamento",
        telefone_whatsapp,
        lambda: whatsapp_client.enviar_texto(telefone_whatsapp, texto),
    )
