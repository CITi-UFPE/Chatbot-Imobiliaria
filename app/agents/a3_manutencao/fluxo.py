from typing import Callable, Literal, Optional

from pydantic import BaseModel

from app.models.maintenance import ClassificacaoManutencao, TicketManutencao, UrgenciaManutencao
from app.tools.maintenance_classification import classificar_manutencao, gerar_pergunta_esclarecimento
from app.tools.mensagens_manutencao import (
    montar_confirmacao_inquilino,
    montar_notificacao_gestora,
    montar_parametros_notificacao_gestora,
)
from app.tools.text_matching import contem_palavra

# Limiares separados (mesmo valor de partida, 0.7) porque errar a urgência é mais
# grave do que errar a categoria — ter dois nomes permite endurecer um sem o outro
# no futuro, sem mexer no código de novo.
CONFIDENCE_MINIMA_CATEGORIA = 0.7
CONFIDENCE_MINIMA_URGENCIA = 0.7

MAX_TENTATIVAS_IDENTIFICACAO = 2

# Quantas vezes o A3 aceita uma resposta de "confusão" (ex: "hein?", "oi",
# "?") durante o esclarecimento antes de desistir e abrir o ticket incerto
# mesmo assim — evita loop infinito se a pessoa nunca responder de verdade,
# mas dá pelo menos uma chance real antes de finalizar num mal-entendido.
MAX_TENTATIVAS_ESCLARECIMENTO = 2

# Só casa quando a mensagem INTEIRA (depois de tirar pontuação/espaço) é uma
# dessas interjeições — nunca quando uma delas aparece dentro de uma frase de
# verdade (ex: "oi, deixa eu explicar melhor" não é ruído, tem conteúdo).
_MARCADORES_CONFUSAO = {
    "hein", "oi", "ola", "que", "quê", "como", "como assim", "o que",
    "nao entendi", "não entendi", "oq", "hum", "hm", "?",
}

_ORDEM_URGENCIA: dict[UrgenciaManutencao, int] = {"baixa": 0, "media": 1, "alta": 2}

# contem_palavra normaliza acento/caixa e casa só palavra inteira (evita
# falso positivo tipo "sim" em "assim", ou "correto" em "incorreto" via substring).
_PALAVRAS_CONFIRMACAO = ("sim", "confirmo", "isso", "correto", "ok", "exato")
_PALAVRAS_NEGACAO = ("nao", "errado", "incorreto")

EtapaAtendimento = Literal[
    "aguardando_confirmacao_imovel",
    "aguardando_descricao",
    "aguardando_esclarecimento",
    "finalizado",
]

# Assinatura esperada de quem persiste o ticket (integração Supabase — fora do
# escopo desta função; ver app/tools/supabase_client.py). Recebe a classificação,
# a descrição original do inquilino e a marcação de incerteza, devolve o
# TicketManutencao já com protocolo gerado.
AbrirTicketFn = Callable[[ClassificacaoManutencao, str, bool], TicketManutencao]

# Assinatura esperada de quem registra o escalonamento (agent_create_escalation).
CriarEscalonamentoFn = Callable[[str, str], None]


class EstadoAtendimentoManutencao(BaseModel):
    etapa: EtapaAtendimento = "aguardando_confirmacao_imovel"
    tentativas_identificacao: int = 0
    tentativas_esclarecimento: int = 0
    descricao_livre: str = ""
    classificacao_inicial: Optional[ClassificacaoManutencao] = None


class ResultadoTurno(BaseModel):
    estado: EstadoAtendimentoManutencao
    resposta_inquilino: str
    ticket: Optional[TicketManutencao] = None
    notificacao_gestora: Optional[str] = None
    # NOVO (checkup pós-WA-06/WA-08, Ponto 3): parâmetros posicionais pro
    # template manutencao_equipe (protocolo, imóvel, categoria, urgência,
    # descrição) — o que app/agents/a3_manutencao/atendimento.py de fato usa
    # pra notificar a equipe agora. `notificacao_gestora` (texto livre) é
    # mantido por compatibilidade (assinatura pública existente, testes
    # atuais checam esse campo) mas não é mais o que vai no envio real.
    notificacao_gestora_parametros: Optional[list[str]] = None
    escalonado: bool = False


def iniciar_atendimento(imovel_endereco: str, imovel_numero: str) -> ResultadoTurno:
    return ResultadoTurno(
        estado=EstadoAtendimentoManutencao(),
        resposta_inquilino=f"Confirmando: apto {imovel_numero}, {imovel_endereco}?",
    )


def _urgencia_mais_alta(a: UrgenciaManutencao, b: UrgenciaManutencao) -> UrgenciaManutencao:
    return a if _ORDEM_URGENCIA[a] >= _ORDEM_URGENCIA[b] else b


def _confianca_baixa(classificacao: ClassificacaoManutencao) -> bool:
    return (
        classificacao.categoria_confidence < CONFIDENCE_MINIMA_CATEGORIA
        or classificacao.urgencia_confidence < CONFIDENCE_MINIMA_URGENCIA
    )


def _parece_confusao(mensagem: str) -> bool:
    normalizado = mensagem.strip().lower().rstrip("?!. ")
    return normalizado in _MARCADORES_CONFUSAO or len(normalizado) <= 2


