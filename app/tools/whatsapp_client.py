"""Cliente centralizado da WhatsApp Cloud API (Meta) — Projeto Domingos.

WA-01: fundação — configuração, tipos, exceções e o kill switch
(WHATSAPP_ENVIO_ATIVO).
WA-02: transporte HTTP real de enviar_texto/enviar_template, com retry
seletivo (tenacity) para falha de conexão/timeout/429/5xx, e NENHUM retry
para erro permanente (4xx).
WA-03 (esta entrega): enviar_botoes (mensagem interativa, 1-3 botões,
validados ANTES de qualquer chamada HTTP) e baixar_midia (download real em
duas etapas: metadados + arquivo, com MIME/tamanho validados e leitura em
streaming com limite, pra nunca acumular um arquivo arbitrariamente grande
inteiro na memória).

Pontos que hoje só logam (`app/agents/a2_cobranca/notificacao.py`,
`app/agents/a5_escalonamento/notificacao.py`) serão migrados para este
cliente em WA-05/WA-06/WA-09 — não são tocados por esta task.
"""

import logging
import os
from typing import Optional

import httpx
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Timeout padrão (segundos) para toda chamada HTTP deste cliente — nenhuma
# chamada à Meta deve ficar pendurada indefinidamente (regra comum da
# sprint: "toda chamada HTTP deve ter timeout explícito"). Curto o
# suficiente pra não segurar um BackgroundTask do webhook, generoso o
# suficiente pra upload/download de mídia em rede instável. WA-02/WA-03
# passam este valor ao client httpx.
TIMEOUT_PADRAO_SEGUNDOS = 15.0

# Política de retry (WA-02) — só para erro TRANSITÓRIO (WhatsAppTransientError):
# falha de conexão/timeout, HTTP 429 ou 5xx. 3 tentativas no total (1 original
# + 2 retries), backoff exponencial curto o bastante para não segurar demais
# um BackgroundTask do webhook nem os crons do A2/A4/A5. Erro PERMANENTE
# (4xx exceto 429) nunca entra aqui — propaga na primeira tentativa.
_RETRY_MAX_TENTATIVAS = 3
_RETRY_ESPERA_MULTIPLICADOR_SEGUNDOS = 0.5
_RETRY_ESPERA_MAX_SEGUNDOS = 4.0

# Fallback usado somente quando WHATSAPP_GRAPH_API_VERSION não está setada
# no ambiente — a variável de ambiente tem SEMPRE prioridade (ver
# montar_url_base). Isto não é "escolher uma versão fixa sem permitir
# configuração": é só o valor padrão de uma config que continua 100%
# sobrescrevível.
_GRAPH_API_VERSION_PADRAO = "v21.0"

_VALORES_BOOLEANOS_VERDADEIROS = {"1", "true", "t", "yes", "y", "on"}
_VALORES_BOOLEANOS_FALSOS = {"0", "false", "f", "no", "n", "off", ""}

# Limites de um botão de interactive message impostos pela própria Meta
# Cloud API (WA-03) — validados localmente ANTES de qualquer request, pra
# nunca gastar uma chamada HTTP com um payload que a Meta rejeitaria de
# qualquer forma.
_MAX_BOTOES = 3
_MAX_TITULO_BOTAO_CARACTERES = 20
_MAX_ID_BOTAO_CARACTERES = 256

# MIME permitidos para comprovante (imagens comuns + PDF) e tamanho máximo
# de mídia aceito por download (WA-03) — configurável via
# WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB, com um padrão conservador. Ver
# _tamanho_maximo_midia_bytes().
_MIME_PERMITIDOS_COMPROVANTE = frozenset(
    {"image/jpeg", "image/png", "image/webp", "application/pdf"}
)
_TAMANHO_MAXIMO_MIDIA_BYTES_PADRAO = 10 * 1024 * 1024  # 10 MB


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


