from datetime import date
from uuid import UUID

from app.models.contract_alerts import ContratoParaAlerta
from app.orchestrator.agent_auth import obter_client_agente, obter_client_cron_batch


def listar_contratos_ativos() -> list[ContratoParaAlerta]:
    client = obter_client_cron_batch()
    resultado = client.rpc("cron_listar_contratos_ativos", {}).execute()
    return [ContratoParaAlerta.model_validate(linha) for linha in resultado.data]


def listar_clausulas_financeiras(contract_id: UUID) -> list[tuple[str, str]]:
    client = obter_client_cron_batch()
    resultado = client.rpc(
        "cron_listar_clausulas_financeiras", {"p_contract_id": str(contract_id)}
    ).execute()
    return [(linha["numero_clausula"], linha["texto_clausula"]) for linha in resultado.data]


def registrar_alerta_renovacao(contract_id: UUID, data_disparo: date) -> bool:
    """True se o alerta foi registrado agora (mensagem deve ser enviada).
    False se já existia um alerta igual (job rodou 2x no mesmo dia para o
    mesmo contrato) — nesse caso não reenviar a mensagem.

    Escreve como agente_ia (não cron_batch): cron_batch só lê em lote, a
    escrita é sempre escopada a UM contrato via agent_contract_id() — ver
    docs/schemas/010_alertas_contratuais_e_reajuste.sql, seção 10.4."""
    client = obter_client_agente(contract_id)
    resultado = client.rpc(
        "agent_registrar_alerta_renovacao",
        {"p_data_disparo": data_disparo.isoformat()},
    ).execute()
    return resultado.data is not None


def registrar_calculo_reajuste(
    contract_id: UUID, data_disparo: date, percentual_reajuste: float, valor_sugerido: float
) -> bool:
    """Mesma semântica de retorno de registrar_alerta_renovacao (e mesmo
    papel agente_ia na escrita)."""
    client = obter_client_agente(contract_id)
    resultado = client.rpc(
        "agent_registrar_calculo_reajuste",
        {
            "p_data_disparo": data_disparo.isoformat(),
            "p_percentual_reajuste": percentual_reajuste,
            "p_valor_sugerido": valor_sugerido,
        },
    ).execute()
    return resultado.data is not None


def listar_reajustes_para_aplicar(data_referencia: date) -> list[dict]:
    """Alertas de reajuste já confirmados/ajustados pela gestora cujo
    aniversário é hoje — cada item tem alerta_id, contract_id, valor_sugerido.

    PostgREST serializa colunas uuid como string no JSON — sem converter
    aqui, alerta_id/contract_id chegariam como str a quem consome esta lista
    (ex: ResultadoExecucaoAlertas.reajustes_aplicados, tipado list[UUID])."""
    client = obter_client_cron_batch()
    resultado = client.rpc(
        "cron_listar_reajustes_para_aplicar", {"p_data_referencia": data_referencia.isoformat()}
    ).execute()
    return [
        {
            "alerta_id": UUID(linha["alerta_id"]),
            "contract_id": UUID(linha["contract_id"]),
            "valor_sugerido": linha["valor_sugerido"],
        }
        for linha in resultado.data
    ]


def aplicar_reajuste(alerta_id: UUID, contract_id: UUID, valor_aplicado: float) -> bool:
    """True se o reajuste foi de fato aplicado. False se o alerta não estava
    mais em condição de ser aplicado no momento exato da escrita — decisão
    da gestora não confirmada ou já aplicado antes (agent_aplicar_reajuste
    reforça esse filtro dentro da própria transação; ver
    docs/schemas/010_alertas_contratuais_e_reajuste.sql, seção 10.4). Quem
    chama não deve assumir sucesso silencioso quando isso retorna False —
    ver app/agents/a4_gestao_contratual/fluxo.py::_aplicar_reajustes_confirmados.

    Escreve como agente_ia, escopado a contract_id — mesma razão de
    registrar_alerta_renovacao acima."""
    client = obter_client_agente(contract_id)
    resultado = client.rpc(
        "agent_aplicar_reajuste",
        {"p_alerta_id": str(alerta_id), "p_valor_aplicado": valor_aplicado},
    ).execute()
    return resultado.data is not None


