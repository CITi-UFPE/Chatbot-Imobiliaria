"""
Teste de integração focado: confirma que a aplicação do reajuste no
aniversário do contrato realmente atualiza contracts.valor_aluguel (e
contract_alerts.valor_aplicado) — cobre os dois modos de decisão da
gestora (aceitar sugerido / ajustar manualmente), replicando exatamente o
que ReajustesSection.tsx grava (ver aplicarMutation de
ReajustesAniversarioSection: no modo manual, sobrescreve
contract_alerts.valor_sugerido com o valor escolhido pela gestora — não
existe uma coluna "valor_ajustado" separada).

Por que este script existe além de teste_cron_a4.py: teste_cron_a4.py já
cobre esse fluxo (B.4 do PLANO_DE_TESTE.md), mas via `confirmar-decisao`,
que só grava decisao_gestora — não replica o comportamento real da tela no
modo manual (sobrescrever valor_sugerido). Este script simula exatamente o
que a UI faz, com asserts (falha alto e claro, exit code != 0), pensado
pra rodar antes de qualquer deploy que toque
app/agents/a4_gestao_contratual/fluxo.py ou as RPCs
agent_registrar_calculo_reajuste / agent_aplicar_reajuste.

Sobre a API do Banco Central: por padrão, este teste NÃO chama a API real
do BCB — o objetivo aqui é validar a lógica de aplicação (grava certo em
contracts?), não a disponibilidade de uma API externa fora do nosso
controle (ela já demonstrou ser instável — 502 Bad Gateway aconteceu numa
execução real deste script). buscar_percentual_acumulado_12_meses é
substituída por um valor fixo via unittest.mock.patch. Use
--usar-api-real se quiser testar a integração de verdade com o BCB
também (nesse caso, uma falha da API vira falha do teste, o que é
esperado e correto nesse modo).

NOTA: chama fluxo.executar_alertas_contratuais diretamente (mesmo caminho
de teste_cron_a4.py), não o entrypoint app/jobs/cron_alertas_contratuais.py
— então este teste NÃO cobre o bug de import mencionado na conversa (ver
app/agents/a4_gestao_contratual/__init__.py). Se aquele import estiver
quebrado, o cron de produção não roda nada, mesmo que este teste passe.

Uso:
    python teste_aplicacao_reajuste_aniversario.py
    python teste_aplicacao_reajuste_aniversario.py --usar-api-real

Variáveis de ambiente esperadas: as mesmas de teste_cron_a4.py
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    (+ as que app/orchestrator/agent_auth.py exige para o cron funcionar)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from unittest.mock import patch

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PREFIXO = "A4 Teste Aplicacao Reajuste"
VALOR_INICIAL = 1500.00
VALOR_MANUAL_ESCOLHIDO = 1888.88
PERCENTUAL_FAKE = 5.0  # usado quando --usar-api-real não é passado

# Contador global de telefones dinâmicos
_telefone_counter = int(time.time()) % 100000


def _get_telefone_unico() -> str:
    global _telefone_counter
    _telefone_counter += 1
    return f"+5581900{_telefone_counter:05d}"


def get_admin_client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _seed_contrato(client, nome: str, aniversario: date) -> str:
    """data_inicio 5 anos antes de `aniversario`, mesmo aniversário (mês/dia)
    — espelha _data_inicio_para_aniversario_d30 de teste_cron_a4.py."""
    data_inicio = aniversario.replace(year=aniversario.year - 5)
    row = {
        "imovel_identificacao": f"{PREFIXO} - {nome}",
        "imovel_endereco": f"Rua Teste Aplicacao, {nome} - Recife/PE",
        "tipo_locatario": "pf",
        "inquilino_nome": f"{PREFIXO} {nome}",
        "inquilino_cpf_cnpj": "000.000.000-00",
        "telefone_whatsapp": _get_telefone_unico(),  # Telefone dinâmico gerado aqui
        "garantia_tipo": "caucao",
        "garantia_valor": 1000.00,
        "valor_aluguel": VALOR_INICIAL,
        "dia_vencimento": 10,
        "vencimento_mes_referencia": "atual",
        "data_inicio": data_inicio.isoformat(),
        "data_termino": (aniversario + timedelta(days=700)).isoformat(),
        "indice_reajuste": "igpm",
        "data_aniversario_reajuste": None,
        "multa_infracao_tipo": "meses_aluguel",
        "multa_infracao_valor": 3,
        "multa_moratoria_percentual": 0.02,
        "juros_moratorio_mensal": 0.01,
        "aviso_previo_dias": 30,
        "aviso_previo_a_partir_mes": 2,
        "prazo_indeterminado": False,
        "tipo_renovacao": "novo_contrato",
        "status": "ativo",
    }
    result = client.table("contracts").insert(row).execute()
    return result.data[0]["id"]


def _simular_decisao_ui(client, contract_id: str, modo: str, valor_manual: float | None = None):
    """Replica EXATAMENTE o que ReajustesAniversarioSection.aplicarMutation
    grava (ReajustesSection.tsx) — inclusive a sobrescrita de
    valor_sugerido no modo manual, que teste_cron_a4.py::confirmar_decisao
    não fazia."""
    resp = (
        client.table("contract_alerts")
        .select("id, valor_sugerido")
        .eq("contract_id", contract_id)
        .eq("tipo", "calculo_reajuste_d30")
        .or_("decisao_gestora.is.null,decisao_gestora.eq.pendente")
        .order("data_disparo", desc=True)
        .limit(1)
        .execute()
    )
    assert resp.data, (
        f"Nenhum alerta calculo_reajuste_d30 pendente para contract_id={contract_id} "
        "— o cron em D-30 não gerou o alerta esperado (ver resultado.erros do Passo 1 "
        "acima, deveria ter aparecido antes desta linha)."
    )
    alerta = resp.data[0]

    payload = {"decisao_gestora": "renovar_sugerido" if modo == "sugerido" else "renovar_ajustado"}
    valor_esperado = alerta["valor_sugerido"]
    if modo == "manual":
        assert valor_manual is not None
        payload["valor_sugerido"] = valor_manual
        valor_esperado = valor_manual

    client.table("contract_alerts").update(payload).eq("id", alerta["id"]).execute()
    return alerta["id"], valor_esperado


def _ler_contrato(client, contract_id: str) -> dict:
    return client.table("contracts").select("valor_aluguel").eq("id", contract_id).execute().data[0]


def _ler_alerta(client, alerta_id: str) -> dict:
    return (
        client.table("contract_alerts")
        .select("valor_aplicado, decisao_gestora")
        .eq("id", alerta_id)
        .execute()
        .data[0]
    )


def _rodar_cron(hoje: date, usar_api_real: bool):
    """Roda executar_alertas_contratuais em `hoje`. Por padrão, substitui a
    chamada real à API do Banco Central por um valor fixo (PERCENTUAL_FAKE)
    — este teste valida a lógica de aplicação do reajuste, não a
    disponibilidade de uma API externa fora do nosso controle. Passe
    usar_api_real=True pra também testar a integração de verdade."""
    from app.agents.a4_gestao_contratual.fluxo import executar_alertas_contratuais

    if usar_api_real:
        return executar_alertas_contratuais(hoje=hoje)

    with patch(
        "app.agents.a4_gestao_contratual.fluxo.buscar_percentual_acumulado_12_meses",
        return_value=PERCENTUAL_FAKE,
    ):
        return executar_alertas_contratuais(hoje=hoje)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--usar-api-real",
        action="store_true",
        help="chama a API real do Banco Central em vez de simular o percentual (mais lento, "
        "sujeito a instabilidade da API externa, mas testa a integração de ponta a ponta)",
    )
    args = parser.parse_args()

    try:
        from app.agents.a4_gestao_contratual.fluxo import executar_alertas_contratuais  # noqa: F401
    except ImportError as erro:
        logger.error(
            "Não foi possível importar executar_alertas_contratuais de "
            "app.agents.a4_gestao_contratual.fluxo: %s", erro,
        )
        return 1

    client = get_admin_client()
    hoje_aniversario = date.today() + timedelta(days=40)
    hoje_d30 = hoje_aniversario - timedelta(days=30)

    id_sugerido = None
    id_ajustado = None

    try:
        logger.info("Seed: 2 contratos (sugerido / ajustado) — aniversário em %s", hoje_aniversario)
        id_sugerido = _seed_contrato(client, "sugerido", hoje_aniversario)
        id_ajustado = _seed_contrato(client, "ajustado", hoje_aniversario)

        logger.info("Passo 1 — cron em D-30 (%s): gera os alertas calculo_reajuste_d30", hoje_d30)
        resultado_d30 = _rodar_cron(hoje_d30, args.usar_api_real)
        if resultado_d30.erros:
            logger.error("Passo 1 falhou antes de chegar na parte que este teste valida:")
            for erro in resultado_d30.erros:
                logger.error("  - %s", erro)
            logger.error(
                "Isso geralmente é a API do Banco Central instável (se você não passou "
                "--usar-api-real, não deveria ser isso — investigue o traceback acima) ou "
                "algum outro problema no cálculo do reajuste, não na aplicação em si."
            )
            return 1

        logger.info("Passo 2 — simulando decisão da gestora (igual à UI)")
        alerta_sugerido_id, valor_sugerido_esperado = _simular_decisao_ui(client, id_sugerido, "sugerido")
        alerta_ajustado_id, valor_ajustado_esperado = _simular_decisao_ui(
            client, id_ajustado, "manual", valor_manual=VALOR_MANUAL_ESCOLHIDO
        )

        logger.info("Passo 3 — cron no aniversário (%s): deve aplicar os dois reajustes", hoje_aniversario)
        resultado = _rodar_cron(hoje_aniversario, args.usar_api_real)
        logger.info("reajustes_aplicados=%s  erros=%s", resultado.reajustes_aplicados, resultado.erros)

        logger.info("Passo 4 — conferindo o estado final")
        contrato_sugerido = _ler_contrato(client, id_sugerido)
        contrato_ajustado = _ler_contrato(client, id_ajustado)
        alerta_sugerido = _ler_alerta(client, alerta_sugerido_id)
        alerta_ajustado = _ler_alerta(client, alerta_ajustado_id)

        falhas = []

        if resultado.erros:
            falhas.append(f"resultado.erros não está vazio: {resultado.erros}")

        if abs(contrato_sugerido["valor_aluguel"] - valor_sugerido_esperado) > 0.01:
            falhas.append(
                f"[sugerido] contracts.valor_aluguel = {contrato_sugerido['valor_aluguel']}, "
                f"esperado {valor_sugerido_esperado} (valor calculated pelo percentual do índice)"
            )
        if alerta_sugerido["valor_aplicado"] is None:
            falhas.append("[sugerido] contract_alerts.valor_aplicado continua NULL após o cron no aniversário")

        if abs(contrato_ajustado["valor_aluguel"] - VALOR_MANUAL_ESCOLHIDO) > 0.01:
            falhas.append(
                f"[ajustado] contracts.valor_aluguel = {contrato_ajustado['valor_aluguel']}, "
                f"esperado {VALOR_MANUAL_ESCOLHIDO} (valor manual escolhido pela gestora)"
            )
        if alerta_ajustado["valor_aplicado"] is None:
            falhas.append("[ajustado] contract_alerts.valor_aplicado continua NULL após o cron no aniversário")

    finally:
        logger.info("Limpando contratos de teste...")
        ids_deletar = [i for i in [id_sugerido, id_ajustado] if i is not None]
        if ids_deletar:
            client.table("contracts").delete().in_("id", ids_deletar).execute()

    if falhas:
        logger.error("FALHOU:")
        for f in falhas:
            logger.error("  - %s", f)
        return 1

    logger.info(
        "PASSOU: os dois modos de reajuste (sugerido e ajustado) foram aplicados "
        "corretamente em contracts.valor_aluguel no aniversário do contrato."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())