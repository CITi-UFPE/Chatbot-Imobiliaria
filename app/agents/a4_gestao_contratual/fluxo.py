"""Orquestração diária do A4 (Gestão Contratual) — chamada pelo cron job
(app/jobs/cron_alertas_contratuais.py). Junta, para cada contrato ativo:

  Fluxo A — alerta de renovação D-60 (docs/specs/agente-gestao-contratual.md)
  Fluxo B — cálculo de reajuste D-30 + aplicação do valor confirmado no
            aniversário do contrato

Um terceiro passo, dentro do mesmo loop por contrato (não uma segunda
leitura em lote — cron_listar_contratos_ativos já devolve data_termino para
todo contrato ativo), finaliza todo contrato que chega em data_termino hoje
— incondicionalmente, sem depender de nenhuma decisão da gestora (o painel
de renovação é só aviso, sem interação). Só pode acontecer na data_termino
real, nunca antes (ver Migration 012: desativar antes da hora quebra
cobrança e roteamento por WhatsApp, que dependem de status='ativo' até o
fim do contrato).

Cada contrato (e cada item da aplicação de reajuste / finalização de
contrato) é processado isoladamente: um erro num contrato (ex: API do Banco
Central fora do ar) não pode impedir que os demais contratos ativos sejam
verificados no mesmo dia.
"""

import os
from datetime import date, datetime
from typing import Callable, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.models.contract_alerts import ContratoParaAlerta
from app.tools.calculo_reajuste import (
    calcular_periodo_contrato_meses,
    calcular_valor_reajustado,
    esta_na_janela_alerta_renovacao,
    esta_na_janela_calculo_reajuste,
    identificar_clausula_reajuste,
    proximo_aniversario_contrato,
)
from app.tools.contract_alerts_client import (
    aplicar_reajuste,
    finalizar_contrato,
    listar_clausulas_financeiras,
    listar_contratos_ativos,
    listar_reajustes_para_aplicar,
    registrar_alerta_renovacao,
    registrar_calculo_reajuste,
)
from app.tools.indice_reajuste_client import buscar_percentual_acumulado_12_meses
from app.tools.mensagens_gestao_contratual import montar_alerta_renovacao, montar_calculo_reajuste

# livre_negociacao (ou índice não definido) não tem cálculo automático de
# reajuste — só os dois índices com fonte externa (Banco Central) publicada.
_INDICES_COM_CALCULO_AUTOMATICO = ("igpm", "ipca")


class ResultadoExecucaoAlertas(BaseModel):
    alertas_renovacao: list[str] = Field(default_factory=list)
    calculos_reajuste: list[str] = Field(default_factory=list)
    reajustes_aplicados: list[UUID] = Field(default_factory=list)
    contratos_finalizados: list[UUID] = Field(default_factory=list)
    erros: list[str] = Field(default_factory=list)


def _hoje_no_fuso_do_projeto() -> date:
    """date.today() usa o calendário local do processo (em produção, quase
    sempre UTC) — para um job cuja idempotência (D-60/D-30 batem no dia
    exato) depende de "hoje" ser o dia certo no fuso do negócio, isso pode
    disparar/deixar de disparar um alerta perto da virada do dia. TIMEZONE
    já é uma variável de ambiente do projeto (.env.example); aqui é onde ela
    de fato é lida."""
    fuso = ZoneInfo(os.environ.get("TIMEZONE", "America/Recife"))
    return datetime.now(fuso).date()


def processar_alerta_renovacao(
    contrato: ContratoParaAlerta,
    hoje: date,
    *,
    registrar_alerta_renovacao_fn: Callable[[UUID, date], bool],
) -> Optional[str]:
    if not esta_na_janela_alerta_renovacao(contrato.data_termino, hoje):
        return None

    # Monta a mensagem ANTES de marcar o alerta como disparado: se algo aqui
    # lançasse uma exceção depois do registro, o índice único da migration
    # 006 faria o retry de amanhã achar "já disparado" e nunca reenviar —
    # perdendo o alerta daquele ano para sempre. Hoje só há formatação pura
    # aqui (sem I/O), mas a ordem já fica correta para qualquer mudança
    # futura que adicione uma chamada que possa falhar.
    periodo = calcular_periodo_contrato_meses(contrato.data_inicio, contrato.data_termino)
    mensagem = montar_alerta_renovacao(
        contrato.imovel_identificacao, contrato.inquilino_nome, periodo, contrato.data_termino
    )

    if not registrar_alerta_renovacao_fn(contrato.id, hoje):
        return None  # já disparado hoje — job rodou 2x, não reenviar

    return mensagem


