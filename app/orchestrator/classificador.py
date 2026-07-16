"""Classificação de intenção — primeira etapa do orquestrador.

Recebe a mensagem do inquilino (e histórico recente, se houver) e devolve
qual agente (A1-A5) deve tratar a conversa, um motivo curto (texto livre,
não confundir com o `motivo` de escalations — ver nota abaixo) e a urgência.

Essa classificação é deliberadamente RASA: só decide o roteamento. A lógica
de negócio de cada agente (o que responder, que ação tomar) é
responsabilidade do próprio agente — inclusive o A5, que tem seu próprio
critério mais fino (app/agents/a5_escalonamento/criterios.py, 13 motivos
objetivos) pra decidir SE de fato escala e POR QUÊ. O `motivo` devolvido
aqui é só a justificativa da escolha de AGENTE, não o motivo de
escalonamento.
"""

from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

MODEL = "claude-sonnet-5"

AgenteDestino = Literal["A1", "A2", "A3", "A4", "A5"]
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
    "Agentes disponíveis:\n"
    "- A1 (Atendimento ao Inquilino): dúvidas gerais sobre o contrato, o imóvel, prazos, "
    "regras — perguntas de informação que o contrato provavelmente já responde, sem risco "
    "financeiro/jurídico associado.\n"
    "- A2 (Cobrança e Inadimplência): qualquer assunto sobre pagamento de aluguel/água, "
    "comprovantes, atraso, valores cobrados (sem ser pedido de desconto/renegociação — "
    "isso é A5).\n"
    "- A3 (Manutenção): problemas físicos no imóvel (elétrica, hidráulica, estrutural, "
    "pintura) que NÃO sejam risco grave ou emergência (isso é A5).\n"
    "- A4 (Gestão Contratual): renovação, reajuste, alterações de condições do contrato "
    "que não envolvam pedido de ação imediata com risco jurídico (isso é A5).\n"
    "- A5 (Escalonamento Humano): pedido explícito de humano; risco financeiro/jurídico "
    "alto (rescisão antecipada, desconto/renegociação, ameaça de advogado/Procon, pedido "
    "de sublocação, troca de fiador, óbito de fiador); risco de segurança/emergência real "
    "(estrutural grave, incêndio, alagamento); ação contra vizinho/condomínio; ou sinais "
    "de conversa em loop/frustração crescente. Na dúvida entre A5 e outro agente quando "
    "há risco financeiro, jurídico ou de segurança envolvido, prefira A5 — o próprio A5 "
    "decide com mais detalhe se de fato escala.\n\n"
    "urgencia: 'alta' para risco de segurança/emergência ou pedido explícito de humano; "
    "'media' para os demais casos de A5 e problemas de manutenção que incomodam o dia a "
    "dia; 'baixa' para dúvidas de informação (A1) e rotina de cobrança/gestão contratual."
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
