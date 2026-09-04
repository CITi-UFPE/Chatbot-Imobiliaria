"""Agente 5 — Escalonamento Humano.

Duas partes:
  1. `avaliar_escalonamento` — decide SE e POR QUÊ uma mensagem/conversa deve
     escalar, usando os critérios de criterios.py como tool schema pra
     Claude (mesmo padrão de app/tools/contract_extraction.py: tool-use com
     schema Pydantic — mas aqui com tool_choice="auto", porque a maioria das
     mensagens NÃO deve escalar, diferente da extração de contrato onde a
     tool é sempre chamada).
  2. `executar_escalonamento` — grava a escalação via RPC
     agent_create_escalation (que já gera o protocolo — ver
     docs/schemas/004_protocolo_e_resolucao_contrato.sql) e notifica a
     equipe (stub, ver notificacao.py, até a API do WhatsApp existir).

Os critérios `loop_nao_resolvido` e `frustracao_crescente` dependem de
estado acumulado da conversa que o orquestrador ainda não produz
formalmente (ver criterios.py). `detectar_loop_ou_frustracao` abaixo é uma
heurística de curto prazo baseada em conversation_logs — não é a versão
final.
"""

import logging
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from app.agents.a5_escalonamento.criterios import CRITERIOS
from app.agents.a5_escalonamento.notificacao import notificar_staff_escalonamento
from app.orchestrator.agent_auth import obter_client_agente

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"

MotivoEscalonamento = Literal[
    "sem_clausula",
    "pedido_humano",
    "rescisao_antecipada",
    "desconto_renegociacao",
    "ameaca_juridica",
    "sublocacao_pedido",
    "troca_fiador",
    "obito_fiador",
    "risco_estrutural",
    "emergencia",
    "terceiros_condominio",
    "loop_nao_resolvido",
    "frustracao_crescente",
    # Nunca chega aqui vindo de avaliar_escalonamento (não é detectável a
    # partir de uma mensagem — ver criterios.py) — só é usado por quem chama
    # executar_escalonamento diretamente, como o cron do A2.
    "atraso_severo",
]


class AvaliacaoEscalonamento(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: MotivoEscalonamento = Field(description="Critério que melhor justifica o escalonamento.")
    descricao: str = Field(
        description="Resumo objetivo do que motivou o escalonamento, para a equipe humana."
    )
    resposta_para_inquilino: str = Field(
        description="Mensagem curta e educada para o inquilino, avisando que o caso foi "
        "encaminhado para a equipe e que em breve alguém entrará em contato. Não incluir "
        "número de protocolo aqui — ele ainda não existe neste momento (só é gerado "
        "depois, em executar_escalonamento)."
    )


TOOL_NAME = "escalar_para_humano"

_CRITERIOS_TEXTO = "\n".join(
    f"- {c.motivo}: {c.descricao}" for c in CRITERIOS if c.deteccao_via_mensagem
)

SYSTEM_PROMPT = (
    "Você avalia se uma mensagem de inquilino, dentro do contexto da conversa, deve ser "
    f"escalada para um humano da equipe de gestão. Use a tool '{TOOL_NAME}' SOMENTE quando "
    "a mensagem se encaixar claramente em um dos critérios abaixo. Não escale dúvidas "
    "simples que o contrato já responde e que não tenham risco financeiro, jurídico ou de "
    "segurança associado — a maioria das mensagens não deve escalar.\n\n"
    f"Critérios:\n{_CRITERIOS_TEXTO}\n\n"
    "Critérios 'loop_nao_resolvido' e 'frustracao_crescente' são avaliados separadamente "
    "(dependem de padrão ao longo da conversa, não desta chamada) — não os use aqui."
)
# Nota: 'atraso_severo' nem entra na lista de critérios acima (não é
# detectável por mensagem — ver criterios.py), então nunca aparece pro
# Claude aqui. Quem dispara esse motivo é o cron do A2, chamando
# executar_escalonamento diretamente, sem passar por avaliar_escalonamento.


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Registra que a conversa atual deve ser escalada para um humano, e por quê.",
        "input_schema": AvaliacaoEscalonamento.model_json_schema(),
    }


def avaliar_escalonamento(
    mensagem_atual: str, historico_conversa: str = "", model: str = MODEL
) -> Optional[AvaliacaoEscalonamento]:
    """Pergunta à Claude se a conversa deve escalar agora. Devolve None se não."""
    client = anthropic.Anthropic()

    texto_usuario = mensagem_atual
    if historico_conversa:
        texto_usuario = (
            f"Histórico recente da conversa:\n{historico_conversa}\n\n"
            f"Mensagem atual do inquilino:\n{mensagem_atual}"
        )

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[_tool_schema()],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": texto_usuario}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        return None  # Claude decidiu não escalar

    return AvaliacaoEscalonamento.model_validate(tool_use.input)


