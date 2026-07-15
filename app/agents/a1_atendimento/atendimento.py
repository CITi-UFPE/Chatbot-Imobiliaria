"""Agente 1 — Atendimento ao Inquilino.

Responde perguntas diretas sobre o contrato de locação do inquilino (valor,
vencimento, vigência, cláusulas, garantia, histórico de atendimentos). Não
negocia nada e não decide critério de escalonamento sozinho — antes de
tentar responder, delega essa decisão pro A5
(app/agents/a5_escalonamento.avaliar_escalonamento), reaproveitando os
critérios já existentes em vez de duplicar lógica de escalonamento aqui.

Diferença de desenho em relação ao A5: lá, `avaliar_escalonamento` decide SE
chama uma tool numa única rodada (tool_choice="auto", mas sem loop, porque
a tool só serve pra registrar uma decisão). Aqui o A1 PRECISA dos dados do
contrato antes de poder responder qualquer coisa, então isto é um loop de
tool-use de verdade: o Claude pode chamar `buscar_dados_inquilino` e/ou
`consultar_historico` quantas vezes precisar até ter o que precisa pra
responder em texto puro.

Segurança (mesma doutrina do agent_auth.py e da Migration 004): as tools NÃO
recebem contract_id como parâmetro vindo do Claude, e as próprias RPCs do
Supabase (buscar_dados_inquilino, consultar_historico) também não recebem
contract_id como parâmetro — elas resolvem o contrato internamente via
agent_contract_id(), lendo o claim do JWT assinado por obter_client_agente().
O `contract_id` só existe do lado Python, no fechamento (closure) de
`responder_inquilino`, e serve apenas pra escolher QUAL client/token usar
(obter_client_agente(contract_id)) — nunca é enviado como argumento de RPC.
O modelo não tem, em nenhuma camada, a opção de pedir dado de outro contrato.

TODO (pendente de decisão de design, mesmo espírito das notas em
criterios.py): o critério 'sem_clausula' do A5 depende do resultado de
`buscar_dados_inquilino` (só dá pra saber que não há cláusula correspondente
DEPOIS de buscar os dados), mas a checagem de escalonamento abaixo roda
ANTES da busca, só com o texto da mensagem. Por ora o system prompt instrui
o A1 a avisar que vai verificar quando não encontrar cláusula, mas o
escalonamento formal (motivo=sem_clausula, protocolo gerado) não dispara
sozinho nesse caso — falta decidir se rodamos avaliar_escalonamento de novo
depois do tool-use, ou se o A1 chama executar_escalonamento diretamente com
motivo fixo quando detectar isso.
"""

import json
import logging

import anthropic

from app.agents.a1_atendimento.schemas import DadosInquilino, RegistroHistorico
from app.agents.a5_escalonamento import (
    AvaliacaoEscalonamento,
    avaliar_escalonamento,
    executar_escalonamento,
)
from app.orchestrator.agent_auth import obter_client_agente

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"

# Evita loop infinito se o modelo insistir em chamar tools sem nunca
# convergir pra uma resposta em texto — depois disso, respondemos com uma
# mensagem de fallback em vez de deixar o inquilino sem resposta nenhuma.
MAX_RODADAS_TOOL_USE = 4

TOOL_BUSCAR_DADOS = "buscar_dados_inquilino"
TOOL_CONSULTAR_HISTORICO = "consultar_historico"