def processar_calculo_reajuste(
    contrato: ContratoParaAlerta,
    hoje: date,
    *,
    buscar_percentual_fn: Callable[[str], float],
    registrar_calculo_reajuste_fn: Callable[[UUID, date, float, float], bool],
    listar_clausulas_fn: Callable[[UUID], list[tuple[str, str]]],
) -> Optional[str]:
    if contrato.indice_reajuste not in _INDICES_COM_CALCULO_AUTOMATICO:
        return None

    if not esta_na_janela_calculo_reajuste(contrato.data_inicio, hoje):
        return None

    aniversario = proximo_aniversario_contrato(contrato.data_inicio, hoje)
    percentual = buscar_percentual_fn(contrato.indice_reajuste)
    valor_reajustado = calcular_valor_reajustado(contrato.valor_aluguel, percentual)

    # Busca a cláusula e monta a mensagem completa ANTES de registrar —
    # mesmo racional de processar_alerta_renovacao acima, mas aqui o risco é
    # real: listar_clausulas_fn é uma chamada de rede que pode lançar. Se
    # isso acontecesse DEPOIS do registro (ordem antiga), o alerta ficaria
    # marcado como "já disparado" no banco sem a mensagem nunca ter sido
    # produzida — perdido até o próximo aniversário, um ano depois.
    clausulas = listar_clausulas_fn(contrato.id)
    numero_clausula = identificar_clausula_reajuste(clausulas)
    mensagem = montar_calculo_reajuste(
        contrato.imovel_identificacao,
        contrato.inquilino_nome,
        aniversario,
        contrato.indice_reajuste,
        numero_clausula,
        contrato.valor_aluguel,
        percentual,
        valor_reajustado,
    )

    if not registrar_calculo_reajuste_fn(contrato.id, hoje, percentual, valor_reajustado):
        return None  # já disparado hoje

    return mensagem


def _aplicar_reajustes_confirmados(hoje: date) -> tuple[list[UUID], list[str]]:
    """Isola erro por item: um reajuste falhando ao aplicar (ex: RPC
    instável) não pode impedir os demais reajustes confirmados de serem
    aplicados no mesmo dia, nem descartar os que já foram aplicados com
    sucesso antes da falha.

    aplicar_reajuste pode devolver False sem lançar exceção nenhuma — o
    filtro (decisao_gestora confirmada + ainda não aplicado) é reforçado
    dentro da própria função SQL, então algo pode ter mudado entre a leitura
    da lista do dia e a vez deste item ser escrito. Isso não é descartado em
    silêncio: vira um erro registrado, porque não é o caminho esperado."""
    aplicados: list[UUID] = []
    erros: list[str] = []

    for item in listar_reajustes_para_aplicar(hoje):
        try:
            if aplicar_reajuste(item["alerta_id"], item["contract_id"], item["valor_sugerido"]):
                aplicados.append(item["alerta_id"])
            else:
                erros.append(
                    f"alerta {item['alerta_id']} (aplicação de reajuste): condição de "
                    "aplicação não confirmada no banco no momento da escrita (decisão da "
                    "gestora mudou ou o alerta já havia sido aplicado)"
                )
        except Exception as erro:  # noqa: BLE001
            erros.append(f"alerta {item['alerta_id']} (aplicação de reajuste): {erro}")

    return aplicados, erros


def processar_finalizacao_contrato(
    contrato: ContratoParaAlerta,
    hoje: date,
    *,
    finalizar_contrato_fn: Callable[[UUID], bool],
) -> Optional[UUID]:
    """Mesmo estilo de processar_alerta_renovacao/processar_calculo_reajuste:
    função pura, testável com um fake injetado em finalizar_contrato_fn, sem
    precisar de uma segunda leitura em lote — contrato.data_termino já veio
    de listar_contratos_ativos(), que o loop principal já percorre.

    Incondicional: não depende de nenhuma decisão da gestora (o painel de
    renovação é só aviso). Só pode acontecer na data_termino real (ver
    Migration 012): fazer isso antes desligaria o contrato antes da hora,
    quebrando cobrança e roteamento por WhatsApp, que dependem de
    status='ativo' até o fim do contrato.

    finalizar_contrato_fn pode devolver False sem lançar exceção — o guard
    (status ainda 'ativo' no momento da escrita) é reforçado dentro da
    própria função SQL (agent_finalizar_contrato). Isso não é descartado em
    silêncio: quem chama decide o que fazer com o None devolvido."""
    if contrato.data_termino != hoje:
        return None

    if not finalizar_contrato_fn(contrato.id):
        return None  # já não estava mais 'ativo' — outra chamada já finalizou

    return contrato.id


def executar_alertas_contratuais(hoje: Optional[date] = None) -> ResultadoExecucaoAlertas:
    hoje = hoje or _hoje_no_fuso_do_projeto()
    resultado = ResultadoExecucaoAlertas()

    for contrato in listar_contratos_ativos():
        try:
            mensagem = processar_alerta_renovacao(
                contrato, hoje, registrar_alerta_renovacao_fn=registrar_alerta_renovacao
            )
            if mensagem:
                resultado.alertas_renovacao.append(mensagem)
        except Exception as erro:  # noqa: BLE001 — isola falha de 1 contrato do resto do lote
            resultado.erros.append(f"contrato {contrato.id} (alerta de renovação): {erro}")

        try:
            mensagem = processar_calculo_reajuste(
                contrato,
                hoje,
                buscar_percentual_fn=buscar_percentual_acumulado_12_meses,
                registrar_calculo_reajuste_fn=registrar_calculo_reajuste,
                listar_clausulas_fn=listar_clausulas_financeiras,
            )
            if mensagem:
                resultado.calculos_reajuste.append(mensagem)
        except Exception as erro:  # noqa: BLE001
            resultado.erros.append(f"contrato {contrato.id} (cálculo de reajuste): {erro}")

        try:
            finalizado = processar_finalizacao_contrato(
                contrato, hoje, finalizar_contrato_fn=finalizar_contrato
            )
            if finalizado:
                resultado.contratos_finalizados.append(finalizado)
        except Exception as erro:  # noqa: BLE001
            resultado.erros.append(f"contrato {contrato.id} (finalização no término): {erro}")

    aplicados, erros_aplicacao = _aplicar_reajustes_confirmados(hoje)
    resultado.reajustes_aplicados = aplicados
    resultado.erros.extend(erros_aplicacao)

    return resultado