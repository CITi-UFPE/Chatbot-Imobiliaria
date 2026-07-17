from typing import Literal

import httpx

# SGS (Sistema Gerenciador de Séries Temporais) do Banco Central — API pública,
# gratuita, sem autenticação. Códigos de série para variação MENSAL de cada
# índice (não o acumulado — o acumulado de 12 meses é calculado localmente
# compondo as últimas 12 variações mensais, ver _calcular_acumulado_12_meses).
_CODIGO_SERIE = {"igpm": 189, "ipca": 433}

_URL_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{quantidade}"

TIMEOUT_PADRAO_SEGUNDOS = 10.0


def _calcular_acumulado_12_meses(variacoes_mensais_percentual: list[float]) -> float:
    """Composição das variações mensais (não soma simples) — padrão de mercado
    para 'acumulado 12 meses' de índices de preços."""
    fator_acumulado = 1.0
    for variacao in variacoes_mensais_percentual:
        fator_acumulado *= 1 + variacao / 100

    return (fator_acumulado - 1) * 100


def buscar_percentual_acumulado_12_meses(
    indice: Literal["igpm", "ipca"], timeout_segundos: float = TIMEOUT_PADRAO_SEGUNDOS
) -> float:
    """Percentual acumulado dos últimos 12 meses publicados do índice, via API
    do Banco Central (SGS). Busca 13 registros (não 12) como margem — o mês
    mais recente pode ainda não ter sido publicado quando o job roda."""
    codigo = _CODIGO_SERIE[indice]
    url = _URL_BASE.format(codigo=codigo, quantidade=13)

    try:
        resposta = httpx.get(url, params={"formato": "json"}, timeout=timeout_segundos)
        resposta.raise_for_status()
    except httpx.HTTPError as erro:
        raise RuntimeError(f"Falha ao buscar série {indice} (código {codigo}) na API do Banco Central: {erro}") from erro

    dados = resposta.json()
    if len(dados) < 12:
        raise RuntimeError(
            f"API do Banco Central devolveu só {len(dados)} registro(s) para {indice} "
            f"(código {codigo}) — esperado ao menos 12 para calcular o acumulado."
        )

    ultimos_12 = dados[-12:]
    variacoes = [float(registro["valor"]) for registro in ultimos_12]

    return _calcular_acumulado_12_meses(variacoes)
