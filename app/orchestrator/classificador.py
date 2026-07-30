"""Classificação de intenção — primeira etapa do orquestrador.

Recebe a mensagem do inquilino (e histórico recente, se houver) e devolve
qual agente deve tratar a conversa, um motivo curto (texto livre, não
confundir com o `motivo` de escalations — ver nota abaixo) e a urgência.

Essa classificação é deliberadamente RASA: só decide o roteamento. A lógica
de negócio de cada agente (o que responder, que ação tomar) é
responsabilidade do próprio agente — inclusive o A5, que tem seu próprio
critério mais fino (app/agents/a5_escalonamento/criterios.py, 13 motivos
objetivos) pra decidir SE de fato escala e POR QUÊ. O `motivo` devolvido
aqui é só a justificativa da escolha de AGENTE, não o motivo de
escalonamento.

IMPORTANTE — só A1/A3/A5 aparecem como destino possível daqui: A2 e A4
NUNCA respondem por texto, por desenho (A2 só reage a comprovante/clique de
botão; A4 só reage ao cron diário — ver app/orchestrator/orchestrator.py).
Antes desta versão, o schema permitia classificar como A2/A4 e a mensagem
caía num "agente ainda não implementado" — expondo jargão de arquitetura
pro inquilino E gerando uma resposta que na prática nunca resolvia nada,
porque não existe (nem vai existir) esse agente ouvindo texto do outro
lado. Removido o próprio VALOR do schema (não só orientação no prompt):
Claude estruturalmente não consegue mais devolver A2/A4 aqui, então esse
caminho morto deixou de existir. Qualquer assunto de cobrança/gestão
contratual que chegue por texto agora cai em A1 (se for informativo) ou A5
(se precisar mesmo de uma pessoa agindo).
"""

from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

MODEL = "claude-sonnet-5"

AgenteDestino = Literal["A1", "A3", "A5"]
Urgencia = Literal["alta", "media", "baixa"]


class ClassificacaoIntencao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agente: AgenteDestino = Field(description="Agente que deve tratar esta mensagem.")
    motivo: str = Field(
        description="Justificativa curta e objetiva da escolha do agente (texto livre)."
    )
    urgencia: Urgencia = Field(
        description="Urgência da mensagem — usada para priorizar (ex: fila do A3, "
        "notificação do A5)."
    )


TOOL_NAME = "classificar_mensagem"

SYSTEM_PROMPT = (
    "Você classifica mensagens de inquilinos recebidas via WhatsApp para decidir qual "
    f"agente especializado deve tratar a conversa. Use a tool '{TOOL_NAME}' SEMPRE, para "
    "toda mensagem recebida — a classificação é obrigatória, mesmo quando a mensagem "
    "parecer ambígua (escolha o agente mais provável).\n\n"
    "Agentes disponíveis (só estes três — não existe agente de texto para cobrança "
    "ativa nem para gestão contratual, ver detalhe abaixo):\n"
    "- A1 (Atendimento ao Inquilino): TODA dúvida ou aviso informativo sobre o contrato, o "
    "imóvel, prazos, regras, pagamento — inclui valor do aluguel, data de vencimento, "
    "onde/como pagar (chave Pix, dados bancários), perguntas HIPOTÉTICAS sobre "
    "consequências de atraso ('quanto fica de multa e juros se eu atrasar?'), aviso pontual "
    "de atraso sem pedido de desconto ('posso pagar amanhã?'), aviso informal de pagamento "
    "já feito sem anexar comprovante ('fiz o pix', 'já paguei'), e pedidos administrativos "
    "simples sobre o contrato (ex: 'manda o contrato pra eu assinar', 'me envia uma cópia') "
    "— para esses últimos o A1 apenas confirma que vai verificar com a equipe, não tenta "
    "executar a ação sozinho. Tudo isso é informação/aviso, sem risco financeiro/jurídico "
    "e sem exigir uma decisão humana imediata — diferente de pedido de desconto/renegociação "
    "ou de algo que só uma pessoa da equipe pode decidir (isso é A5).\n"
    "- A3 (Manutenção): problemas físicos no imóvel (elétrica, hidráulica, estrutural, "
    "pintura) que NÃO sejam risco grave ou emergência (isso é A5).\n"
    "- A5 (Escalonamento Humano): pedido explícito de humano; risco financeiro/jurídico "
    "alto (rescisão antecipada, desconto/renegociação, ameaça de advogado/Procon, pedido "
    "de sublocação, troca de fiador, óbito de fiador); risco de segurança/emergência real "
    "(estrutural grave, incêndio, alagamento); ação contra vizinho/condomínio; renovação ou "
    "reajuste que o inquilino queira NEGOCIAR (não só perguntar como funciona — isso é A1); "
    "ou sinais de conversa em loop/frustração crescente. Na dúvida entre A5 e A1 quando há "
    "risco financeiro, jurídico ou de segurança envolvido, prefira A5 — o próprio A5 decide "
    "com mais detalhe se de fato escala.\n\n"
    "Cobrança já em andamento (comprovante, decisão da Fernanda) e gestão contratual "
    "automática (alertas de renovação/reajuste) são tratadas por agentes que reagem a "
    "eventos específicos (imagem recebida, clique de botão, cron diário), nunca a texto "
    "livre do inquilino — por isso não aparecem aqui como destino.\n\n"
    "urgencia: 'alta' para risco de segurança/emergência ou pedido explícito de humano; "
    "'media' para os demais casos de A5 e problemas de manutenção que incomodam o dia a "
    "dia; 'baixa' para dúvidas/avisos informativos (A1)."
)


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Registra a classificação de roteamento da mensagem recebida.",
        "input_schema": ClassificacaoIntencao.model_json_schema(),
    }


def classificar_intencao(
    mensagem_atual: str, historico_conversa: str = "", model: str = MODEL
) -> ClassificacaoIntencao:
    """Classifica a mensagem atual (com histórico opcional) num agente, motivo e urgência.

    tool_choice é forçado (não "auto"): diferente do A5, aqui TODA mensagem
    precisa de uma classificação — não existe "não classificar".
    """
    client = anthropic.Anthropic()

    texto_usuario = mensagem_atual
    if historico_conversa:
        texto_usuario = (
            f"Histórico recente da conversa:\n{historico_conversa}\n\n"
            f"Mensagem atual do inquilino:\n{mensagem_atual}"
        )

    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        tools=[_tool_schema()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": texto_usuario}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise RuntimeError("Claude não retornou classificação de intenção.")

    return ClassificacaoIntencao.model_validate(tool_use.input)
