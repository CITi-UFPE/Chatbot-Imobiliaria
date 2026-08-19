"""Orquestração diária do A4 (Gestão Contratual) — chamada pelo cron job
(app/jobs/cron_alertas_contratuais.py). Junta, para cada contrato ativo:

  Fluxo A — alerta de renovação D-60 (docs/specs/agente-gestao-contratual.md)
  Fluxo B — cálculo de reajuste D-30 + aplicação do valor confirmado no
            aniversário do contrato

Um terceiro passo, dentro do mesmo loop por contrato (não uma segunda
leitura em lote — cron_listar_contratos_ativos já devolve data_termino e
tipo_renovacao para todo contrato ativo), decide o que fazer com o contrato
que chega em data_termino hoje — e esse "o quê" depende de
contrato.tipo_renovacao (Migration 016, escolhido manualmente pela gestora
na tela de conferência, não mais inferido pela IA):

  - novo_contrato (default): desativa normalmente (agent_finalizar_contrato,
    Migration 012) — sem pendência, sem depender de decisão da gestora.
  - requer_aditivo / automatica / nao_identificado ("acionáveis"): se não
    houver decisão registrada até data_termino, desativa E marca
    pendente_decisao_renovacao=true (agent_desativar_pendente_renovacao) —
    o card de renovação continua visível no dashboard (RenovacaoSection.tsx)
    até a gestora resolver, reativando o contrato ou confirmando o
    encerramento.
  - indeterminado_por_lei: nunca desativa por esta via — transiciona pra
    prazo_indeterminado=true (agent_transicionar_prazo_indeterminado), pois
    a prorrogação decorre de lei (art. 46 §1º da Lei 8.245/91), não de
    decisão humana.

Contratos que JÁ estão em prazo_indeterminado=true (Migration 013) nunca
passam por nenhum desses três caminhos — data_termino, pra eles, é só um
valor histórico, nunca uma data real de encerramento. Fora esse caso, o
terceiro passo só pode acontecer na data_termino real, nunca antes (ver
Migration 012: desativar antes da hora quebra cobrança e roteamento por
WhatsApp, que dependem de status='ativo' até o fim do contrato).

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
    INDICES_COM_CALCULO_AUTOMATICO,
    calcular_periodo_contrato_meses,
    calcular_valor_reajustado,
    esta_na_janela_alerta_renovacao,
    esta_na_janela_calculo_reajuste,
    identificar_clausula_reajuste,
    proximo_aniversario_contrato,
)
from app.tools.contract_alerts_client import (
    aplicar_reajuste,
    desativar_pendente_renovacao,
    finalizar_contrato,
    listar_clausulas_financeiras,
    listar_contratos_ativos,
    listar_reajustes_para_aplicar,
    registrar_alerta_renovacao,
    registrar_calculo_reajuste,
    transicionar_prazo_indeterminado,
)
from app.tools.indice_reajuste_client import buscar_percentual_acumulado_12_meses
from app.tools.mensagens_gestao_contratual import montar_alerta_renovacao, montar_calculo_reajuste

# tipo_renovacao que dependem de decisão da gestora até data_termino
# (Migration 016) — os demais (novo_contrato, indeterminado_por_lei) têm
# caminho próprio no dispatcher abaixo, sem passar por pendência.
_TIPOS_RENOVACAO_ACIONAVEIS = ("requer_aditivo", "automatica", "nao_identificado")


class ResultadoExecucaoAlertas(BaseModel):
    alertas_renovacao: list[str] = Field(default_factory=list)
    calculos_reajuste: list[str] = Field(default_factory=list)
    reajustes_aplicados: list[UUID] = Field(default_factory=list)
    contratos_finalizados: list[UUID] = Field(default_factory=list)
    contratos_transicionados_indeterminado: list[UUID] = Field(default_factory=list)
    contratos_pendentes_renovacao: list[UUID] = Field(default_factory=list)
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
    # Contratos de prazo indeterminado (ex: cláusula de renovação por
    # inércia, ou já transicionados por indeterminado_por_lei) não têm mais
    # uma data de término real — data_termino aqui é só um valor histórico.
    # Pular o Fluxo A pra eles é deliberado, não uma omissão: ver
    # docs/schemas/013_prazo_indeterminado.sql.
    if contrato.prazo_indeterminado:
        return None

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
    if contrato.indice_reajuste not in INDICES_COM_CALCULO_AUTOMATICO:
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
    desativar_pendente_renovacao_fn: Callable[[UUID], bool],
    transicionar_indeterminado_fn: Callable[[UUID], bool],
) -> Optional[tuple[str, UUID]]:
    """Dispatcher por contrato.tipo_renovacao (Migration 016). Função pura,
    testável com fakes injetados nos três Callable, sem precisar de uma
    segunda leitura em lote — contrato já veio de listar_contratos_ativos(),
    que o loop principal percorre.

    Retorna uma tupla (status, contract_id) para o chamador decidir em qual
    lista de ResultadoExecucaoAlertas colocar o id, ou None se nada foi
    feito (fora da data_termino, ou a escrita não confirmou a condição
    esperada no banco no momento exato da execução).

    Contratos de prazo indeterminado (Migration 013) NUNCA passam por
    nenhum dos três caminhos abaixo — data_termino, pra eles, é um valor
    histórico/decorativo, não uma data real de encerramento. Sem este
    guard, um contrato de prazo indeterminado cujo data_termino
    "decorativo" um dia coincidisse com `hoje` seria processado por engano
    — o mesmo risco que motivou o guard equivalente em
    processar_alerta_renovacao acima.

    Fora esse caso, só pode acontecer na data_termino real (ver
    Migration 012): fazer isso antes desligaria o contrato antes da hora,
    quebrando cobrança e roteamento por WhatsApp, que dependem de
    status='ativo' até o fim do contrato.

    Nenhuma das três funções injetadas deve ter sucesso silencioso assumido
    quando devolve False — cada uma reforça seu próprio guard (status
    ainda 'ativo', ou ainda não prazo_indeterminado) dentro da transação no
    banco, porque o estado pode ter mudado entre a leitura em lote e a vez
    deste contrato ser escrito (retry do job, ou ação manual da gestora)."""
    if contrato.prazo_indeterminado:
        return None

    if contrato.data_termino != hoje:
        return None

    if contrato.tipo_renovacao == "indeterminado_por_lei":
        ok = transicionar_indeterminado_fn(contrato.id)
        return ("transicionado_indeterminado", contrato.id) if ok else None

    if contrato.tipo_renovacao in _TIPOS_RENOVACAO_ACIONAVEIS:
        ok = desativar_pendente_renovacao_fn(contrato.id)
        return ("pendente_renovacao", contrato.id) if ok else None

    # tipo_renovacao == "novo_contrato" (ou qualquer valor não mapeado
    # acima, por segurança): comportamento original, sem pendência.
    ok = finalizar_contrato_fn(contrato.id)
    return ("finalizado", contrato.id) if ok else None


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
            resultado_finalizacao = processar_finalizacao_contrato(
                contrato,
                hoje,
                finalizar_contrato_fn=finalizar_contrato,
                desativar_pendente_renovacao_fn=desativar_pendente_renovacao,
                transicionar_indeterminado_fn=transicionar_prazo_indeterminado,
            )
            if resultado_finalizacao:
                status, contrato_id = resultado_finalizacao
                if status == "transicionado_indeterminado":
                    resultado.contratos_transicionados_indeterminado.append(contrato_id)
                elif status == "pendente_renovacao":
                    resultado.contratos_pendentes_renovacao.append(contrato_id)
                else:
                    resultado.contratos_finalizados.append(contrato_id)
        except Exception as erro:  # noqa: BLE001
            resultado.erros.append(f"contrato {contrato.id} (finalização/renovação no término): {erro}")

    aplicados, erros_aplicacao = _aplicar_reajustes_confirmados(hoje)
    resultado.reajustes_aplicados = aplicados
    resultado.erros.extend(erros_aplicacao)

    return resultado