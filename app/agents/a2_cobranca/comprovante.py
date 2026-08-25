"""Agente 2 — leitura de comprovante por visão + resolução de qual(is)
charge(s) o comprovante cobre + fluxo de confirmação.

MUDANÇA DE DESENHO importante em relação à primeira versão: antes,
processar_comprovante_recebido exigia charge_id como parâmetro — ou seja,
alguém já tinha que saber de antemão qual cobrança a foto representava.
Isso não se sustenta quando o inquilino pode ter aluguel E água em aberto
ao mesmo tempo e manda uma foto sem dizer qual é qual. Agora a resolução do
charge_id acontece AQUI DENTRO, por valor, com fallback pra decisão manual
da Fernanda quando a correspondência não é confiável.

Regra de decisão (Caso A / Caso B), por ordem:
  1. Só 1 charge em aberto no contrato -> sem ambiguidade, segue igual antes.
  2. 2+ charges em aberto:
     a) valor do comprovante bate (dentro de margem) com o valor esperado
        de EXATAMENTE UMA delas -> atribui automaticamente a essa, mas ainda
        manda Confirmar/Valor diverge pra Fernanda, com nota de que foi
        detecção automática por valor.
     b) valor bate (dentro de margem) com a SOMA de todas -> pagamento
        combinado (ex: aluguel + água na mesma PIX). Notifica com 3 botões:
        Cobre os dois / Só uma delas / Valor diverge.
     c) não bate com nenhuma individual nem com a soma -> não tenta
        adivinhar. Notifica a Fernanda listando as charges em aberto, sem
        marcar nenhuma automaticamente, pra ela resolver manualmente (mesmo
        espírito do "Valor diverge" original: fica com ela, fora do fluxo
        automatizado, sem notificar o grupo).

MARGEM_TOLERANCIA_* abaixo são placeholders — não confirmados com o
negócio. Ajustar conforme necessário (ex: taxas de PIX/arredondamento que
fazem o valor do comprovante não bater centavo a centavo com o esperado).

PONTO EM ABERTO (copiado da doc, não resolvido aqui de propósito): o que
acontece se a Fernanda não responder à DM de confirmação em X tempo ainda
não está definido pelo negócio (sugestão da doc: lembrete em 24h,
escalonamento em 48h) — ver conversa anterior, não implementado.
"""

import logging

import anthropic

from app.agents.a2_cobranca.notificacao import (
    notificar_fernanda_comprovante,
    notificar_fernanda_pagamento_combinado,
    notificar_fernanda_sem_match,
    responder_confirmacao_pagamento,
)
from app.agents.a2_cobranca.schemas import ComprovanteExtraido
from app.orchestrator.agent_auth import obter_client_agente

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"

TOOL_NAME = "extrair_dados_comprovante"

# Placeholders de margem de tolerância — não confirmados com o negócio.
# Combinar as duas: tolera o MAIOR entre o valor absoluto e o percentual,
# pra funcionar bem tanto em valores baixos (água) quanto altos (aluguel).
MARGEM_TOLERANCIA_ABSOLUTA_REAIS = 15.0
MARGEM_TOLERANCIA_PERCENTUAL = 0.03  # 3%

STATUS_CHARGES_ABERTAS = ("pendente", "atrasado")

SYSTEM_PROMPT_COMPROVANTE = (
    "Você está analisando uma imagem ou PDF de comprovante de pagamento (transferência, "
    "PIX, boleto pago). Extraia o valor pago, a data do pagamento e o nome do "
    "beneficiário/favorecido, exatamente como aparecem na imagem. A data deve ser "
    "normalizada para o formato ISO 8601 (YYYY-MM-DD) — nunca devolva a data em formato "
    "livre, já que ela alimenta uma coluna 'date' no banco. Se algum campo não estiver "
    "legível, não existir na imagem, ou a data não puder ser determinada com confiança "
    "nesse formato, deixe como null — nunca invente um valor ou arrisque um formato "
    "incerto. Se a imagem não parecer um comprovante de pagamento (foto de outra coisa, "
    "documento cortado, ilegível), marque legivel=false e descreva o problema em "
    "observacoes."
)


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Registra os dados extraídos do comprovante de pagamento na imagem.",
        "input_schema": ComprovanteExtraido.model_json_schema(),
    }