def telefone_staff() -> str:
    """Telefone (E.164) que recebe notificações dirigidas À EQUIPE (não ao
    inquilino) — WHATSAPP_STAFF_PHONE_NUMBER, reaproveitado por
    app/agents/a4_gestao_contratual/fluxo.py e
    app/agents/a5_escalonamento/notificacao.py, centralizado aqui pra não
    duplicar a mesma checagem em cada consumidor (os dois tinham cópias
    quase idênticas de "_telefone_staff" até a WA-05). RuntimeError (não
    WhatsAppConfigError) de propósito: mantém compatibilidade com os testes
    já escritos contra esse comportamento em ambos os agentes."""
    valor = os.environ.get("WHATSAPP_STAFF_PHONE_NUMBER")
    if not valor:
        raise RuntimeError(
            "WHATSAPP_STAFF_PHONE_NUMBER não configurado — necessário para notificar a "
            "equipe (envio está ativo, mas falta o destino)."
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
# Transporte HTTP (WA-02)
# ======================================================================


def _construir_client() -> httpx.Client:
    """Fábrica do client httpx usado pelas chamadas deste módulo — criado
    sob demanda a cada chamada, não um client global mutável (restrição da
    WA-01). Isolado numa função própria só para os testes poderem trocar o
    transport por um httpx.MockTransport via monkeypatch, sem precisar
    mockar cada chamada individualmente."""
    return httpx.Client(timeout=TIMEOUT_PADRAO_SEGUNDOS)


def _normalizar_destino(telefone: str) -> str:
    """Normalização MÍNIMA do destino pro campo 'to' do payload — só
    dígitos, sem formatação de apresentação (+, espaços, parênteses,
    hífen). NÃO resolve DDI/DDD/nono dígito nem gera variantes brasileiras
    — isso é escopo da WA-07, na resolução de contrato por telefone; aqui o
    número já chega pronto para ser usado como identificador do WhatsApp."""
    digitos = "".join(c for c in telefone if c.isdigit())
    if not digitos:
        raise WhatsAppConteudoInvalidoError(f"Telefone inválido para envio: {telefone!r}")
    return digitos


def _resumo_erro_meta(resposta: httpx.Response) -> str:
    """Extrai code/message do corpo de erro padrão da Meta
    ({"error": {"message": ..., "code": ...}}) para a exceção/log ficarem
    legíveis sem precisar despejar o corpo inteiro da resposta. Nunca inclui
    header nem o access token — só o corpo JSON de erro, que é público (é o
    que a própria Meta devolveu)."""
    try:
        corpo = resposta.json()
    except ValueError:
        return resposta.text[:200]
    erro = corpo.get("error", {}) if isinstance(corpo, dict) else {}
    if not erro:
        return resposta.text[:200]
    return f"code={erro.get('code')} message={erro.get('message')}"


def _classificar_resposta(resposta: httpx.Response) -> httpx.Response:
    """Ponto único de decisão "isso é transitório, permanente, ou ok?" —
    compartilhado entre POST (WA-02) e GET (WA-03) pra não duplicar a
    classificação de status code em dois lugares."""
    if resposta.status_code == 429 or resposta.status_code >= 500:
        raise WhatsAppTransientError(
            f"Erro transitório da Meta (HTTP {resposta.status_code}): {_resumo_erro_meta(resposta)}"
        )
    if resposta.status_code >= 400:
        raise WhatsAppPermanentError(
            f"Erro permanente da Meta (HTTP {resposta.status_code}): {_resumo_erro_meta(resposta)}"
        )
    return resposta


@retry(
    retry=retry_if_exception_type(WhatsAppTransientError),
    stop=stop_after_attempt(_RETRY_MAX_TENTATIVAS),
    wait=wait_exponential(multiplier=_RETRY_ESPERA_MULTIPLICADOR_SEGUNDOS, max=_RETRY_ESPERA_MAX_SEGUNDOS),
    reraise=True,
)
def _post_com_retry(url: str, payload: dict, headers: dict) -> httpx.Response:
    """Uma tentativa de POST — decorada com retry seletivo: só
    WhatsAppTransientError (falha de rede, 429, 5xx) é retentado, até
    _RETRY_MAX_TENTATIVAS vezes com backoff exponencial. WhatsAppPermanentError
    (4xx) propaga na primeira tentativa, sem retry."""
    try:
        with _construir_client() as client:
            resposta = client.post(url, json=payload, headers=headers)
    except httpx.RequestError as erro:
        # Cobre timeout E falha de conexão — httpx.TimeoutException e
        # httpx.TransportError são ambas subclasses de httpx.RequestError.
        raise WhatsAppTransientError(f"Falha de rede ao chamar a Graph API: {erro}") from erro
    return _classificar_resposta(resposta)


@retry(
    retry=retry_if_exception_type(WhatsAppTransientError),
    stop=stop_after_attempt(_RETRY_MAX_TENTATIVAS),
    wait=wait_exponential(multiplier=_RETRY_ESPERA_MULTIPLICADOR_SEGUNDOS, max=_RETRY_ESPERA_MAX_SEGUNDOS),
    reraise=True,
)
def _get_com_retry(url: str, headers: dict) -> httpx.Response:
    """Mesma política de retry do POST (WA-02), usada pelo GET de metadados
    de mídia (WA-03) — não pelo download do arquivo em si, que usa streaming
    com limite de tamanho (ver _baixar_arquivo_com_limite)."""
    try:
        with _construir_client() as client:
            resposta = client.get(url, headers=headers)
    except httpx.RequestError as erro:
        raise WhatsAppTransientError(f"Falha de rede ao chamar a Graph API: {erro}") from erro
    return _classificar_resposta(resposta)


def _extrair_message_id(corpo: dict) -> Optional[str]:
    mensagens = corpo.get("messages") or []
    if not mensagens:
        return None
    return mensagens[0].get("id")


def _enviar_mensagem(payload: dict, telefone: str, operacao: str, **detalhes_log: object) -> ResultadoEnvio:
    """Caminho comum a enviar_texto/enviar_template depois que o payload já
    está montado: chama a Graph API (com retry seletivo), extrai o
    message_id da resposta e loga de forma segura. Levanta WhatsAppError se
    a Meta responder 2xx sem um message_id reconhecível — resposta nesse
    formato é inesperada, não deve ser tratada como sucesso silencioso."""
    url = f"{montar_url_base()}/messages"
    headers = _headers_autenticados()
    resposta = _post_com_retry(url, payload, headers)

    try:
        corpo = resposta.json()
    except ValueError as erro:
        raise WhatsAppError(f"Resposta 2xx da Meta com corpo não-JSON para {operacao}.") from erro

    message_id = _extrair_message_id(corpo)
    if message_id is None:
        raise WhatsAppError(
            f"Resposta 2xx da Meta sem message_id reconhecível para {operacao} "
            f"(telefone {mascarar_telefone(telefone)})."
        )

    _log_operacao(operacao, telefone, status=resposta.status_code, message_id=message_id, **detalhes_log)
    return ResultadoEnvio(sucesso=True, simulado=False, message_id=message_id)


def enviar_texto(telefone: str, texto: str) -> ResultadoEnvio:
    """Envia uma mensagem de texto livre. Só é aceito pela Meta dentro da
    janela de 24h desde a última mensagem do destinatário — a decisão de
    quando usar texto vs. template é responsabilidade de quem chama (regra
    completa em WA-08), este cliente só transporta o que foi decidido.
    """
    if not envio_ativo():
        _log_operacao("enviar_texto", telefone, simulado=True)
        return ResultadoEnvio(sucesso=True, simulado=True)

    validar_configuracao_envio_real()
    destino = _normalizar_destino(telefone)
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "text",
        "text": {"body": texto},
    }
    return _enviar_mensagem(payload, telefone, operacao="enviar_texto")