def finalizar_contrato(contract_id: UUID) -> bool:
    """True se o contrato foi de fato desativado agora (status -> 'inativo').
    False se já não estava mais 'ativo' no momento exato da escrita — pode
    ter sido desativado por outra chamada deste mesmo job (retry) ou pela
    gestora manualmente antes disso (ContratosSection.tsx, botão "Desativar
    Contrato"). agent_finalizar_contrato reforça esse guard (where
    status = 'ativo') dentro da própria transação; ver
    docs/schemas/012_finalizacao_contrato_automatica.sql. Quem chama não
    deve assumir sucesso silencioso quando isso retorna False — ver
    app/agents/a4_gestao_contratual/fluxo.py::processar_finalizacao_contrato.

    Usado no dispatcher só para tipo_renovacao='novo_contrato' (Migration
    016) — os demais tipos passam por desativar_pendente_renovacao ou
    transicionar_prazo_indeterminado abaixo.

    Escreve como agente_ia, escopado a contract_id — mesma razão de
    registrar_alerta_renovacao/aplicar_reajuste acima. Diferente delas,
    agent_finalizar_contrato não recebe nenhum parâmetro (só lê
    agent_contract_id() do token), então o corpo do rpc() vai vazio."""
    client = obter_client_agente(contract_id)
    resultado = client.rpc("agent_finalizar_contrato", {}).execute()
    return resultado.data is not None


def desativar_pendente_renovacao(contract_id: UUID) -> bool:
    """True se o contrato foi desativado agora com pendência de renovação
    marcada (status -> 'inativo', pendente_decisao_renovacao -> true).
    False se já não estava mais 'ativo' no momento da escrita (mesma
    semântica de sucesso silencioso não assumido de finalizar_contrato
    acima). agent_desativar_pendente_renovacao reforça o guard (where
    status = 'ativo') dentro da transação; ver
    docs/schemas/016_decisao_renovacao.sql.

    Usado no dispatcher para tipo_renovacao em (requer_aditivo, automatica,
    nao_identificado) sem decisão registrada até data_termino — ver
    app/agents/a4_gestao_contratual/fluxo.py::processar_finalizacao_contrato.
    Diferente de finalizar_contrato, este NÃO encerra "de vez": a gestora
    ainda pode reativar o contrato depois, resolvendo o card no dashboard
    (RenovacaoSection.tsx) via escrita direta em contracts.

    Escreve como agente_ia, escopado a contract_id — mesma razão das
    demais funções agent_* acima."""
    client = obter_client_agente(contract_id)
    resultado = client.rpc("agent_desativar_pendente_renovacao", {}).execute()
    return resultado.data is not None


def transicionar_prazo_indeterminado(contract_id: UUID) -> bool:
    """True se o contrato transicionou agora para prazo indeterminado
    (prazo_indeterminado -> true, contrato permanece 'ativo'). False se já
    estava em prazo indeterminado no momento da escrita (mesma semântica de
    sucesso silencioso não assumido das demais funções acima).
    agent_transicionar_prazo_indeterminado reforça o guard (where
    status = 'ativo' and not prazo_indeterminado) dentro da transação; ver
    docs/schemas/014_decisao_renovacao.sql.

    Usado no dispatcher só para tipo_renovacao='indeterminado_por_lei' —
    ver app/agents/a4_gestao_contratual/fluxo.py::processar_finalizacao_contrato.
    Diferente de finalizar_contrato/desativar_pendente_renovacao, o
    contrato aqui NUNCA sai de 'ativo': a prorrogação decorre de lei
    (art. 46 §1º da Lei 8.245/91), não de decisão da gestora.

    Escreve como agente_ia, escopado a contract_id — mesma razão das
    demais funções agent_* acima."""
    client = obter_client_agente(contract_id)
    resultado = client.rpc("agent_transicionar_prazo_indeterminado", {}).execute()
    return resultado.data is not None