def extrair_dados_comprovante(imagem_base64: str, media_type: str, model: str = MODEL) -> ComprovanteExtraido:
    """Chama a Claude API (visão) com a tool FORÇADA — diferente do A1/A5,
    aqui sempre queremos uma tentativa estruturada de extração, nunca uma
    resposta em texto livre sobre a imagem."""
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT_COMPROVANTE,
        tools=[_tool_schema()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image" if media_type.startswith("image/") else "document",
                        "source": {"type": "base64", "media_type": media_type, "data": imagem_base64},
                    },
                    {"type": "text", "text": "Extraia os dados deste comprovante de pagamento."},
                ],
            }
        ],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    return ComprovanteExtraido.model_validate(tool_use.input)


def _dentro_da_margem(valor_a: float, valor_b: float) -> bool:
    margem = max(MARGEM_TOLERANCIA_ABSOLUTA_REAIS, valor_b * MARGEM_TOLERANCIA_PERCENTUAL)
    return abs(valor_a - valor_b) <= margem


def _buscar_charges_abertas(client_agente, contract_id: str) -> list[dict]:
    resposta = (
        client_agente.table("charges")
        .select("id, tipo, valor_esperado")
        .eq("contract_id", contract_id)
        .in_("status", STATUS_CHARGES_ABERTAS)
        .execute()
    )
    return resposta.data or []


def _marcar_aguardando_confirmacao(client_agente, charge_id: str, extraido: ComprovanteExtraido) -> None:
    client_agente.rpc(
        "agent_update_charge_status",
        {
            "p_charge_id": charge_id,
            "p_status": "aguardando_confirmacao",
            "p_valor_identificado": extraido.valor_identificado,
            "p_data_identificada_comprovante": extraido.data_identificada,
        },
    ).execute()


def _resolver_charge_e_notificar(
    client_agente,
    contract_id: str,
    extraido: ComprovanteExtraido,
    dados_contrato: dict,
) -> None:
    """Implementa a regra de decisão Caso A / Caso B descrita no topo do
    módulo. Não devolve nada — cada ramo já cuida de marcar status (quando
    aplicável) e notificar a Fernanda com o formato de mensagem certo.

    PENDÊNCIA CONHECIDA (achada na revisão da WA-05, endereçar na WA-06,
    que já mexe neste arquivo pra ligar os botões de verdade): em cada
    ramo abaixo, _marcar_aguardando_confirmacao (grava no banco) roda
    ANTES da chamada notificar_fernanda_*. Hoje, se o envio falhar depois
    do banco já gravado, a exceção sobe sem tratamento e quem chama trata
    como falha total — perdendo a informação de que o status da charge já
    foi atualizado de verdade. Mesmo padrão do achado já corrigido em
    app/agents/a2_cobranca/cobranca.py::_processar_charge e
    app/agents/a5_escalonamento/escalonamento.py::executar_escalonamento."""
    telefone_fernanda = ""  # TODO: número/ID da Fernanda — não decidido nesta task
    nome = dados_contrato.get("inquilino_nome", "")
    imovel = dados_contrato.get("imovel_identificacao", "")

    charges_abertas = _buscar_charges_abertas(client_agente, contract_id)

    # Nenhuma charge em aberto — caso estranho o suficiente pra não tentar
    # automatizar nada, só avisar a Fernanda.
    if not charges_abertas:
        notificar_fernanda_sem_match(
            telefone_fernanda, nome, imovel,
            extraido.valor_identificado, extraido.data_identificada,
            charges_em_aberto=[],
        )
        return

    # Caso A — só 1 charge em aberto: sem ambiguidade.
    if len(charges_abertas) == 1:
        charge_unica = charges_abertas[0]
        _marcar_aguardando_confirmacao(client_agente, charge_unica["id"], extraido)
        notificar_fernanda_comprovante(
            telefone_fernanda, nome, imovel,
            extraido.valor_identificado, extraido.data_identificada,
            valor_esperado=charge_unica["valor_esperado"],
        )
        return

    # Caso B — 2+ charges em aberto: precisa decidir por valor.
    valor = extraido.valor_identificado
    if valor is None:
        # Sem valor extraído, não dá pra tentar casar nada — cai direto
        # pro caminho manual, listando as opções pra Fernanda decidir.
        notificar_fernanda_sem_match(
            telefone_fernanda, nome, imovel,
            None, extraido.data_identificada,
            charges_em_aberto=charges_abertas,
        )
        return

    matches_individuais = [c for c in charges_abertas if _dentro_da_margem(valor, c["valor_esperado"])]
    soma_total = sum(c["valor_esperado"] for c in charges_abertas)
    bate_com_soma = _dentro_da_margem(valor, soma_total)

    # B.a — bate com exatamente uma, e não bate (ambiguamente) com a soma.
    if len(matches_individuais) == 1 and not bate_com_soma:
        charge_match = matches_individuais[0]
        _marcar_aguardando_confirmacao(client_agente, charge_match["id"], extraido)
        notificar_fernanda_comprovante(
            telefone_fernanda, nome, imovel,
            extraido.valor_identificado, extraido.data_identificada,
            valor_esperado=charge_match["valor_esperado"],
            nota_deteccao_automatica=(
                f"Identificado automaticamente como {charge_match['tipo']}, baseado no "
                f"valor — confirma?"
            ),
        )
        return

    # B.b — bate com a soma de todas (pagamento combinado). Marca todas como
    # aguardando_confirmacao (tentativa) — se Fernanda escolher "Só uma
    # delas" depois, a outra precisa ser revertida manualmente por ela
    # (callback disso ainda não existe, mesma lacuna do restante do fluxo
    # de botão).
    if bate_com_soma:
        for c in charges_abertas:
            _marcar_aguardando_confirmacao(client_agente, c["id"], extraido)
        notificar_fernanda_pagamento_combinado(
            telefone_fernanda, nome, imovel,
            extraido.valor_identificado, extraido.data_identificada,
            charges_envolvidas=charges_abertas,
        )
        return

    # B.c — não bate com nenhuma individual nem com a soma. Não tenta
    # adivinhar; não marca status em nenhuma charge.
    notificar_fernanda_sem_match(
        telefone_fernanda, nome, imovel,
        extraido.valor_identificado, extraido.data_identificada,
        charges_em_aberto=charges_abertas,
    )