def _validar_botoes_template(botoes: list[str]) -> None:
    """Valida payloads dos quick replies de um template.

    Os títulos já pertencem ao template aprovado; no envio informamos apenas
    os payloads dinâmicos, na mesma ordem dos botões cadastrados.
    """
    if len(botoes) > _MAX_BOTOES:
        raise WhatsAppConteudoInvalidoError(
            f"enviar_template aceita até {_MAX_BOTOES} botões, recebido {len(botoes)}."
        )
    for indice, payload in enumerate(botoes):
        if not payload:
            raise WhatsAppConteudoInvalidoError(
                f"Botão de template {indice}: payload vazio."
            )
        if len(payload) > _MAX_ID_BOTAO_CARACTERES:
            raise WhatsAppConteudoInvalidoError(
                f"Botão de template {indice}: payload com {len(payload)} caracteres, "
                f"máximo {_MAX_ID_BOTAO_CARACTERES}."
            )


def enviar_template(
    telefone: str,
    nome: str,
    parametros: list[str],
    lang: str = "pt_BR",
    *,
    botoes: Optional[list[str]] = None,
) -> ResultadoEnvio:
    """Envia uma mensagem de template pré-aprovado pela Meta — obrigatório
    fora da janela de 24h ou para mensagens proativas (cron de cobrança,
    alertas do A4). `parametros` é posicional, na MESMA ordem cadastrada no
    template junto à Meta (catálogo formal: WA-09) — viram o componente
    `body` da mensagem, um por variável `{{n}}` do template. `botoes`
    contém somente os payloads dinâmicos dos quick replies, na ordem dos
    botões cadastrados no template; os títulos não são enviados aqui.
    """
    payloads_botoes = botoes or []
    _validar_botoes_template(payloads_botoes)

    if not envio_ativo():
        _log_operacao(
            "enviar_template",
            telefone,
            simulado=True,
            template=nome,
            n_botoes=len(payloads_botoes),
        )
        return ResultadoEnvio(sucesso=True, simulado=True)

    validar_configuracao_envio_real()
    destino = _normalizar_destino(telefone)
    template: dict = {"name": nome, "language": {"code": lang}}
    componentes: list[dict] = []
    if parametros:
        componentes.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": parametro} for parametro in parametros],
            }
        )
    componentes.extend(
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(indice),
            "parameters": [{"type": "payload", "payload": payload}],
        }
        for indice, payload in enumerate(payloads_botoes)
    )
    if componentes:
        template["components"] = componentes
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "template",
        "template": template,
    }
    return _enviar_mensagem(
        payload,
        telefone,
        operacao="enviar_template",
        template=nome,
        n_botoes=len(payloads_botoes),
    )


