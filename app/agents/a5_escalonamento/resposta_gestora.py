"""Resposta da gestora a uma escalação — reply nativo do WhatsApp (Migration 022).

Fecha o loop que faltava no A5: hoje, quando um caso é escalado (ex: pergunta
sem cláusula correspondente), a Fernanda recebe a notificação mas não existe
caminho de volta — ela tem que ir pessoalmente resolver com o inquilino. Este
módulo trata o REPLY NATIVO dela (segurar a notificação original e responder)
como a resposta que deve ser repassada ao inquilino, corretamente correlata
com o caso certo mesmo com múltiplos escalonamentos abertos ao mesmo tempo.

Correlação via `context.id` do payload da Meta (o wamid da mensagem
respondida), não por telefone nem por "o caso mais recente" — a mesma
ambiguidade que existe no fluxo de correção de comprovante do A2 (pausado,
ver conversa com o Davi) existiria aqui se a correlação fosse por qualquer
coisa menos precisa que isso. Duas chamadas RPC, na mesma ordem de
resolver_contrato_por_telefone -> obter_client_agente:
  1. identificar_contrato_por_wamid — papel anon (ainda não temos
     contract_id pra montar o JWT do agente).
  2. obter_escalonamento_aberto — já com o token escopado, devolve os dados
     pra compor a resposta.

`compor_resposta_inquilino` é uma chamada isolada e bem restrita à Claude —
NUNCA usa tool-use nem tem acesso a nenhum dado além do que já foi passado
explicitamente (a pergunta original e a resposta literal da gestora). O
guardrail central: nunca acrescentar informação, justificativa ou detalhe
que a gestora não tenha dito — ver SYSTEM_PROMPT abaixo.

`marcar_resolvido` só deve ser chamada DEPOIS que a mensagem já foi entregue
ao inquilino com sucesso — se o envio falhar, a escalação continua 'aberto'
e o mesmo wamid pode ser reprocessado depois, sem exigir controle de retry
separado (ver Migration 022).
"""

import logging
import os

import anthropic
from supabase import create_client

from app.tools.whatsapp_message_policy import MensagemTemplate

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """Você recebe a pergunta original de um inquilino e a resposta que a gestora
do imóvel deu para essa pergunta. Sua única tarefa é compor uma mensagem curta e natural,
em português, para mandar ao inquilino via WhatsApp, repassando a resposta da gestora.

REGRAS ABSOLUTAS:
- Use SOMENTE a informação contida na resposta da gestora. Nunca acrescente detalhe,
  justificativa, explicação ou condição que ela não tenha mencionado explicitamente.
- Se a resposta da gestora for vaga, curta ou incompleta (ex: só "não" ou "sim"), mantenha
  a mesma objetividade na sua mensagem — não tente completar ou adivinhar o motivo.
- Não invente número de cláusula, prazo, valor ou qualquer dado que não veio da gestora.
- Tom direto e educado, adequado a WhatsApp, sem markdown pesado, sem se estender.
- Nunca revele que você é uma IA nem mencione "gestora", "equipe" ou arquitetura interna —
  fale como se fosse a continuação natural do atendimento."""


def identificar_contrato_por_wamid(wamid: str) -> str | None:
    """Descobre o contract_id da escalação aberta cujo wamid de notificação
    corresponde ao `context.id` respondido pela Fernanda.

    Usa um client "anon" (sem token assinado) chamando
    resolver_escalonamento_por_wamid — mesmo racional de
    app/orchestrator/processar_mensagem.py::_resolver_contract_id: antes de
    ter o contract_id ainda não dá para montar o JWT escopado do agente.
    """
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY não configurados.")

    client = create_client(url, anon_key)
    resposta = client.rpc("resolver_escalonamento_por_wamid", {"p_wamid": wamid}).execute()
    return resposta.data


def obter_escalonamento_aberto(client, wamid: str) -> dict | None:
    """Já com o token escopado do agente (contract_id do JWT) — devolve
    protocolo/motivo/descricao/telefone_whatsapp da escalação aberta
    correspondente ao wamid, ou None se não existir mais (já resolvida, ou
    o reply não correspondia a nenhum caso deste contrato)."""
    resposta = client.rpc(
        "agent_obter_escalonamento_aberto_por_wamid", {"p_wamid": wamid}
    ).execute()
    return resposta.data


def compor_resposta_inquilino(pergunta_original: str, resposta_gestora: str, model: str = MODEL) -> str:
    """Chamada isolada à Claude — SEM tool-use, sem acesso a nenhum dado do
    contrato além do que é passado explicitamente aqui. Só parafraseia a
    resposta literal da gestora para o formato de mensagem ao inquilino."""
    client = anthropic.Anthropic()
    texto_usuario = (
        f"Pergunta original do inquilino:\n{pergunta_original}\n\n"
        f"Resposta da gestora:\n{resposta_gestora}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": texto_usuario}],
    )
    bloco_texto = next((b for b in response.content if b.type == "text"), None)
    if bloco_texto is None:
        raise RuntimeError("Resposta da Claude sem bloco de texto ao compor resposta ao inquilino.")
    return bloco_texto.text.strip()


def marcar_resolvido(client, protocolo: str) -> bool:
    """Marca a escalação como resolvida — só deve ser chamada depois que a
    mensagem já foi entregue ao inquilino com sucesso (ver docstring do
    módulo). Devolve False se a escalação já não estava mais 'aberto'
    (idempotência — mesmo padrão de agent_finalizar_contrato)."""
    resposta = client.rpc(
        "agent_marcar_escalonamento_resolvido", {"p_protocolo": protocolo}
    ).execute()
    return bool(resposta.data)


def montar_template_resposta_gestora(resposta_inquilino: str) -> MensagemTemplate:
    """Template usado quando a janela de 24h com o inquilino está fechada
    (decidir_saida_para_contrato, app/tools/whatsapp_message_policy.py).

    NUNCA reaproveitar TEMPLATE_RETOMADA_ATENDIMENTO aqui: aquele template não
    tem variável nenhuma porque foi desenhado pra fluxos onde o agente
    recalcula a resposta quando o inquilino responder de novo (A1/A3) — a
    resposta da gestora não é recalculável, é uma informação humana pontual.
    Perdê-la equivale a nunca ter repassado o caso, mesmo com o escalonamento
    marcado como resolvido logo em seguida (ver docstring do módulo).
    """
    return MensagemTemplate(
        nome="resposta_gestora_fora_da_janela",
        idioma="pt_BR",
        parametros=(resposta_inquilino,),
    )
