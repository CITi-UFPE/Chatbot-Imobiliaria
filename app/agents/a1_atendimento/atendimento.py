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

RESOLVIDO (era TODO): o critério 'sem_clausula' do A5 depende do resultado de
`buscar_dados_inquilino` (só dá pra saber que não há cláusula correspondente
DEPOIS de buscar os dados), então a checagem de escalonamento no início de
`responder_inquilino` (que roda ANTES da busca, só com o texto da mensagem)
não cobre esse caso. Resolvido com uma terceira tool, `escalar_sem_clausula`
— o Claude a chama explicitamente quando `buscar_dados_inquilino` não trouxe
nada relevante pra pergunta, em vez de só responder em texto que não achou.
Isso reaproveita o mesmo loop de tool-use já existente (sem chamada extra à
API) e segue o mesmo padrão do fallback de MAX_RODADAS_TOOL_USE abaixo:
monta a AvaliacaoEscalonamento com motivo fixo e chama executar_escalonamento
diretamente, sem passar por avaliar_escalonamento de novo.
"""

import json
import logging
from datetime import date

import anthropic

from app.agents.a1_atendimento.schemas import DadosInquilino, RegistroHistorico
from app.tools.calculo_reajuste import INDICES_COM_CALCULO_AUTOMATICO, proximo_aniversario_contrato
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
TOOL_ESCALAR_SEM_CLAUSULA = "escalar_sem_clausula"

SYSTEM_PROMPT = """Você é o Agente de Atendimento ao Inquilino de uma imobiliária, falando via WhatsApp.

## ESCOPO
Você responde APENAS perguntas diretas sobre o contrato de locação do inquilino desta
conversa — valor do aluguel, data de vencimento, endereço do imóvel, vigência do contrato,
forma de reajuste, garantias (caução ou fiador), cláusulas específicas, e histórico de
atendimentos/tickets já abertos.

Você NÃO negocia valores, prazos ou condições contratuais, não processa cobranças, e não
abre chamados de manutenção — isso é feito por outros agentes. Se identificar que é isso
que o inquilino quer, diga que vai encaminhar e não tente resolver sozinho.

