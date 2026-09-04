"""Testes do schema/tool de classificação (app/orchestrator/classificador.py).

Não chama a API da Anthropic de verdade — só valida o modelo Pydantic e o
schema da tool que é oferecido ao Claude, que é o contrato que o resto do
sistema depende."""

from app.orchestrator import classificador as clf


def test_tool_schema_aceita_fora_de_escopo():
    """FORA_DE_ESCOPO precisa estar no enum que a tool oferece ao Claude —
    sem isso ele estruturalmente não consegue devolver esse valor, mesmo
    que o SYSTEM_PROMPT peça."""
    schema = clf._tool_schema()
    enum_agente = schema["input_schema"]["properties"]["agente"]["enum"]

    assert set(enum_agente) == {"A1", "A3", "A5", "FORA_DE_ESCOPO"}


def test_classificacao_intencao_aceita_fora_de_escopo():
    classificacao = clf.ClassificacaoIntencao(
        agente="FORA_DE_ESCOPO",
        motivo="Papo pessoal, sem relação com o contrato desta conversa.",
        urgencia="baixa",
    )

    assert classificacao.agente == "FORA_DE_ESCOPO"


def test_system_prompt_orienta_quando_usar_fora_de_escopo():
    """Não substitui um teste de comportamento real do modelo (isso exigiria
    chamar a API de verdade), mas garante que o prompt não regrida
    silenciosamente perdendo a instrução — se alguém apagar essa seção do
    prompt num refactor futuro, este teste quebra."""
    assert "FORA_DE_ESCOPO" in clf.SYSTEM_PROMPT
    # os dois exemplos concretos que motivaram esta correção precisam
    # continuar aparecendo no prompt, não só o nome do destino
    assert "outro imóvel" in clf.SYSTEM_PROMPT.lower() or "outros imóveis" in clf.SYSTEM_PROMPT.lower()
    assert "pessoal" in clf.SYSTEM_PROMPT


def test_system_prompt_orienta_pergunta_de_condominio_para_a1():
    """Regressão do gap identificado na Revisão 3: pergunta sobre o imóvel/
    condomínio que não está numa cláusula específica do contrato (ex:
    regimento interno) precisa estar explicitamente marcada como A1 no
    prompt, não FORA_DE_ESCOPO — sem isso o classificador tende a confundir
    "não está na cláusula" com "sem relação com a locação" e recusar uma
    pergunta legítima do dia a dia do inquilino."""
    assert "regimento" in clf.SYSTEM_PROMPT.lower()


def test_system_prompt_manda_saudacao_pura_para_a1():
    """Regressão da Revisão 4: saudação pura vai pro A1 (resposta gerada
    pelo modelo, natural) em vez de um pseudo-destino dedicado com resposta
    fixa em Python — a Revisão 3 tinha um destino 'SAUDACAO' que a Revisão
    4 removeu a pedido do usuário (ficava "quadrado" demais). Este teste
    tranca as duas pontas dessa decisão: a instrução de saudação continua
    no prompt, e o destino removido não pode voltar por acidente."""
    assert "tudo bem" in clf.SYSTEM_PROMPT.lower()
    assert "SAUDACAO" not in clf.SYSTEM_PROMPT
