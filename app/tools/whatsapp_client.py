"""Cliente centralizado da WhatsApp Cloud API (Meta) — Projeto Domingos.

WA-01 (esta entrega): fundação — configuração, tipos, exceções e o kill
switch (WHATSAPP_ENVIO_ATIVO). Os quatro fluxos HTTP completos (texto,
template, botões, download de mídia) chegam em WA-02/WA-03; aqui só stubs
públicos e documentados, que já respeitam o kill switch e a validação de
configuração — nenhuma chamada de rede acontece nesta task.

Pontos que hoje só logam (`app/agents/a2_cobranca/notificacao.py`,
`app/agents/a5_escalonamento/notificacao.py`) serão migrados para este
cliente em WA-05/WA-06/WA-09 — não são tocados por esta task.
"""

import logging
import os
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Timeout padrão (segundos) para toda chamada HTTP deste cliente — nenhuma
# chamada à Meta deve ficar pendurada indefinidamente (regra comum da
# sprint: "toda chamada HTTP deve ter timeout explícito"). Curto o
# suficiente pra não segurar um BackgroundTask do webhook, generoso o
# suficiente pra upload/download de mídia em rede instável. WA-02/WA-03
# passam este valor ao client httpx.
TIMEOUT_PADRAO_SEGUNDOS = 15.0

# Fallback usado somente quando WHATSAPP_GRAPH_API_VERSION não está setada
# no ambiente — a variável de ambiente tem SEMPRE prioridade (ver
# montar_url_base). Isto não é "escolher uma versão fixa sem permitir
# configuração": é só o valor padrão de uma config que continua 100%
# sobrescrevível.
_GRAPH_API_VERSION_PADRAO = "v21.0"

_VALORES_BOOLEANOS_VERDADEIROS = {"1", "true", "t", "yes", "y", "on"}
_VALORES_BOOLEANOS_FALSOS = {"0", "false", "f", "no", "n", "off", ""}


# ======================================================================
# Exceções
# ======================================================================


class WhatsAppError(Exception):
    """Base de todas as exceções deste módulo."""


class WhatsAppConfigError(WhatsAppError):
    """Configuração ausente ou inválida para realizar uma operação real
    (ex: envio ativo mas falta WHATSAPP_ACCESS_TOKEN/WHATSAPP_PHONE_NUMBER_ID).
    A mensagem sempre lista quais variáveis faltam pelo NOME — nunca inclui
    o valor de nenhuma variável de configuração."""


class WhatsAppTransientError(WhatsAppError):
    """Erro transitório da Meta — timeout, falha de conexão, HTTP 429 ou
    5xx. Elegível a retry; a política de quantas vezes/quando é definida em
    WA-02, esta classe só marca a categoria do erro."""


class WhatsAppPermanentError(WhatsAppError):
    """Erro permanente da Meta — HTTP 4xx (exceto 429). Repetir a mesma
    chamada sem mudar o payload não vai funcionar; não deve ser retentado."""


class WhatsAppConteudoInvalidoError(WhatsAppError):
    """Conteúdo fornecido pelo chamador não é válido para o transporte (ex:
    mais de 3 botões, título vazio, MIME não permitido, arquivo grande
    demais). Levantada ANTES de qualquer chamada HTTP — validação é sempre
    local, nunca descoberta só depois de gastar uma request na Meta."""


# ======================================================================
# Tipos de resultado
# ======================================================================


class ResultadoEnvio(BaseModel):
    """Resultado de uma operação de envio (texto, template ou botões).

    `simulado=True` quando WHATSAPP_ENVIO_ATIVO está desligado (ou ausente):
    nenhuma chamada HTTP foi feita e `message_id` é sempre None nesse caso.
    Consumidores que só precisam saber "foi tratado sem erro" checam
    `sucesso`; quem precisa reconciliar com a Meta depois (ex: matching de
    status de entrega, fora do escopo desta sprint) usa `message_id`.
    """

    sucesso: bool
    simulado: bool
    message_id: Optional[str] = None
    detalhe: Optional[str] = None


class ResultadoMidia(BaseModel):
    """Resultado do download de mídia (implementado em WA-03) — bytes brutos
    e o MIME reportado pela Meta. Definido já nesta fundação porque
    `baixar_midia` precisa de uma assinatura de retorno estável desde o
    stub, mesmo sem implementação ainda."""

    conteudo: bytes
    mime_type: str


# ======================================================================
# Configuração / kill switch
# ======================================================================