SYSTEM_PROMPT = """Você é o Agente de Atendimento ao Inquilino de uma imobiliária, falando via WhatsApp.

## ESCOPO
Você responde APENAS perguntas diretas sobre o contrato de locação do inquilino desta
conversa — valor do aluguel, data de vencimento, endereço do imóvel, vigência do contrato,
forma de reajuste, garantias (caução ou fiador), cláusulas específicas, e histórico de
atendimentos/tickets já abertos.

Você NÃO negocia valores, prazos ou condições contratuais, não processa cobranças, e não
abre chamados de manutenção — isso é feito por outros agentes. Se identificar que é isso
que o inquilino quer, diga que vai encaminhar e não tente resolver sozinho.

## DADOS
Use a tool 'buscar_dados_inquilino' antes de responder qualquer pergunta factual sobre o
contrato. Nunca invente ou presuma valores. Se a tool não retornar o dado perguntado, diga
que vai verificar com a equipe — não afirme algo que não veio da tool.

## RAMIFICAÇÃO PF/PJ
O campo `tipo_locatario` retornado será "pf" ou "pj":
- pf: trate o inquilino pelo primeiro nome (campo `inquilino_nome`).
- pj: trate formalmente pela razão social/nome fantasia (`inquilino_nome`). Se
  `responsavel_contato_nome` estiver preenchido, é o nome da pessoa que normalmente fala
  em nome da empresa — pode usá-lo pra personalizar o tratamento, mas não existe nenhum
  dado que confirme "quem está mandando esta mensagem agora tem autoridade pra decidir
  algo" — para qualquer pedido de alteração (não apenas informação), o caso já deveria ter
  sido escalado antes de chegar até você.

Garantia (`garantia_tipo`) só tem dois valores possíveis: "fiador" (aí `fiador_nome` vem
preenchido) ou "caucao" (aí `garantia_valor` vem preenchido). Não existe "seguro-fiança"
nem "fiança bancária" no sistema — não mencione essas opções.

## CITAÇÃO DE CLÁUSULA
Sempre que a resposta se basear numa cláusula específica, cite o número exatamente como
veio em `clausulas[].numero_clausula`. Nunca invente um número que não veio da tool.
O campo `texto_clausula` é o texto jurídico ORIGINAL e completo — PARAFRASEIE o conteúdo em
linguagem simples de WhatsApp, não cole o texto bruto da cláusula na conversa.
Formato: "De acordo com a Cláusula 8ª do seu contrato, o reajuste é anual pelo índice
combinado." (não cite o texto_clausula literalmente).

## HISTÓRICO
Use 'consultar_historico' quando o inquilino perguntar sobre atendimentos anteriores ou
tickets já abertos.

## TOM
Respostas curtas e diretas, adequadas a WhatsApp, sem markdown pesado. Nunca revele que
você é uma IA "multiagente" nem explique arquitetura interna."""


def _tools_schema() -> list[dict]:
    return [
        {
            "name": TOOL_BUSCAR_DADOS,
            "description": (
                "Busca os dados estruturados do contrato do inquilino desta conversa: "
                "tipo_locatario ('pf' ou 'pj'), valor do aluguel, datas, garantia, e "
                "cláusulas com número/título/texto/categoria. Chame esta tool ANTES de "
                "responder qualquer pergunta factual sobre o contrato — nunca responda com "
                "um valor que não veio daqui. O contrato já está fixado pela sessão atual; "
                "não é possível buscar dados de outro contrato através desta tool."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "campos": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Opcional. Campos específicos a priorizar (ex: "
                            "['valor_aluguel', 'clausulas']). Se omitido, retorna tudo."
                        ),
                    }
                },
            },
        },
        {
            "name": TOOL_CONSULTAR_HISTORICO,
            "description": (
                "Consulta o histórico de manutenção, negociações de cobrança e "
                "escalonamentos anteriores do inquilino desta conversa. Chame quando o "
                "inquilino perguntar sobre um chamado, negociação ou caso já aberto "
                "anteriormente (ex: 'já abri um chamado sobre isso', 'e aquela negociação "
                "da multa?')."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "limite": {
                        "type": "integer",
                        "default": 10,
                        "description": "Número máximo de registros a retornar.",
                    },
                    "tipo": {
                        "type": "string",
                        "enum": ["todos", "manutencao", "cobranca", "escalonamento"],
                        "default": "todos",
                    },
                },
            },
        },
    ]


def _executar_buscar_dados_inquilino(contract_id: str, campos: list[str] | None = None) -> dict:
    # contract_id só escolhe QUAL client/token usar — a RPC em si não recebe
    # contract_id como argumento, ela resolve isso internamente via
    # agent_contract_id() lendo o claim do próprio JWT (ver migration
    # 006_a1_rpcs.sql — número final pendente de coordenação de merge).
    client = obter_client_agente(contract_id)
    resposta = client.rpc("buscar_dados_inquilino", {}).execute()
    dados = resposta.data or {}

    # valida contra o schema esperado ANTES de repassar pro modelo — se a
    # RPC mudar de formato no banco, isso deve quebrar aqui de forma
    # explícita, não virar um campo estranho que o Claude tenta interpretar.
    DadosInquilino.model_validate(dados)

    if campos:
        filtrado = {k: v for k, v in dados.items() if k in campos}
        return filtrado or dados
    return dados


