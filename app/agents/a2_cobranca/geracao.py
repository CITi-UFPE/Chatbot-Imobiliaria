"""Agente 2 — geração automática das charges de aluguel (Migration 025).

Roda 1x/dia pelo job app/jobs/cron_cobranca_diaria.py, ANTES de
executar_cobranca_diaria: cria a charge de aluguel de cada contrato ativo
cujo vencimento cai nos próximos JANELA_GERACAO_DIAS dias — assim ela já
existe quando o D-5 chega. Água não é gerada aqui (continua manual, pela
tela de Água do frontend).

Mesmas duas camadas de autenticação do cron de cobrança (ver cobranca.py):
cron_batch só lista; o insert vai contrato por contrato com o JWT do
agente_ia. Idempotência é do banco (charges_unico_por_mes).
"""

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.agents.a2_cobranca.cobranca import TIMEZONE_COBRANCA
from app.agents.a2_cobranca.schemas import ContratoFaturamento
from app.orchestrator.agent_auth import obter_client_agente, obter_client_cron_batch

logger = logging.getLogger(__name__)

# Menor que qualquer mês (28 dias), então no máximo UM vencimento cai na
# janela por contrato. Maior que 5 pra charge existir antes do D-5, com
# folga pra recuperar alguns dias de cron parado.
JANELA_GERACAO_DIAS = 10


@dataclass(frozen=True)
class CobrancaAGerar:
    mes_referencia: date
    data_vencimento: date


def _somar_meses(primeiro_dia: date, meses: int) -> date:
    indice = primeiro_dia.year * 12 + (primeiro_dia.month - 1) + meses
    return date(indice // 12, indice % 12 + 1, 1)


def _vencimento_no_mes(primeiro_dia: date, dia_vencimento: int) -> date:
    # dia 31 em mês de 30 (ou fevereiro) vence no último dia do mês
    ultimo_dia = calendar.monthrange(primeiro_dia.year, primeiro_dia.month)[1]
    return primeiro_dia.replace(day=min(dia_vencimento, ultimo_dia))


def calcular_cobrancas_a_gerar(contrato: ContratoFaturamento, hoje: date) -> list[CobrancaAGerar]:
    limite = hoje + timedelta(days=JANELA_GERACAO_DIAS)
    inicio_vigencia = contrato.data_inicio.replace(day=1)
    fim_vigencia = contrato.data_termino.replace(day=1)
    mes_atual = hoje.replace(day=1)

    cobrancas = []
    for deslocamento in (0, 1):
        mes_vencimento = _somar_meses(mes_atual, deslocamento)
        data_vencimento = _vencimento_no_mes(mes_vencimento, contrato.dia_vencimento)
        if not hoje <= data_vencimento <= limite:
            continue
        if data_vencimento < contrato.data_inicio:
            # Vence antes do inquilino entrar (ex.: 'atual', início 15/09,
            # dia 10). Primeiro mês é lançado à mão, nunca pelo cron.
            continue

        mes_referencia = (
            mes_vencimento
            if contrato.vencimento_mes_referencia == "atual"
            else _somar_meses(mes_vencimento, -1)
        )
        if mes_referencia < inicio_vigencia:
            continue
        if not contrato.prazo_indeterminado and mes_referencia > fim_vigencia:
            continue

        cobrancas.append(CobrancaAGerar(mes_referencia=mes_referencia, data_vencimento=data_vencimento))
    return cobrancas


def _gerar_para_contrato(contrato: ContratoFaturamento, hoje: date) -> int:
    cobrancas = calcular_cobrancas_a_gerar(contrato, hoje)
    if not cobrancas:
        return 0

    client_agente = obter_client_agente(contrato.id)
    geradas = 0
    for cobranca in cobrancas:
        resposta = client_agente.rpc(
            "agent_gerar_charge_aluguel",
            {
                "p_mes_referencia": cobranca.mes_referencia.isoformat(),
                "p_data_vencimento": cobranca.data_vencimento.isoformat(),
            },
        ).execute()
        # null = já existia charge de aluguel pro mês (charges_unico_por_mes)
        if resposta.data:
            geradas += 1
            logger.info(
                "Charge de aluguel gerada (contrato %s, mes_referencia %s, vencimento %s).",
                contrato.id,
                cobranca.mes_referencia,
                cobranca.data_vencimento,
            )
    return geradas


def gerar_charges_aluguel(hoje: date | None = None) -> int:
    """Ponto de entrada chamado por app/jobs/cron_cobranca_diaria.py antes
    de executar_cobranca_diaria. `hoje` só é passado em testes/scripts
    (mesmo racional de executar_cobranca_diaria). Retorna quantas charges
    NOVAS foram criadas."""
    if hoje is None:
        hoje = datetime.now(TIMEZONE_COBRANCA).date()

    client_cron = obter_client_cron_batch()
    resposta = client_cron.rpc("cron_listar_contratos_para_faturamento", {}).execute()
    contratos_raw = resposta.data or []

    geradas = 0
    for contrato_raw in contratos_raw:
        try:
            contrato = ContratoFaturamento.model_validate(contrato_raw)
            geradas += _gerar_para_contrato(contrato, hoje)
        except Exception:
            # Um contrato com dado inconsistente (ou falha de rede/token) não
            # pode travar a geração dos demais — mesmo padrão do lote de
            # executar_cobranca_diaria.
            logger.exception(
                "Falha ao gerar charge de aluguel do contrato %s — pulando.",
                contrato_raw.get("id"),
            )

    logger.info(
        "Geração de charges de aluguel: %s contratos avaliados, %s charges novas em %s.",
        len(contratos_raw),
        geradas,
        hoje,
    )
    return geradas
