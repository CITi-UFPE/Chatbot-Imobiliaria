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