def processar_comprovante_recebido(contract_id: str, imagem_base64: str, media_type: str) -> None:
    """Ponto de entrada chamado pelo orquestrador quando o inquilino manda
    uma foto/PDF de comprovante. NÃO recebe mais charge_id — a resolução de
    qual(is) charge(s) o comprovante cobre acontece internamente (ver
    _resolver_charge_e_notificar)."""
    extraido = extrair_dados_comprovante(imagem_base64, media_type)
    client_agente = obter_client_agente(contract_id)

    if not extraido.legivel:
        logger.warning(
            "Comprovante ilegível para contrato %s: %s", contract_id, extraido.observacoes
        )
        # Não muda status de charge nenhuma — o inquilino pode tentar de
        # novo. Aviso automático "não consegui ler" fica fora do escopo
        # desta task, fácil de adicionar depois via notificacao.py.
        return

    dados_contrato = client_agente.rpc("buscar_dados_cobranca_contrato", {}).execute().data or {}
    _resolver_charge_e_notificar(client_agente, contract_id, extraido, dados_contrato)


def confirmar_pagamento(contract_id: str, charge_id: str) -> None:
    """Chamado quando Fernanda aperta 'Confirmar'. O parsing do callback do
    botão em si (webhook recebendo o clique) ainda não existe — esta função
    já está pronta pra ser chamada assim que essa peça for construída."""
    client_agente = obter_client_agente(contract_id)

    resposta_charge = (
        client_agente.table("charges")
        .select("data_identificada_comprovante")
        .eq("id", charge_id)
        .single()
        .execute()
    )
    data_identificada = (resposta_charge.data or {}).get("data_identificada_comprovante")

    client_agente.rpc(
        "agent_update_charge_status",
        {
            "p_charge_id": charge_id,
            "p_status": "confirmado",
            # data_pagamento só é preenchida aqui, na confirmação humana —
            # copiada da leitura automática (data_identificada_comprovante),
            # gravada lá atrás em processar_comprovante_recebido. Se a visão
            # não conseguiu ler a data (None), data_pagamento também fica
            # None — não inventamos "hoje" como substituto.
            "p_data_pagamento": data_identificada,
        },
    ).execute()

    dados_contrato = client_agente.rpc("buscar_dados_cobranca_contrato", {}).execute().data or {}
    responder_confirmacao_pagamento(
        telefone_whatsapp=dados_contrato.get("telefone_whatsapp", ""),
        nome_inquilino=dados_contrato.get("inquilino_nome", ""),
    )