def _validar_botoes(botoes: list[dict]) -> None:
    """Valida quantidade e formato dos botões ANTES de qualquer chamada
    HTTP e independente do kill switch — entrada inválida é inválida mesmo
    em modo simulado; não faz sentido "simular sucesso" pra um payload que
    a Meta rejeitaria. Limites: 1 a 3 botões (Meta não aceita 0 nem mais de
    3), título não vazio até 20 caracteres, id não vazio até 256
    caracteres (mesmo limite assumido pelo formato de
    app/agents/a2_cobranca/button_ids.py)."""
    if not (1 <= len(botoes) <= _MAX_BOTOES):
        raise WhatsAppConteudoInvalidoError(
            f"enviar_botoes aceita de 1 a {_MAX_BOTOES} botões, recebido {len(botoes)}."
        )
    for indice, botao in enumerate(botoes):
        titulo = botao.get("titulo") or ""
        id_botao = botao.get("id") or ""
        if not titulo:
            raise WhatsAppConteudoInvalidoError(f"Botão {indice}: título vazio.")
        if len(titulo) > _MAX_TITULO_BOTAO_CARACTERES:
            raise WhatsAppConteudoInvalidoError(
                f"Botão {indice}: título com {len(titulo)} caracteres, "
                f"máximo {_MAX_TITULO_BOTAO_CARACTERES}."
            )
        if not id_botao:
            raise WhatsAppConteudoInvalidoError(f"Botão {indice}: id vazio.")
        if len(id_botao) > _MAX_ID_BOTAO_CARACTERES:
            raise WhatsAppConteudoInvalidoError(
                f"Botão {indice}: id com {len(id_botao)} caracteres, "
                f"máximo {_MAX_ID_BOTAO_CARACTERES}."
            )