def _parse_bool_env(valor: Optional[str], padrao: bool) -> bool:
    """Parsing booleano seguro de variável de ambiente — nunca lança.
    Qualquer valor não reconhecido cai no padrão (mais seguro exigir um
    'true' explícito do que arriscar interpretar algo incerto como
    verdadeiro, já que o padrão do kill switch é desligado)."""
    if valor is None:
        return padrao
    normalizado = valor.strip().lower()
    if normalizado in _VALORES_BOOLEANOS_VERDADEIROS:
        return True
    if normalizado in _VALORES_BOOLEANOS_FALSOS:
        return False
    logger.warning(
        "WHATSAPP_ENVIO_ATIVO=%r não reconhecido como valor booleano — usando padrão (%s).",
        valor,
        padrao,
    )
    return padrao


def envio_ativo() -> bool:
    """Kill switch: True somente com WHATSAPP_ENVIO_ATIVO explicitamente
    truthy no ambiente ('1', 'true', 'yes', 'on', case-insensitive). Padrão
    é False — nasce travado, precisa ser ligado de propósito (mesmo
    espírito de RLS fail-closed na Migration 001: mais seguro nascer
    bloqueado e abrir depois do que o contrário)."""
    return _parse_bool_env(os.environ.get("WHATSAPP_ENVIO_ATIVO"), padrao=False)


def _graph_api_version() -> str:
    return os.environ.get("WHATSAPP_GRAPH_API_VERSION") or _GRAPH_API_VERSION_PADRAO


def montar_url_graph_api() -> str:
    """https://graph.facebook.com/{versao} — base comum a qualquer endpoint
    da Graph API, incluindo os que não dependem de phone_number_id (ex:
    GET /{media_id} do download de mídia em WA-03)."""
    return f"https://graph.facebook.com/{_graph_api_version()}"


def _phone_number_id_obrigatorio() -> str:
    valor = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if not valor:
        raise WhatsAppConfigError(
            "WHATSAPP_PHONE_NUMBER_ID não configurado — necessário para enviar mensagens reais."
        )
    return valor


def _access_token_obrigatorio() -> str:
    valor = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    if not valor:
        raise WhatsAppConfigError(
            "WHATSAPP_ACCESS_TOKEN não configurado — necessário para enviar mensagens reais."
        )
    return valor


def montar_url_base() -> str:
    """https://graph.facebook.com/{versao}/{phone_number_id} — URL usada
    pelos envios de texto/template/botões (WA-02/WA-03). Levanta
    WhatsAppConfigError se WHATSAPP_PHONE_NUMBER_ID não estiver configurado;
    a versão da Graph API vem sempre de montar_url_graph_api(), nunca fixa
    aqui dentro."""
    return f"{montar_url_graph_api()}/{_phone_number_id_obrigatorio()}"


def validar_configuracao_envio_real() -> None:
    """Chamada no início de cada operação real (WA-02/WA-03) antes de
    montar qualquer request. Levanta WhatsAppConfigError listando pelo NOME
    quais variáveis faltam — nunca inclui o valor de nenhuma delas na
    mensagem nem em log."""
    faltando = [
        nome
        for nome, valor in (
            ("WHATSAPP_PHONE_NUMBER_ID", os.environ.get("WHATSAPP_PHONE_NUMBER_ID")),
            ("WHATSAPP_ACCESS_TOKEN", os.environ.get("WHATSAPP_ACCESS_TOKEN")),
        )
        if not valor
    ]
    if faltando:
        raise WhatsAppConfigError(
            "Envio real está ativo (WHATSAPP_ENVIO_ATIVO=true) mas faltam variáveis de "
            f"configuração: {', '.join(faltando)}."
        )


def _headers_autenticados() -> dict:
    """Headers para uma chamada real à Graph API. Só deve ser chamada depois
    de validar_configuracao_envio_real() ter passado sem lançar. O valor do
    token nunca deve ser logado — só passado aqui, direto pro header."""
    return {
        "Authorization": f"Bearer {_access_token_obrigatorio()}",
        "Content-Type": "application/json",
    }


# ======================================================================
# Logging seguro
# ======================================================================


def mascarar_telefone(telefone: str) -> str:
    """Mantém só os 4 últimos dígitos visíveis, pro log identificar o
    destino sem expor o número completo. Compartilhado por todas as
    funções de envio (WA-02 loga 'operação, telefone mascarado, status e
    message_id' — helper centralizado aqui pra não duplicar a lógica em
    cada uma)."""
    digitos = "".join(c for c in telefone if c.isdigit())
    if len(digitos) <= 4:
        return "*" * len(digitos)
    return "*" * (len(digitos) - 4) + digitos[-4:]


