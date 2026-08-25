"""Envio de mensagens do A2 — Cobrança.

WA-05: transporte real via app/tools/whatsapp_client.py (fundação/WA-01,
transporte HTTP/WA-02, botões e mídia/WA-03) — antes, todo envio real
(WHATSAPP_ACCESS_TOKEN configurado) caía num NotImplementedError, o que
quebrava o cron assim que alguém preenchesse o token. Com o kill switch
(WHATSAPP_ENVIO_ATIVO) desligado — padrão hoje — o comportamento não muda:
whatsapp_client.enviar_texto/enviar_template/enviar_botoes já caem em modo
simulado sozinhos (logam e devolvem sem chamada HTTP), então nada aqui
precisa checar o kill switch explicitamente.

WA-08: cobranças do cron e notificações proativas à gestão usam templates
estruturados. Os botões definidos pela WA-06 continuam carregando IDs
dinâmicos decodificáveis, agora como quick replies dos templates aprovados.
Somente a segunda etapa provisória de "Só uma delas" permanece interativa
livre até o novo fluxo de seleção direta ser aprovado e implementado.

WA-06: `notificar_fernanda_comprovante` e
`notificar_fernanda_pagamento_combinado` mandam botões nativos, com o `id`
de cada botão
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
from app.tools.whatsapp_message_policy import (
    BotaoTemplateQuickReply,
    MensagemTemplate,
    decidir_saida_para_contrato,
    enviar_saida,
)

logger = logging.getLogger(__name__)

# Limite de botões de uma interactive message da Meta (whatsapp_client.
# _MAX_BOTOES) — duplicado aqui só pra decidir ANTES de montar qualquer
# botão se notificar_pergunta_qual_charge_paga cabe no formato de botões ou
# precisa cair pra texto livre (ver docstring da função).
_MAX_CHARGES_BOTAO_QUAL_PAGA = 3

_TEMPLATE_COMPROVANTE_PARA_CONFERENCIA = "comprovante_para_conferencia"
_TEMPLATE_PAGAMENTO_COMBINADO = "pagamento_combinado"
_TEMPLATE_COMPROVANTE_SEM_CORRESPONDENCIA = "comprovante_sem_correspondencia"
_TEMPLATE_PAGAMENTO_CONFIRMADO = "pagamento_confirmado"


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


def _destino_staff(telefone: str) -> str:
    """Resolve o destino real sem exigir configuração no modo simulado."""
    if telefone or not whatsapp_client.envio_ativo():
        return telefone
    return whatsapp_client.telefone_staff()


def _formatar_valor(valor: float) -> str:
    formato_internacional = f"{valor:,.2f}"
    return formato_internacional.translate(str.maketrans({",": ".", ".": ","}))


def _formatar_valor_extraido(valor: float | None) -> str:
    if valor is None:
        return "não legível"
    return f"R$ {_formatar_valor(valor)}"


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
    """Template gerencial com quick replies Confirmar / Valor diverge."""
    destino = _destino_staff(telefone_fernanda)
    criterio = (
        "Correspondência identificada automaticamente pelo valor"
        if nota_deteccao_automatica
        else "Única cobrança em aberto"
    )
    mensagem = MensagemTemplate(
        nome=_TEMPLATE_COMPROVANTE_PARA_CONFERENCIA,
        parametros=(
            nome_inquilino,
            imovel_identificacao,
            _formatar_valor_extraido(valor_extraido),
            data_extraida or "não legível",
            _formatar_valor(valor_esperado),
            criterio,
        ),
        botoes=(
            BotaoTemplateQuickReply(
                payload=montar_button_id_confirmar(contract_id, charge_id)
            ),
            BotaoTemplateQuickReply(
                payload=montar_button_id_divergente(contract_id, charge_id)
            ),
        ),
    )
    _enviar_com_log(
        "notificar_fernanda_comprovante",
        destino,
        lambda: enviar_saida(destino, mensagem),
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
    """Template com "Cobre os dois" / "Só uma delas" quando o comprovante
    bate com a soma de duas ou mais charges.

    "Cobre os dois": `id` montado por montar_button_id_combinado_todos com
    TODAS as charge_ids envolvidas — sem ambiguidade, confirma tudo de
    uma vez (button_ids.py já assume múltiplos charge_id separados por
    vírgula nesse caso).

    "Só uma delas": só inicia a 1ª etapa do fluxo de duas etapas (ver
    docstring do módulo) — `id` montado por montar_button_id_escolher_parcial,
    que NÃO confirma nem reverte nenhuma charge sozinho. Só quando a
    segunda mensagem (notificar_pergunta_qual_charge_paga) for respondida
    é que alguma charge muda de status.

    Não existe "Valor diverge" nesta mensagem especificamente:
    montar_button_id_divergente só aceita UM charge_id — usá-lo aqui
    marcaria uma única charge como divergente e deixaria a(s) outra(s)
    permanentemente em 'aguardando_confirmacao' (a ação "Valor diverge" já
    tem seu botão de verdade em notificar_fernanda_comprovante, onde há
    sempre uma única charge)."""
    destino = _destino_staff(telefone_fernanda)
    linhas_charges = "\n".join(
        f"- {c['tipo'].capitalize()}: R$ {_formatar_valor(c['valor_esperado'])}"
        for c in charges_envolvidas
    )
    soma = sum(c["valor_esperado"] for c in charges_envolvidas)
    charge_ids = [c["id"] for c in charges_envolvidas]
    mensagem = MensagemTemplate(
        nome=_TEMPLATE_PAGAMENTO_COMBINADO,
        parametros=(
            nome_inquilino,
            imovel_identificacao,
            _formatar_valor_extraido(valor_extraido),
            data_extraida or "não legível",
            _formatar_valor(soma),
            linhas_charges,
        ),
        botoes=(
            BotaoTemplateQuickReply(
                payload=montar_button_id_combinado_todos(contract_id, charge_ids)
            ),
            BotaoTemplateQuickReply(
                payload=montar_button_id_escolher_parcial(contract_id, charge_ids)
            ),
        ),
    )
    _enviar_com_log(
        "notificar_fernanda_pagamento_combinado",
        destino,
        lambda: enviar_saida(destino, mensagem),
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
    resolve pela plataforma. Como o destinatário é staff, sempre usa
    template."""
    destino = _destino_staff(telefone_fernanda)
    linhas_charges = (
        "\n".join(
            f"- {c['tipo'].capitalize()}: R$ {_formatar_valor(c['valor_esperado'])}"
            for c in charges_em_aberto
        )
        if charges_em_aberto
        else "(nenhuma charge em aberto encontrada para este contrato)"
    )
    mensagem = MensagemTemplate(
        nome=_TEMPLATE_COMPROVANTE_SEM_CORRESPONDENCIA,
        parametros=(
            nome_inquilino,
            imovel_identificacao,
            _formatar_valor_extraido(valor_extraido),
            data_extraida or "não legível",
            linhas_charges,
        ),
    )
    _enviar_com_log(
        "notificar_fernanda_sem_match",
        destino,
        lambda: enviar_saida(destino, mensagem),
    )


def responder_confirmacao_pagamento(
    client_agente,
    telefone_whatsapp: str,
    nome_inquilino: str,
) -> None:
    """Resposta automática ao inquilino quando Fernanda confirma o
    pagamento. Texto livre somente com janela comprovadamente aberta; caso
    contrário usa o template específico ``pagamento_confirmado``."""
    texto = f"Recebemos seu comprovante, {nome_inquilino}. Pagamento confirmado, obrigado!"
    saida = decidir_saida_para_contrato(
        client_agente,
        reativa=True,
        texto=texto,
        template=MensagemTemplate(
            nome=_TEMPLATE_PAGAMENTO_CONFIRMADO,
            parametros=(nome_inquilino,),
        ),
    )
    _enviar_com_log(
        "responder_confirmacao_pagamento",
        telefone_whatsapp,
        lambda: enviar_saida(telefone_whatsapp, saida),
    )