def executar_escalonamento(contract_id: str, avaliacao: AvaliacaoEscalonamento) -> str:
    """Grava a escalação no banco (via RPC, com o token escopado do agente),
    busca os dados do inquilino pra notificação ficar identificável, e
    notifica a equipe. Devolve o protocolo gerado pelo banco.

    A gravação (RPC) é a fonte da verdade — o caso já está escalado, com
    protocolo válido, assim que ela retorna. Uma falha só no aviso à
    equipe (rede instável, WHATSAPP_STAFF_PHONE_NUMBER ausente etc.) por
    isso não pode derrubar o retorno do protocolo nem a resposta que o
    chamador devolve ao inquilino (avaliacao.resposta_para_inquilino) — a
    falha é logada, não engolida, mas não propaga daqui. O mesmo vale pra
    busca dos dados extras do inquilino (nome/imóvel/telefone): se falhar,
    a notificação ainda sai, só sem esses 3 campos (notificar_staff_
    escalonamento troca "" por "não informado").

    Migration 022: quando a notificação sai de fato (envio real ativo), o
    wamid devolvido pela Meta é gravado na escalação — é o que permite
    depois correlacionar um reply nativo da Fernanda com este caso
    específico (ver resposta_gestora.py). Falha só nesse registro (não na
    notificação em si) segue a mesma regra: logada, não propagada — sem
    o wamid salvo, a Fernanda só perde a correlação automática, o caso
    continua escalado e visível pelos meios de sempre."""
    client = obter_client_agente(contract_id)
    resposta = client.rpc(
        "agent_create_escalation",
        {"p_motivo": avaliacao.motivo, "p_descricao": avaliacao.descricao},
    ).execute()
    protocolo = resposta.data

    nome_inquilino = ""
    imovel_identificacao = ""
    telefone_inquilino = ""
    try:
        dados_contrato = client.rpc("buscar_dados_cobranca_contrato", {}).execute().data or {}
        nome_inquilino = dados_contrato.get("inquilino_nome") or ""
        imovel_identificacao = dados_contrato.get("imovel_identificacao") or ""
        telefone_inquilino = dados_contrato.get("telefone_whatsapp") or ""
    except Exception:
        logger.exception(
            "Falha ao buscar dados do contrato %s para a notificação de escalonamento %s — "
            "a notificação vai sem nome/imóvel/telefone do inquilino.",
            contract_id,
            protocolo,
        )

    try:
        wamid = notificar_staff_escalonamento(
            str(protocolo),
            avaliacao.motivo,
            avaliacao.descricao,
            nome_inquilino,
            imovel_identificacao,
            telefone_inquilino,
        )
    except Exception:
        logger.exception(
            "Falha ao notificar a equipe sobre o escalonamento %s (contrato %s) — "
            "a escalação em si já foi gravada e o protocolo continua válido.",
            protocolo,
            contract_id,
        )
        wamid = None

    if wamid is not None:
        try:
            client.rpc(
                "agent_registrar_wamid_escalonamento",
                {"p_protocolo": str(protocolo), "p_wamid": wamid},
            ).execute()
        except Exception:
            logger.exception(
                "Falha ao gravar o wamid da notificação para o escalonamento %s (contrato %s) — "
                "a resposta da Fernanda pra este caso não poderá ser correlacionada "
                "automaticamente depois.",
                protocolo,
                contract_id,
            )

    return protocolo


def detectar_loop_ou_frustracao(contract_id: str, limite_mensagens: int = 10) -> Optional[str]:
    """Heurística MVP para os critérios 10/11 — NÃO é a versão final.

    Consulta as últimas mensagens do inquilino em conversation_logs e
    sinaliza 'loop_nao_resolvido' se a mesma mensagem (normalizada, texto
    idêntico após strip/lower — comparação simples, sem NLP) aparecer 3
    vezes seguidas, ou 'frustracao_crescente' se detectar palavras de
    frustração recorrentes nas últimas mensagens. O design correto (um sinal
    "resolvido: sim/não" por turno, mantido pelo orquestrador) ainda não
    existe — ver criterios.py e a observação técnica original do Davi/equipe.
    """
    client = obter_client_agente(contract_id)
    resposta = (
        client.table("conversation_logs")
        .select("mensagem, remetente")
        .eq("contract_id", contract_id)
        .eq("remetente", "inquilino")
        .order("timestamp", desc=True)
        .limit(limite_mensagens)
        .execute()
    )
    mensagens = [row["mensagem"].strip().lower() for row in resposta.data]

    if len(mensagens) >= 3 and len(set(mensagens[:3])) == 1:
        return "loop_nao_resolvido"

    palavras_frustracao = ("já falei", "de novo", "ninguém resolve", "não adianta", "cansado disso")
    ocorrencias = sum(1 for m in mensagens[:5] for p in palavras_frustracao if p in m)
    if ocorrencias >= 2:
        return "frustracao_crescente"

    return None