def marcar_valor_divergente(contract_id: str, charge_id: str) -> None:
    """Chamado quando Fernanda aperta 'Valor diverge'. Por design (ver doc):
    fica pendente com ela mesma, SEM notificar o grupo — ela resolve pelo
    canal normal, fora do fluxo automatizado."""
    client_agente = obter_client_agente(contract_id)
    client_agente.rpc(
        "agent_update_charge_status",
        {"p_charge_id": charge_id, "p_status": "divergente"},
    ).execute()


def confirmar_pagamento_combinado(contract_id: str, charge_ids: list[str]) -> None:
    """Chamado quando Fernanda aperta 'Cobre os dois' — na DM de pagamento
    combinado (ver notificar_fernanda_pagamento_combinado), confirmando que
    o valor do comprovante realmente cobre TODAS as charges listadas (ex:
    aluguel + água pagos juntos numa PIX só). Confirma cada uma
    individualmente, copiando a própria data_identificada_comprovante (já
    gravada em _marcar_aguardando_confirmacao pra todas elas, no momento em
    que o comprovante foi recebido)."""
    client_agente = obter_client_agente(contract_id)

    for charge_id in charge_ids:
        resposta_charge = (
            client_agente.table("charges")
            .select("data_identificada_comprovante")
            .eq("id", charge_id)
            .single()
            .execute()
        )
        data_identificada = (resposta_charge.data or {}).get("data_identificada_comprovante")

        client_agente.rpc(
            "agent_update_charge_status",
            {
                "p_charge_id": charge_id,
                "p_status": "confirmado",
                "p_data_pagamento": data_identificada,
            },
        ).execute()

    dados_contrato = client_agente.rpc("buscar_dados_cobranca_contrato", {}).execute().data or {}
    responder_confirmacao_pagamento(
        telefone_whatsapp=dados_contrato.get("telefone_whatsapp", ""),
        nome_inquilino=dados_contrato.get("inquilino_nome", ""),
    )


def marcar_apenas_uma_paga(
    contract_id: str, charge_id_paga: str, charge_ids_restantes: list[str]
) -> None:
    """Chamado quando Fernanda aperta 'Só uma delas' — o comprovante NÃO
    cobre todas as charges que tinham sido marcadas como
    aguardando_confirmacao no pagamento combinado; só uma foi paga de fato.

    PONTO EM ABERTO: o botão 'Só uma delas', sozinho, não diz QUAL charge é
    a paga — falta uma interação adicional (Fernanda especificar qual,
    provavelmente por uma lista de opções ou resposta de texto), que ainda
    não foi desenhada nem implementada. Esta função já assume que
    charge_id_paga chega resolvido por quem a chama; só executa a ação de
    banco (confirmar a paga, reverter as demais).

    As demais voltam para status='pendente' (não 'atrasado' direto) — o
    próximo cron diário recalcula dias_atraso do zero a partir da data real
    (não confia em valor salvo, ver cobranca.py:_processar_charge), então
    se ainda estiverem de fato atrasadas, o status correto é restabelecido
    sozinho na próxima execução."""
    client_agente = obter_client_agente(contract_id)

    resposta_charge = (
        client_agente.table("charges")
        .select("data_identificada_comprovante")
        .eq("id", charge_id_paga)
        .single()
        .execute()
    )
    data_identificada = (resposta_charge.data or {}).get("data_identificada_comprovante")

    client_agente.rpc(
        "agent_update_charge_status",
        {
            "p_charge_id": charge_id_paga,
            "p_status": "confirmado",
            "p_data_pagamento": data_identificada,
        },
    ).execute()

    for charge_id in charge_ids_restantes:
        client_agente.rpc(
            "agent_update_charge_status",
            {"p_charge_id": charge_id, "p_status": "pendente"},
        ).execute()

    dados_contrato = client_agente.rpc("buscar_dados_cobranca_contrato", {}).execute().data or {}
    responder_confirmacao_pagamento(
        telefone_whatsapp=dados_contrato.get("telefone_whatsapp", ""),
        nome_inquilino=dados_contrato.get("inquilino_nome", ""),
    )