def _log_operacao(operacao: str, telefone: Optional[str] = None, **detalhes: object) -> None:
    """Log estruturado seguro: nunca recebe o access token como argumento;
    telefone é sempre mascarado antes de sair daqui. Usar em toda função de
    envio/download deste módulo em vez de logger.info direto, para manter
    o mascaramento garantido num único ponto."""
    partes = [f"operacao={operacao}"]
    if telefone is not None:
        partes.append(f"telefone={mascarar_telefone(telefone)}")
    partes.extend(f"{chave}={valor}" for chave, valor in detalhes.items())
    logger.info("whatsapp_client: %s", " ".join(partes))


# ======================================================================
# Stubs públicos — implementação HTTP completa chega em WA-02 (texto e
# template) e WA-03 (botões e mídia). Todos já respeitam o kill switch:
# com envio inativo, retornam simulado sem tentar rede.
# ======================================================================


def enviar_texto(telefone: str, texto: str) -> ResultadoEnvio:
    """Envia uma mensagem de texto livre. Só é aceito pela Meta dentro da
    janela de 24h desde a última mensagem do destinatário — a decisão de
    quando usar texto vs. template é responsabilidade de quem chama (regra
    completa em WA-08), este cliente só transporta o que foi decidido.

    Implementação HTTP completa: WA-02. Aqui, com envio ativo, valida
    configuração e sinaliza que o transporte real ainda não existe — não
    finge sucesso.
    """
    if not envio_ativo():
        _log_operacao("enviar_texto", telefone, simulado=True)
        return ResultadoEnvio(sucesso=True, simulado=True)
    validar_configuracao_envio_real()
    raise NotImplementedError(
        "enviar_texto: transporte HTTP real ainda não implementado (chega em WA-02)."
    )


def enviar_template(
    telefone: str, nome: str, parametros: list[str], lang: str = "pt_BR"
) -> ResultadoEnvio:
    """Envia uma mensagem de template pré-aprovado pela Meta — obrigatório
    fora da janela de 24h ou para mensagens proativas (cron de cobrança,
    alertas do A4). `parametros` é posicional, na mesma ordem cadastrada no
    template junto à Meta (catálogo formal: WA-09).

    Implementação HTTP completa: WA-02.
    """
    if not envio_ativo():
        _log_operacao("enviar_template", telefone, simulado=True, template=nome)
        return ResultadoEnvio(sucesso=True, simulado=True)
    validar_configuracao_envio_real()
    raise NotImplementedError(
        "enviar_template: transporte HTTP real ainda não implementado (chega em WA-02)."
    )


def enviar_botoes(telefone: str, corpo: str, botoes: list[dict]) -> ResultadoEnvio:
    """Envia mensagem interativa com até 3 botões nativos (ex: confirmação
    de comprovante do A2 — ver `app/agents/a2_cobranca/button_ids.py` para
    como os IDs são montados/decodificados). `botoes` no formato
    `[{"id": ..., "titulo": ...}, ...]`; validação de quantidade/tamanho
    entra em WA-03, antes de qualquer chamada HTTP.

    Implementação HTTP completa: WA-03.
    """
    if not envio_ativo():
        _log_operacao("enviar_botoes", telefone, simulado=True, n_botoes=len(botoes))
        return ResultadoEnvio(sucesso=True, simulado=True)
    validar_configuracao_envio_real()
    raise NotImplementedError(
        "enviar_botoes: transporte HTTP real ainda não implementado (chega em WA-03)."
    )


def baixar_midia(media_id: str) -> ResultadoMidia:
    """Baixa um arquivo de mídia (comprovante) da Meta em duas etapas: (1)
    GET /{media_id} na Graph API para resolver a URL assinada e temporária
    do arquivo, (2) GET nessa URL para os bytes reais.

    Decisão de design: NÃO respeita o kill switch. Diferente de
    enviar_texto/enviar_template/enviar_botoes (que são ENVIOS, bloqueados
    de propósito por WHATSAPP_ENVIO_ATIVO=false), baixar mídia é uma
    LEITURA de algo que o inquilino já mandou — desligar o kill switch de
    envio não deveria impedir o A2 de processar um comprovante já
    recebido. Ainda assim exige configuração válida (validar_configuracao_
    envio_real), porque a chamada é real e usa o mesmo access token.

    Implementação HTTP completa: WA-03.
    """
    validar_configuracao_envio_real()
    raise NotImplementedError(
        "baixar_midia: transporte HTTP real ainda não implementado (chega em WA-03)."
    )
