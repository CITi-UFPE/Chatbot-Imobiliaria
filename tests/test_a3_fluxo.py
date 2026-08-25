from uuid import uuid4

from app.agents.a3_manutencao.fluxo import (
    EstadoAtendimentoManutencao,
    iniciar_atendimento,
    processar_turno,
)
from app.models.maintenance import ClassificacaoManutencao, TicketManutencao

IMOVEL_ENDERECO = "Ed. X"
IMOVEL_NUMERO = "302"


def _classificacao(**overrides) -> ClassificacaoManutencao:
    base = {
        "categoria": "hidraulica",
        "urgencia": "media",
        "sinais_risco": [],
        "justificativa": "Torneira pingando.",
        "categoria_confidence": 0.95,
        "urgencia_confidence": 0.9,
    }
    base.update(overrides)
    return ClassificacaoManutencao(**base)


def _abrir_ticket_fake(classificacao: ClassificacaoManutencao, descricao: str, incerta: bool) -> TicketManutencao:
    return TicketManutencao(
        id=uuid4(),
        protocolo="MNT-2026-0001",
        categoria=classificacao.categoria,
        urgencia=classificacao.urgencia,
        descricao=descricao,
        sinais_risco=classificacao.sinais_risco,
        classificacao_incerta=incerta,
    )


class RegistroEscalonamento:
    def __init__(self):
        self.chamadas = []

    def __call__(self, motivo: str, descricao: str) -> None:
        self.chamadas.append((motivo, descricao))


def test_iniciar_atendimento_pergunta_confirmacao():
    resultado = iniciar_atendimento(IMOVEL_ENDERECO, IMOVEL_NUMERO)
    assert "302" in resultado.resposta_inquilino
    assert resultado.estado.etapa == "aguardando_confirmacao_imovel"


def test_confirmacao_avanca_para_coleta_de_descricao():
    estado = EstadoAtendimentoManutencao()
    escalonar = RegistroEscalonamento()

    resultado = processar_turno(
        estado,
        "Sim, é esse mesmo",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=escalonar,
    )

    assert resultado.estado.etapa == "aguardando_descricao"
    assert not escalonar.chamadas


def test_palavra_confirmacao_nao_casa_como_substring_de_outra_palavra():
    """'sim' é substring de 'assim' — não deve ser lido como confirmação
    (regressão do bug de correspondência por substring)."""
    estado = EstadoAtendimentoManutencao()
    escalonar = RegistroEscalonamento()

    resultado = processar_turno(
        estado,
        "Assim que eu conseguir eu te aviso qual é o problema",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=escalonar,
    )

    assert resultado.estado.etapa == "aguardando_confirmacao_imovel"
    assert not escalonar.chamadas


def test_duas_negacoes_escalam_para_humano():
    estado = EstadoAtendimentoManutencao()
    escalonar = RegistroEscalonamento()

    r1 = processar_turno(
        estado,
        "não é esse apto",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=escalonar,
    )
    assert r1.estado.etapa == "aguardando_confirmacao_imovel"
    assert not r1.escalonado

    r2 = processar_turno(
        r1.estado,
        "não, errado de novo",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=escalonar,
    )

    assert r2.escalonado
    assert r2.estado.etapa == "finalizado"
    assert escalonar.chamadas == [("pedido_humano", "Falha ao confirmar identificação do imóvel após 2 tentativa(s).")]


def test_descricao_com_confianca_alta_abre_ticket_direto():
    estado = EstadoAtendimentoManutencao(etapa="aguardando_descricao")
    escalonar = RegistroEscalonamento()

    resultado = processar_turno(
        estado,
        "A torneira da cozinha está pingando direto",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=escalonar,
        classificar_fn=lambda descricao: _classificacao(),
    )

    assert resultado.estado.etapa == "finalizado"
    assert resultado.ticket is not None
    assert resultado.ticket.protocolo == "MNT-2026-0001"
    assert "24h" in resultado.resposta_inquilino
    assert resultado.notificacao_gestora is not None
    assert IMOVEL_ENDERECO in resultado.notificacao_gestora
    # checkup pós-WA-06/WA-08 (Ponto 3): parâmetros estruturados pro
    # template manutencao_equipe, na ordem protocolo/imóvel/categoria/
    # urgência/descrição — é isso que app/agents/a3_manutencao/atendimento.py
    # de fato usa pra notificar a equipe agora.
    assert resultado.notificacao_gestora_parametros is not None
    assert resultado.notificacao_gestora_parametros[0] == resultado.ticket.protocolo
    assert IMOVEL_ENDERECO in resultado.notificacao_gestora_parametros[1]
    assert len(resultado.notificacao_gestora_parametros) == 5