def enviar_botoes(telefone: str, corpo: str, botoes: list[dict]) -> ResultadoEnvio:
    """Envia mensagem interativa com até 3 botões nativos (ex: confirmação
    de comprovante do A2 — ver `app/agents/a2_cobranca/button_ids.py` para
    como os IDs são montados/decodificados, este cliente só transporta IDs
    já prontos, nunca monta ID de negócio). `botoes` no formato
    `[{"id": ..., "titulo": ...}, ...]`.
    """
    _validar_botoes(botoes)

    if not envio_ativo():
        _log_operacao("enviar_botoes", telefone, simulado=True, n_botoes=len(botoes))
        return ResultadoEnvio(sucesso=True, simulado=True)

    validar_configuracao_envio_real()
    destino = _normalizar_destino(telefone)
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": corpo},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": botao["id"], "title": botao["titulo"]}}
                    for botao in botoes
                ]
            },
        },
    }
    return _enviar_mensagem(payload, telefone, operacao="enviar_botoes", n_botoes=len(botoes))


def _tamanho_maximo_midia_bytes() -> int:
    """Limite de tamanho de mídia aceito, configurável via
    WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB (float, em megabytes). Valor ausente ou
    não numérico cai no padrão conservador (10 MB) — nunca lança."""
    valor = os.environ.get("WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB")
    if not valor:
        return _TAMANHO_MAXIMO_MIDIA_BYTES_PADRAO
    try:
        megabytes = float(valor)
    except ValueError:
        logger.warning(
            "WHATSAPP_MIDIA_TAMANHO_MAXIMO_MB=%r inválido — usando padrão (%s bytes).",
            valor,
            _TAMANHO_MAXIMO_MIDIA_BYTES_PADRAO,
        )
        return _TAMANHO_MAXIMO_MIDIA_BYTES_PADRAO
    return int(megabytes * 1024 * 1024)


@retry(
    retry=retry_if_exception_type(WhatsAppTransientError),
    stop=stop_after_attempt(_RETRY_MAX_TENTATIVAS),
    wait=wait_exponential(multiplier=_RETRY_ESPERA_MULTIPLICADOR_SEGUNDOS, max=_RETRY_ESPERA_MAX_SEGUNDOS),
    reraise=True,
)
def _baixar_arquivo_com_limite(url: str, headers: dict, limite_bytes: int) -> bytes:
    """Segunda etapa do download — GET em streaming, abortando assim que o
    total acumulado ultrapassa limite_bytes, pra nunca carregar um arquivo
    arbitrariamente grande inteiro na memória só para descobrir depois que
    ele deveria ter sido rejeitado. Mesma política de retry das outras
    chamadas (WA-02): se falhar por rede/429/5xx, a tentativa INTEIRA é
    refeita do zero (sem retomar de onde parou — simplicidade sobre
    otimização, comprovantes não passam de poucos MB)."""
    try:
        with _construir_client() as client:
            with client.stream("GET", url, headers=headers) as resposta:
                if resposta.status_code >= 400:
                    # Corpo de erro da Meta é pequeno — seguro materializar
                    # inteiro só nesse caminho, pra poder classificar/logar
                    # com _resumo_erro_meta (que precisa de .json()/.text,
                    # indisponíveis num Response ainda em streaming).
                    resposta.read()
                    _classificar_resposta(resposta)

                total = 0
                pedacos: list[bytes] = []
                for pedaco in resposta.iter_bytes():
                    total += len(pedaco)
                    if total > limite_bytes:
                        raise WhatsAppConteudoInvalidoError(
                            f"Mídia excede o tamanho máximo permitido ({limite_bytes} bytes) "
                            "durante o download."
                        )
                    pedacos.append(pedaco)
    except httpx.RequestError as erro:
        raise WhatsAppTransientError(f"Falha de rede ao baixar mídia: {erro}") from erro
    return b"".join(pedacos)


