"""Testes de app/tools/mensagens_manutencao.py — foco em
montar_parametros_notificacao_gestora (checkup pós-WA-06/WA-08, Ponto 3):
os parâmetros posicionais pro template manutencao_equipe precisam vir na
ordem exata cadastrada (protocolo, imóvel, categoria, urgência, descrição),
como uma lista de 5 strings — nunca uma única mensagem pronta."""

from uuid import uuid4

from app.models.maintenance import TicketManutencao
from app.tools.mensagens_manutencao import (
    montar_notificacao_gestora,
    montar_parametros_notificacao_gestora,
)


def _ticket(**overrides) -> TicketManutencao:
    base = {
        "id": uuid4(),
        "protocolo": "MNT-2026-0001",
        "categoria": "hidraulica",
        "urgencia": "alta",
        "descricao": "Vazamento no banheiro",
        "sinais_risco": [],
        "classificacao_incerta": False,
    }
    base.update(overrides)
    return TicketManutencao(**base)


def test_parametros_na_ordem_protocolo_imovel_categoria_urgencia_descricao():
    ticket = _ticket()

    parametros = montar_parametros_notificacao_gestora(
        ticket, "Rua X, 123", "302", "Vazamento grande no banheiro, água acumulando"
    )

    assert parametros == [
        "MNT-2026-0001",
        "Rua X, 123, apto 302",
        "hidraulica",
        "alta",
        "Vazamento grande no banheiro, água acumulando",
    ]


def test_parametros_e_sempre_uma_lista_de_cinco_strings():
    ticket = _ticket(protocolo="MNT-2026-0099", categoria="eletrica", urgencia="media")

    parametros = montar_parametros_notificacao_gestora(ticket, "Av. Y, 456", "12", "Chuveiro não esquenta")

    assert len(parametros) == 5
    assert all(isinstance(p, str) for p in parametros)


def test_parametros_nao_inclui_sinais_risco_nem_prazo_nem_incerteza():
    """De propósito: a versão estruturada não vira 8 variáveis — só os 5
    campos que Davi escolheu. sinais_risco/prazo/incerteza continuam só no
    texto livre (montar_notificacao_gestora), não no template."""
    ticket = _ticket(sinais_risco=["fiação exposta", "fumaça"], classificacao_incerta=True)

    parametros = montar_parametros_notificacao_gestora(ticket, "Rua X, 123", "302", "Cheiro de queimado")

    texto_junto = " ".join(parametros)
    assert "fiação exposta" not in texto_junto
    assert "fumaça" not in texto_junto
    assert len(parametros) == 5


def test_montar_notificacao_gestora_texto_livre_continua_funcionando():
    """Regressão: a função antiga (texto livre, usada por
    ResultadoTurno.notificacao_gestora e pelos testes já existentes de
    test_a3_fluxo.py) não foi alterada."""
    ticket = _ticket()

    texto = montar_notificacao_gestora(ticket, "Rua X, 123", "302", "Vazamento no banheiro")

    assert "MNT-2026-0001" in texto
    assert "Rua X, 123" in texto
