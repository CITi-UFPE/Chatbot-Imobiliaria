"""Regressão do prompt de avaliar_escalonamento (A5).

Caso real: 'quais são minhas contas em aberto?' foi escalada pelo avaliador
do A5 (que roda antes do A1, só com o texto da mensagem) com a resposta
'Não tenho acesso aos dados financeiros da sua conta' — o A1 tem a tool
buscar_status_cobranca_inquilino e deveria ter respondido."""

from app.agents.a5_escalonamento import escalonamento as esc


def test_prompt_diz_que_consulta_informativa_de_cobranca_nao_escala():
    prompt = esc.SYSTEM_PROMPT.lower()
    assert "contas em aberto" in prompt
    assert "faturas" in prompt


def test_prompt_mantem_sem_clausula_como_criterio():
    """sem_clausula continua no avaliador (comportamento já validado) — a
    correção é só de prompt, não de critério."""
    assert "- sem_clausula:" in esc.SYSTEM_PROMPT