def baixar_midia(media_id: str) -> ResultadoMidia:
    """Baixa um arquivo de mídia (comprovante) da Meta em duas etapas: (1)
    GET /{media_id} na Graph API para resolver a URL assinada/temporária do
    arquivo e o mime_type declarado, (2) GET nessa URL, em streaming, para
    os bytes reais — com corte automático se ultrapassar o limite de
    tamanho configurado.

    Decisão de design: NÃO respeita o kill switch. Diferente de
    enviar_texto/enviar_template/enviar_botoes (que são ENVIOS, bloqueados
    de propósito por WHATSAPP_ENVIO_ATIVO=false), baixar mídia é uma
    LEITURA de algo que o inquilino já mandou — desligar o kill switch de
    envio não deveria impedir o A2 de processar um comprovante já
    recebido. Ainda assim exige configuração válida (validar_configuracao_
    envio_real), porque a chamada é real e usa o mesmo access token.
    """
    validar_configuracao_envio_real()
    if not media_id:
        raise WhatsAppConteudoInvalidoError("media_id vazio.")

    headers = _headers_autenticados()
    limite_bytes = _tamanho_maximo_midia_bytes()

    url_metadados = f"{montar_url_graph_api()}/{media_id}"
    resposta_metadados = _get_com_retry(url_metadados, headers)
    try:
        metadados = resposta_metadados.json()
    except ValueError as erro:
        raise WhatsAppError(
            f"Metadados de mídia com corpo não-JSON para media_id={media_id!r}."
        ) from erro

    url_arquivo = metadados.get("url")
    mime_type = metadados.get("mime_type", "application/octet-stream")
    tamanho_informado = metadados.get("file_size")

    if not url_arquivo:
        raise WhatsAppError(f"Metadados de mídia sem URL assinada para media_id={media_id!r}.")
    # Defensivo: a URL vem de uma resposta autenticada da própria Meta, mas
    # ainda assim recusamos qualquer coisa que não seja https antes de
    # fazer um segundo GET nela — nunca aceitar "URL inesperada" às cegas
    # (restrição explícita da WA-03).
    if not url_arquivo.startswith("https://"):
        raise WhatsAppError(f"URL de mídia inesperada (não-https) para media_id={media_id!r}.")
    if mime_type not in _MIME_PERMITIDOS_COMPROVANTE:
        raise WhatsAppConteudoInvalidoError(f"MIME não permitido para comprovante: {mime_type!r}.")
    if tamanho_informado is not None:
        try:
            if int(tamanho_informado) > limite_bytes:
                raise WhatsAppConteudoInvalidoError(
                    f"Mídia excede o tamanho máximo permitido ({limite_bytes} bytes): "
                    f"{tamanho_informado} bytes informados nos metadados."
                )
        except (TypeError, ValueError):
            pass  # file_size malformado — segue pro corte real durante o download

    conteudo = _baixar_arquivo_com_limite(url_arquivo, headers, limite_bytes)

    _log_operacao(
        "baixar_midia", telefone=None, media_id=media_id, mime_type=mime_type, bytes=len(conteudo)
    )
    return ResultadoMidia(conteudo=conteudo, mime_type=mime_type)