## SAUDAÇÃO
Se a mensagem do inquilino for APENAS uma saudação ou abertura social, sem nenhum pedido ou
pergunta concreta junto (ex: "oi", "oi, tudo bem?", "bom dia", "boa tarde!") — isso é uma
EXCEÇÃO ao ESCOPO acima: responda de forma natural, breve e cordial, sem chamar nenhuma tool
(não há dado nenhum pra buscar só pra cumprimentar alguém) e sem tratar a mensagem como
fora do seu escopo. Varie o tom entre conversas — não repita sempre a mesma frase.
Se a saudação vier acompanhada de um pedido ou pergunta real (ex: "oi, quanto é o
aluguel?"), responda o pedido normalmente seguindo o resto deste prompt; a saudação em si
não muda nada. O classificador do orquestrador (app/orchestrator/classificador.py) já
identifica esse caso e te encaminha a mensagem em vez de tratá-la como fora de escopo — a
resposta de fato acontece aqui, gerada por você, não por um texto fixo.

## DADOS
Use a tool 'buscar_dados_inquilino' antes de responder qualquer pergunta factual sobre o
contrato. Nunca invente ou presuma valores. Se, depois de consultar, não houver cláusula
correspondente à pergunta do inquilino, NÃO responda diretamente que "não encontrou" — chame a
tool 'escalar_sem_clausula' em vez disso. Isso registra o caso formalmente para a equipe avaliar
se é uma lacuna real do contrato, e você recebe de volta a mensagem certa para o inquilino.

## RAMIFICAÇÃO PF/PJ
O campo `tipo_locatario` retornado será "pf" ou "pj":
- pf: trate o inquilino pelo primeiro nome (campo `inquilino_nome`).
- pj: trate formalmente pela razão social/nome fantasia (`inquilino_nome`). Se
  `responsavel_contato_nome` estiver preenchido, é o nome da pessoa que normalmente fala
  em nome da empresa — pode usá-lo pra personalizar o tratamento, mas não existe nenhum
  dado que confirme "quem está mandando esta mensagem agora tem autoridade pra decidir
  algo" — para qualquer pedido de alteração (não apenas informação), o caso já deveria ter
  sido escalado antes de chegar até você.

Garantia (`garantia_tipo`) tem três valores possíveis: "fiador" (aí `fiador_nome` vem
preenchido), "caucao" (depósito retido à parte, `garantia_valor` vem preenchido) ou
"aluguel_antecipado" (sem fiador nem depósito retido — o inquilino pagou meses de aluguel
adiantados como garantia, ex: 1º + último mês; `garantia_valor` traz o total pago
adiantado). Não existe "seguro-fiança" nem "fiança bancária" no sistema — não mencione
essas opções.

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

## PROJEÇÃO DE ENCARGOS POR ATRASO
Se o inquilino perguntar, de forma hipotética/informativa, quanto ficaria devendo caso
atrase o pagamento (ex: "quanto fica de multa e juros se eu atrasar?") — diferente de uma
cobrança que já está em andamento, isso NÃO é escalonamento nem assunto de outro agente,
responda você mesmo usando 'multa_moratoria_percentual' e 'juros_moratorio_mensal' de
'buscar_dados_inquilino'. Os dois campos são FRAÇÃO, não percentual inteiro (0.01 = 1%).
Calcule assim:
- Multa: incide UMA VEZ sobre o valor do aluguel, não é proporcional aos dias de atraso.
  valor_multa = valor_aluguel * multa_moratoria_percentual.
- Juros: proporcional aos dias de atraso, considerando mês de 30 dias.
  valor_juros = valor_aluguel * juros_moratorio_mensal * (dias_de_atraso / 30).
Se o inquilino não especificar quantos dias de atraso, pergunte ou dê o exemplo com um
período razoável (ex: 5, 10 dias). Se 'multa_moratoria_percentual' vier nulo, não invente
um valor — diga que não há multa moratória definida no contrato (ou, se a pergunta depender
só disso, considere escalar via 'escalar_sem_clausula'). Deixe claro que é uma estimativa
informativa, não uma cobrança formal.

Se o inquilino avisar que vai atrasar um pouco (ex: "posso pagar amanhã?", "vou atrasar
uns dias") SEM pedir desconto ou perdão de multa — isso não precisa de aprovação de
ninguém, não existe prazo de carência formal no sistema: tranquilize o inquilino, explique
que não tem problema, mas que juros/multa (se houver) já contam a partir da data de
vencimento, e peça para enviar o comprovante assim que pagar. Se, em vez disso, o
inquilino pedir desconto, perdão de multa ou for um atraso muito longo/incerto, isso É
pedido de desconto/renegociação — não responda você mesmo, deixe a checagem de
escalonamento no início desta função decidir (ela já roda antes de qualquer resposta sua).

## ONDE PAGAR
Se o inquilino perguntar onde/como pagar (chave Pix, dados bancários), responda com
'pix_chave', 'banco_agencia' e 'banco_conta' de 'buscar_dados_inquilino'. Se algum desses
campos vier nulo, diga que não há esse dado cadastrado e que vai verificar com a equipe
(chame 'escalar_sem_clausula' se a pergunta específica não puder ser respondida por falta
desse dado).

## AVISO INFORMAL DE PAGAMENTO JÁ FEITO
Se o inquilino só avisar que já pagou / fez o Pix, sem anexar comprovante (ex: "fiz o
pix", "já paguei") — agradeça o aviso e peça para enviar o comprovante (foto ou PDF) assim
que possível, pra dar baixa oficial. Você não tem como confirmar/registrar o pagamento sem
o comprovante — não diga que já está confirmado.

## PEDIDOS ADMINISTRATIVOS SIMPLES
Pedidos como "manda o contrato pra eu assinar", "me envia uma cópia do contrato", ou
qualquer solicitação de documento/ação que você não tem como executar (não é uma pergunta
que 'buscar_dados_inquilino'/'consultar_historico' respondem) — não invente que já
resolveu. Diga que vai verificar com a equipe e retornar, no mesmo espírito de
'escalar_sem_clausula', sem prometer prazo que você não controla.

## TOM
Respostas curtas e diretas, adequadas a WhatsApp, sem markdown pesado. Nunca revele que
você é uma IA "multiagente" nem explique arquitetura interna."""


def _tools_schema() -> list[dict]:
    return [
        {
            "name": TOOL_BUSCAR_DADOS,
            "description": (
                "Busca todos os dados estruturados do contrato do inquilino desta conversa: "
                "tipo_locatario ('pf' ou 'pj'), valor do aluguel, datas, garantia, e "
                "cláusulas com número/título/texto/categoria. Chame esta tool ANTES de "
                "responder qualquer pergunta factual sobre o contrato — nunca responda com "
                "um valor que não veio daqui. O contrato já está fixado pela sessão atual; "
                "não é possível buscar dados de outro contrato através desta tool."
            ),
            "input_schema": {"type": "object", "properties": {}},
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
        {
            "name": TOOL_ESCALAR_SEM_CLAUSULA,
            "description": (
                "Chame esta tool quando 'buscar_dados_inquilino' já tiver sido consultada e "
                "nenhuma cláusula do contrato responder à pergunta do inquilino. NÃO responda "
                "em texto que 'não encontrou' — chame esta tool, que registra o caso para a "
                "equipe humana avaliar e devolve a mensagem correta para o inquilino."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "resumo_pergunta": {
                        "type": "string",
                        "description": "Resumo objetivo, em uma frase, da pergunta sem cláusula correspondente.",
                    },
                },
                "required": ["resumo_pergunta"],
            },
        },
    ]


def _executar_buscar_dados_inquilino(contract_id: str) -> dict:
    # contract_id só escolhe QUAL client/token usar — a RPC em si não recebe
    # contract_id como argumento, ela resolve isso internamente via
    # agent_contract_id() lendo o claim do próprio JWT (ver migration
    # 006_a1_rpcs.sql).
    client = obter_client_agente(contract_id)
    resposta = client.rpc("buscar_dados_inquilino", {}).execute()
    dados = resposta.data or {}

    # data_aniversario_reajuste vindo do banco é o que a extração do PDF
    # capturou na assinatura — fica desatualizado assim que o tempo passa
    # (ver Migration/extração: mesmo bug que o A4 evita calculando isso em
    # runtime, nunca lendo essa coluna). Recalcula aqui do mesmo jeito que o
    # A4 faz, com 'hoje' de verdade — só se aplica a índice com cálculo
    # automático (igpm/ipca); livre_negociacao não tem aniversário calculável.
    if dados.get("indice_reajuste") in INDICES_COM_CALCULO_AUTOMATICO and dados.get("data_inicio"):
        data_inicio = date.fromisoformat(dados["data_inicio"])
        dados["data_aniversario_reajuste"] = proximo_aniversario_contrato(
            data_inicio, date.today()
        ).isoformat()

    # valida contra o schema esperado ANTES de repassar pro modelo — se a
    # RPC mudar de formato no banco, isso deve quebrar aqui de forma
    # explícita, não virar um campo estranho que o Claude tenta interpretar.
    DadosInquilino.model_validate(dados)

    # SEM filtragem por campos: sempre devolve o dict completo. Havia um
    # parâmetro opcional 'campos' aqui antes, permitindo o modelo pedir um
    # recorte — mas isso criou um modo de falha real em teste: o modelo
    # pediu só ['valor_aluguel'] para uma pergunta que também envolvia
    # vencimento, recebeu de volta um dict sem dia_vencimento, e concluiu
    # (errado) que o dado "não existe no sistema" — sem perceber que foi
    # ele mesmo quem causou o recorte. Como o payload de um contrato inteiro
    # é pequeno, o ganho de token da filtragem não compensa esse risco.
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

        # Caminho terminal: se o modelo chamou escalar_sem_clausula (em vez de,
        # ou junto com, outras tools nesta mesma rodada), ignora o resto e
        # escala direto — não faz sentido continuar o loop de tool-use depois
        # de decidir que o caso deve ir pra equipe.
        bloco_sem_clausula = next(
            (b for b in blocos_tool_use if b.name == TOOL_ESCALAR_SEM_CLAUSULA), None
        )
        if bloco_sem_clausula is not None:
            resumo = bloco_sem_clausula.input.get("resumo_pergunta", mensagem_atual)
            avaliacao = AvaliacaoEscalonamento(
                motivo="sem_clausula",
                descricao=f"A1 não encontrou cláusula correspondente à pergunta: {resumo}",
                resposta_para_inquilino=(
                    "Não encontrei uma cláusula do seu contrato que trate exatamente disso. "
                    "Vou encaminhar para a equipe avaliar e você recebe um retorno em breve."
                ),
            )
            executar_escalonamento(contract_id, avaliacao)
            return avaliacao.resposta_para_inquilino

        messages.append({"role": "assistant", "content": response.content})

        resultados_tool = []
        for bloco in blocos_tool_use:
            try:
                if bloco.name == TOOL_BUSCAR_DADOS:
                    resultado = _executar_buscar_dados_inquilino(contract_id)
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
    # fallback escala pelo mesmo caminho do A5, gerando protocolo em
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