def _abrir_ticket_e_notificar(
    estado: EstadoAtendimentoManutencao,
    classificacao: ClassificacaoManutencao,
    descricao_inquilino: str,
    imovel_endereco: str,
    imovel_numero: str,
    abrir_ticket_fn: AbrirTicketFn,
    classificacao_incerta: bool = False,
) -> ResultadoTurno:
    ticket = abrir_ticket_fn(classificacao, descricao_inquilino, classificacao_incerta)
    notificacao = montar_notificacao_gestora(ticket, imovel_endereco, imovel_numero, descricao_inquilino)
    parametros_notificacao = montar_parametros_notificacao_gestora(
        ticket, imovel_endereco, imovel_numero, descricao_inquilino
    )
    resposta = montar_confirmacao_inquilino(ticket)

    return ResultadoTurno(
        estado=estado.model_copy(update={"etapa": "finalizado"}),
        resposta_inquilino=resposta,
        ticket=ticket,
        notificacao_gestora=notificacao,
        notificacao_gestora_parametros=parametros_notificacao,
    )


def processar_turno(
    estado: EstadoAtendimentoManutencao,
    mensagem: str,
    *,
    imovel_endereco: str,
    imovel_numero: str,
    abrir_ticket_fn: AbrirTicketFn,
    criar_escalonamento_fn: CriarEscalonamentoFn,
    classificar_fn: Callable[[str], ClassificacaoManutencao] = classificar_manutencao,
    gerar_pergunta_fn: Callable[[str, ClassificacaoManutencao], str] = gerar_pergunta_esclarecimento,
) -> ResultadoTurno:
    texto = mensagem.strip().lower()

    if estado.etapa == "aguardando_confirmacao_imovel":
        confirmou = contem_palavra(texto, _PALAVRAS_CONFIRMACAO) and not contem_palavra(
            texto, _PALAVRAS_NEGACAO
        )
        if confirmou:
            return ResultadoTurno(
                estado=estado.model_copy(update={"etapa": "aguardando_descricao"}),
                resposta_inquilino="Perfeito. Me conta o que está acontecendo?",
            )

        tentativas = estado.tentativas_identificacao + 1
        if tentativas >= MAX_TENTATIVAS_IDENTIFICACAO:
            criar_escalonamento_fn(
                "pedido_humano",
                f"Falha ao confirmar identificação do imóvel após {tentativas} tentativa(s).",
            )
            return ResultadoTurno(
                estado=estado.model_copy(
                    update={"etapa": "finalizado", "tentativas_identificacao": tentativas}
                ),
                resposta_inquilino="Vou te encaminhar para um atendente humano confirmar seus dados.",
                escalonado=True,
            )

        return ResultadoTurno(
            estado=estado.model_copy(update={"tentativas_identificacao": tentativas}),
            resposta_inquilino="Pra abrir o chamado, me confirma o endereço/apto?",
        )

    if estado.etapa == "aguardando_descricao":
        classificacao = classificar_fn(mensagem)

        if _confianca_baixa(classificacao):
            return ResultadoTurno(
                estado=estado.model_copy(
                    update={
                        "etapa": "aguardando_esclarecimento",
                        "descricao_livre": mensagem,
                        "classificacao_inicial": classificacao,
                    }
                ),
                resposta_inquilino=gerar_pergunta_fn(mensagem, classificacao),
            )

        return _abrir_ticket_e_notificar(
            estado, classificacao, classificacao.descricao_formatada, imovel_endereco, imovel_numero, abrir_ticket_fn
        )

    if estado.etapa == "aguardando_esclarecimento":
        tentativas = estado.tentativas_esclarecimento + 1

        # "hein?", "oi", "?" — não é uma tentativa de responder a pergunta de
        # esclarecimento, é confusão/mensagem fora de contexto. Repete a
        # mesma pergunta em vez de fechar o ticket com isso colado na
        # descrição (bug real: virava "tem uma mancha esquisita perto do
        # chuveiro hein?" no chamado). Limitado por MAX_TENTATIVAS_ESCLARECIMENTO
        # pra não entrar em loop se a pessoa nunca responder de verdade.
        if (
            _parece_confusao(mensagem)
            and tentativas < MAX_TENTATIVAS_ESCLARECIMENTO
            and estado.classificacao_inicial is not None
        ):
            return ResultadoTurno(
                estado=estado.model_copy(update={"tentativas_esclarecimento": tentativas}),
                resposta_inquilino=gerar_pergunta_fn(estado.descricao_livre, estado.classificacao_inicial),
            )

        descricao_combinada = f"{estado.descricao_livre} {mensagem}".strip()
        reclassificacao = classificar_fn(descricao_combinada)

        confianca_ainda_baixa = _confianca_baixa(reclassificacao)

        classificacao_final = reclassificacao
        if confianca_ainda_baixa and estado.classificacao_inicial is not None:
            urgencia_conservadora = _urgencia_mais_alta(
                estado.classificacao_inicial.urgencia, reclassificacao.urgencia
            )
            classificacao_final = reclassificacao.model_copy(update={"urgencia": urgencia_conservadora})

        return _abrir_ticket_e_notificar(
            estado,
            classificacao_final,
            classificacao_final.descricao_formatada,
            imovel_endereco,
            imovel_numero,
            abrir_ticket_fn,
            classificacao_incerta=confianca_ainda_baixa,
        )

    return ResultadoTurno(estado=estado, resposta_inquilino="Este chamado já foi encerrado.")
