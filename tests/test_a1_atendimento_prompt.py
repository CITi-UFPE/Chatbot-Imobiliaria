"""Teste de regressão do SYSTEM_PROMPT do A1 (app/agents/a1_atendimento/atendimento.py).

Não chama a API da Anthropic de verdade — só garante que a instrução de
saudação não seja apagada silenciosamente num refactor futuro. Se o modelo
REALMENTE responde bem (tom natural, não repetitivo), isso é validado à
parte, manualmente, com um Cenario em tests/test_a1_local.py (que chama a
API de verdade e por isso não roda em `pytest -x -q`)."""

from app.agents.a1_atendimento import atendimento


def test_system_prompt_tem_secao_de_saudacao():
    assert "## SAUDAÇÃO" in atendimento.SYSTEM_PROMPT


def test_system_prompt_deixa_saudacao_como_excecao_ao_escopo():
    """Regressão do gap desta revisão: sem uma exceção explícita, a seção
    '## ESCOPO' ('Você responde APENAS perguntas diretas sobre o
    contrato...') faria o próprio A1 recusar uma saudação por ela não ser
    sobre o contrato — o oposto do pedido do usuário."""
    prompt = atendimento.SYSTEM_PROMPT
    assert prompt.index("## SAUDAÇÃO") > prompt.index("## ESCOPO")
    assert "exceção" in prompt.lower()
    assert "sem chamar nenhuma tool" in prompt.lower()


def test_system_prompt_tem_secao_de_contas_em_aberto():
    assert "## CONTAS EM ABERTO" in atendimento.SYSTEM_PROMPT


def test_system_prompt_explica_os_status_de_cobranca_em_linguagem_simples():
    """O modelo não deve citar o valor cru do campo 'status' — precisa
    parafrasear. Este teste tranca que as explicações de cada status
    continuam no prompt (regressão)."""
    prompt = atendimento.SYSTEM_PROMPT.lower()
    for status_explicado in ("pendente", "atrasado", "aguardando_confirmacao", "divergente", "em_negociacao"):
        assert status_explicado in prompt


def test_system_prompt_limita_historico_de_pagamento_a_30_dias():
    """Regressão do requisito explícito do usuário: histórico de pagamento
    não é irrestrito — só cobranças com data de pagamento identificada nos
    últimos 30 dias, e o modelo não pode inventar nada fora dessa janela."""
    prompt = atendimento.SYSTEM_PROMPT
    assert "30 dias" in prompt
    assert "nunca" in prompt.lower() and "invente" in prompt.lower()


def test_system_prompt_menciona_tool_buscar_status_cobranca():
    assert atendimento.TOOL_BUSCAR_STATUS_COBRANCA in atendimento.SYSTEM_PROMPT
