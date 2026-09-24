"""Regressão do prompt de avaliar_escalonamento (A5).

Caso real: 'quais são minhas contas em aberto?' foi escalada pelo avaliador
do A5 (que roda antes do A1, só com o texto da mensagem) com a resposta
'Não tenho acesso aos dados financeiros da sua conta' — o A1 tem a tool
buscar_status_cobranca_inquilino e deveria ter respondido."""

from app.agents.a5_escalonamento import escalonamento as esc
from app.agents.a5_escalonamento.criterios import CRITERIOS_POR_MOTIVO


def test_sem_clausula_nao_e_avaliado_so_pelo_texto_da_mensagem():
    """Só dá pra saber que não há cláusula DEPOIS de ler o contrato — quem
    decide isso é o A1, via tool escalar_sem_clausula."""
    assert CRITERIOS_POR_MOTIVO["sem_clausula"].deteccao_via_mensagem is False
    assert "- sem_clausula:" not in esc.SYSTEM_PROMPT


def test_prompt_diz_que_consulta_informativa_de_cobranca_nao_escala():
    prompt = esc.SYSTEM_PROMPT.lower()
    assert "contas em aberto" in prompt
    assert "faturas" in prompt


def _resposta_com_tool_use(motivo: str):
    from unittest.mock import MagicMock

    bloco = MagicMock()
    bloco.type = "tool_use"
    bloco.input = {
        "motivo": motivo,
        "descricao": "x",
        "resposta_para_inquilino": "Não tenho acesso aos dados financeiros da sua conta.",
    }
    resposta = MagicMock()
    resposta.content = [bloco]
    return resposta


def test_avaliador_descarta_motivo_nao_detectavel_pela_mensagem():
    """Mesmo que o modelo escolha 'sem_clausula' (o schema da tool ainda
    aceita), o avaliador não escala — deixa o A1 consultar os dados."""
    from unittest.mock import patch

    with patch.object(esc.anthropic, "Anthropic") as anthropic_cls:
        anthropic_cls.return_value.messages.create.return_value = _resposta_com_tool_use("sem_clausula")
        assert esc.avaliar_escalonamento("quais são minhas contas em aberto?") is None


def test_avaliador_mantem_motivo_detectavel_pela_mensagem():
    from unittest.mock import patch

    with patch.object(esc.anthropic, "Anthropic") as anthropic_cls:
        anthropic_cls.return_value.messages.create.return_value = _resposta_com_tool_use(
            "desconto_renegociacao"
        )
        avaliacao = esc.avaliar_escalonamento("dá pra tirar a multa?")

    assert avaliacao is not None
    assert avaliacao.motivo == "desconto_renegociacao"