def _executar_consultar_historico(
    contract_id: str, limite: int = 10, tipo: str = "todos"
) -> list[dict]:
    client = obter_client_agente(contract_id)
    resposta = client.rpc(
        "consultar_historico",
        {"p_limite": limite, "p_tipo": tipo},
    ).execute()
    registros = resposta.data or []
    for registro in registros:
        RegistroHistorico.model_validate(registro)
    return registros


def responder_inquilino(
    contract_id: str,
    mensagem_atual: str,
    historico_conversa: str = "",
    model: str = MODEL,
) -> str:
    """Ponto de entrada do A1, chamado pelo orquestrador depois que o roteador
    já decidiu que esta mensagem é um caso de atendimento sobre o contrato.

    Primeiro pergunta ao A5 se o caso deveria escalar (mesma função usada
    pelos outros agentes) — se sim, executa o escalonamento e devolve a
    resposta educada do A5, sem o A1 tentar responder o conteúdo. Isso evita
    o A1 "adivinhar" uma resposta pra algo fora do seu escopo (ex: pedido de
    desconto) antes de escalar.
    """
    avaliacao = avaliar_escalonamento(mensagem_atual, historico_conversa, model=model)
    if avaliacao is not None:
        executar_escalonamento(contract_id, avaliacao)
        return avaliacao.resposta_para_inquilino

    client = anthropic.Anthropic()

    texto_usuario = mensagem_atual
    if historico_conversa:
        texto_usuario = (
            f"Histórico recente da conversa:\n{historico_conversa}\n\n"
            f"Mensagem atual do inquilino:\n{mensagem_atual}"
        )

    messages: list[dict] = [{"role": "user", "content": texto_usuario}]

    for _ in range(MAX_RODADAS_TOOL_USE):
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=_tools_schema(),
            tool_choice={"type": "auto"},
            messages=messages,
        )

        blocos_tool_use = [b for b in response.content if b.type == "tool_use"]
        if not blocos_tool_use:
            return next((b.text for b in response.content if b.type == "text"), "")

        messages.append({"role": "assistant", "content": response.content})

        resultados_tool = []
        for bloco in blocos_tool_use:
            try:
                if bloco.name == TOOL_BUSCAR_DADOS:
                    resultado = _executar_buscar_dados_inquilino(
                        contract_id, bloco.input.get("campos")
                    )
                elif bloco.name == TOOL_CONSULTAR_HISTORICO:
                    resultado = _executar_consultar_historico(
                        contract_id,
                        bloco.input.get("limite", 10),
                        bloco.input.get("tipo", "todos"),
                    )
                else:
                    logger.warning("Tool desconhecida chamada pelo A1: %s", bloco.name)
                    resultado = {"erro": f"tool '{bloco.name}' não existe"}
            except Exception:
                logger.exception(
                    "Falha ao executar tool %s para o contrato %s", bloco.name, contract_id
                )
                resultado = {"erro": "falha ao consultar os dados, tente novamente"}

            resultados_tool.append(
                {
                    "type": "tool_result",
                    "tool_use_id": bloco.id,
                    "content": json.dumps(resultado, ensure_ascii=False, default=str),
                }
            )

        messages.append({"role": "user", "content": resultados_tool})

    # Loop estourou sem o Claude convergir pra uma resposta em texto. O
    # fallback escala de fato pelo mesmo caminho do A5, gerando protocolo em
    # `escalations` e notificando a staff.
    logger.warning(
        "A1 atingiu MAX_RODADAS_TOOL_USE (%s) sem convergir para texto — contrato %s. "
        "Escalando via A5.",
        MAX_RODADAS_TOOL_USE,
        contract_id,
    )
    avaliacao_fallback = AvaliacaoEscalonamento(
        motivo="loop_nao_resolvido",
        descricao=(
            "A1 não conseguiu gerar uma resposta em texto após esgotar as rodadas de "
            "tool-use disponíveis (possível loop de tool-calling ou dado inconsistente)."
        ),
        resposta_para_inquilino=(
            "Vou verificar isso com calma e te retorno em breve — já deixei registrado aqui."
        ),
    )
    executar_escalonamento(contract_id, avaliacao_fallback)
    return avaliacao_fallback.resposta_para_inquilino