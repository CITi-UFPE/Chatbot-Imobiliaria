"""Política central de saída do WhatsApp — texto livre ou template.

A Meta só permite texto livre dentro da janela de atendimento aberta pela
última mensagem do inquilino. Mensagens proativas e respostas fora da janela
precisam usar template. Esta regra vive aqui, não dentro de A1/A2/A3/A4/A5.

Fail-closed por desenho: ausência de histórico, timestamp inválido/sem fuso ou
falha de banco nunca libera texto livre. Nesses casos o chamador recebe o
template de fallback que forneceu.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from app.tools import whatsapp_client

logger = logging.getLogger(__name__)

JANELA_ATENDIMENTO = timedelta(hours=24)


class MensagemTexto(BaseModel):
    """Saída de texto livre, válida somente após a política autorizá-la."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: Literal["texto"] = "texto"
    texto: str = Field(min_length=1)


class BotaoTemplateQuickReply(BaseModel):
    """Payload dinâmico de um botão quick reply já cadastrado no template.

    O título é definido no WhatsApp Manager. A posição nesta tupla determina
    o índice do botão e precisa seguir a mesma ordem cadastrada na Meta.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: Literal["quick_reply"] = "quick_reply"
    payload: str = Field(min_length=1, max_length=256)


class MensagemTemplate(BaseModel):
    """Template Meta com corpo e quick replies na ordem cadastrada."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: Literal["template"] = "template"
    nome: str = Field(min_length=1)
    idioma: str = Field(default="pt_BR", min_length=1)
    parametros: tuple[str, ...] = ()
    botoes: tuple[BotaoTemplateQuickReply, ...] = Field(default=(), max_length=3)


SaidaWhatsApp: TypeAlias = MensagemTexto | MensagemTemplate

TEMPLATE_RETOMADA_ATENDIMENTO = MensagemTemplate(
    nome="retomada_atendimento",
    idioma="pt_BR",
    parametros=(),
)


def _normalizar_timestamp(valor: object) -> datetime:
    """Converte o retorno timestamptz do Supabase para datetime aware.

    Supabase normalmente devolve ISO 8601 como string, mas testes e outros
    adaptadores podem devolver ``datetime`` diretamente. Datetime ingênuo é
    recusado: assumir silenciosamente o timezone do host abriria a janela sem
    evidência confiável.
    """
    if isinstance(valor, datetime):
        resultado = valor
    elif isinstance(valor, str):
        texto = valor.strip()
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        resultado = datetime.fromisoformat(texto)
    else:
        raise ValueError(f"Timestamp de última mensagem em formato inválido: {type(valor).__name__}")

    if resultado.tzinfo is None or resultado.utcoffset() is None:
        raise ValueError("Timestamp da última mensagem não possui timezone.")
    return resultado.astimezone(timezone.utc)


def buscar_ultima_mensagem_inquilino(client) -> datetime | None:
    """Consulta a última mensagem recebida no contrato do client escopado.

    A RPC não recebe ``contract_id``: ela usa ``agent_contract_id()`` a partir
    do JWT do próprio client, preservando o isolamento no banco.
    """
    resposta = client.rpc("agent_get_last_tenant_message_at", {}).execute()
    if resposta.data is None:
        return None
    return _normalizar_timestamp(resposta.data)


def janela_atendimento_aberta(
    ultima_mensagem_inquilino: datetime | None,
    *,
    agora: datetime | None = None,
) -> bool:
    """Retorna True apenas para idade no intervalo ``[0, 24h)``.

    Exatamente 24 horas fecha a janela. Timestamp futuro, ausente ou sem fuso
    é indeterminado e, portanto, retorna False.
    """
    if ultima_mensagem_inquilino is None:
        return False
    if ultima_mensagem_inquilino.tzinfo is None or ultima_mensagem_inquilino.utcoffset() is None:
        return False

    instante_atual = agora or datetime.now(timezone.utc)
    if instante_atual.tzinfo is None or instante_atual.utcoffset() is None:
        raise ValueError("O instante atual usado na política precisa possuir timezone.")

    idade = instante_atual.astimezone(timezone.utc) - ultima_mensagem_inquilino.astimezone(timezone.utc)
    return timedelta(0) <= idade < JANELA_ATENDIMENTO


def decidir_saida(
    *,
    reativa: bool,
    texto: str,
    template: MensagemTemplate,
    ultima_mensagem_inquilino: datetime | None,
    agora: datetime | None = None,
) -> SaidaWhatsApp:
    """Decisão pura, sem banco e sem transporte.

    Proativo sempre usa template. Reativo só usa texto quando a janela está
    comprovadamente aberta.
    """
    if reativa and janela_atendimento_aberta(ultima_mensagem_inquilino, agora=agora):
        return MensagemTexto(texto=texto)
    return template


def decidir_saida_para_contrato(
    client,
    *,
    reativa: bool,
    texto: str,
    template: MensagemTemplate,
    agora: datetime | None = None,
) -> SaidaWhatsApp:
    """Consulta o histórico quando necessário e aplica fallback seguro.

    ``client=None`` representa fluxos em que o contrato nem chegou a ser
    resolvido. Sem client escopado não existe como provar a janela; retorna o
    template sem tentar consulta genérica/cross-contrato.
    """
    if not reativa:
        return template
    if client is None:
        return template

    try:
        ultima_mensagem = buscar_ultima_mensagem_inquilino(client)
    except Exception:
        logger.exception(
            "Falha ao consultar última mensagem do inquilino; usando template por segurança."
        )
        return template

    return decidir_saida(
        reativa=True,
        texto=texto,
        template=template,
        ultima_mensagem_inquilino=ultima_mensagem,
        agora=agora,
    )


def enviar_saida(telefone: str, saida: SaidaWhatsApp):
    """Transporta a saída já decidida pelo cliente central da Meta."""
    if isinstance(saida, MensagemTexto):
        return whatsapp_client.enviar_texto(telefone, saida.texto)
    argumentos_botoes = {}
    if saida.botoes:
        argumentos_botoes["botoes"] = [botao.payload for botao in saida.botoes]
    return whatsapp_client.enviar_template(
        telefone,
        saida.nome,
        list(saida.parametros),
        lang=saida.idioma,
        **argumentos_botoes,
    )