def test_urgencia_alta_menciona_prazo_de_1h_e_emergencia():
    estado = EstadoAtendimentoManutencao(etapa="aguardando_descricao")

    resultado = processar_turno(
        estado,
        "Vazamento grande, água alagando tudo",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=RegistroEscalonamento(),
        classificar_fn=lambda descricao: _classificacao(
            urgencia="alta", categoria_confidence=0.95, urgencia_confidence=0.95
        ),
    )

    assert "1h" in resultado.resposta_inquilino
    assert "emergência" in resultado.resposta_inquilino


def test_confianca_baixa_pergunta_esclarecimento_e_reclassifica():
    estado = EstadoAtendimentoManutencao(etapa="aguardando_descricao")

    classificacao_ambigua = _classificacao(categoria_confidence=0.4, urgencia_confidence=0.4)
    classificacao_esclarecida = _classificacao(
        categoria="eletrica", categoria_confidence=0.9, urgencia_confidence=0.9
    )

    respostas_classificar = iter([classificacao_ambigua, classificacao_esclarecida])

    r1 = processar_turno(
        estado,
        "Tem um problema na fiação perto do chuveiro",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=RegistroEscalonamento(),
        classificar_fn=lambda descricao: next(respostas_classificar),
        gerar_pergunta_fn=lambda descricao, classificacao: "É a fiação ou tem água vazando perto dela?",
    )

    assert r1.estado.etapa == "aguardando_esclarecimento"
    assert r1.ticket is None
    assert "fiação" in r1.resposta_inquilino

    r2 = processar_turno(
        r1.estado,
        "É a fiação, tomada solta",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=RegistroEscalonamento(),
        classificar_fn=lambda descricao: next(respostas_classificar),
    )

    assert r2.estado.etapa == "finalizado"
    assert r2.ticket is not None


def test_confianca_ainda_baixa_apos_esclarecimento_marca_incerteza_e_nao_rebaixa_urgencia():
    estado = EstadoAtendimentoManutencao(etapa="aguardando_descricao")

    classificacao_inicial = _classificacao(
        urgencia="alta", categoria_confidence=0.9, urgencia_confidence=0.4
    )
    classificacao_apos_esclarecimento = _classificacao(
        urgencia="baixa", categoria_confidence=0.9, urgencia_confidence=0.5
    )
    respostas_classificar = iter([classificacao_inicial, classificacao_apos_esclarecimento])

    tickets_abertos = []

    def abrir_ticket_fn(classificacao, descricao, incerta):
        ticket = _abrir_ticket_fake(classificacao, descricao, incerta)
        tickets_abertos.append(ticket)
        return ticket

    r1 = processar_turno(
        estado,
        "Relato ambíguo qualquer",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=abrir_ticket_fn,
        criar_escalonamento_fn=RegistroEscalonamento(),
        classificar_fn=lambda descricao: next(respostas_classificar),
        gerar_pergunta_fn=lambda descricao, classificacao: "pergunta qualquer",
    )

    r2 = processar_turno(
        r1.estado,
        "resposta ainda ambígua",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=abrir_ticket_fn,
        criar_escalonamento_fn=RegistroEscalonamento(),
        classificar_fn=lambda descricao: next(respostas_classificar),
    )

    assert r2.ticket.classificacao_incerta is True
    # Nunca subestima: mesmo a reclassificação tendo saído "baixa", mantém "alta".
    assert tickets_abertos[0].urgencia == "alta"


def test_mensagem_apos_finalizado_nao_reabre_fluxo():
    estado = EstadoAtendimentoManutencao(etapa="finalizado")

    resultado = processar_turno(
        estado,
        "oi de novo",
        imovel_endereco=IMOVEL_ENDERECO,
        imovel_numero=IMOVEL_NUMERO,
        abrir_ticket_fn=_abrir_ticket_fake,
        criar_escalonamento_fn=RegistroEscalonamento(),
    )

    assert resultado.ticket is None
    assert "encerrado" in resultado.resposta_inquilino
