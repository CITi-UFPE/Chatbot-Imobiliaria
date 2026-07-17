"""Teste manual e simulado, de ponta a ponta, do Agente 4 (gestão contratual).

Diferente do A3 (conversa por turno), o A4 é um job em lote — não há
"conversa" para digitar interativamente. Este script roda a lógica real de
janela/cálculo (app/tools/calculo_reajuste.py) contra um punhado de contratos
fixture cobrindo os dois fluxos, usando a API REAL do Banco Central para o
percentual de IGPM/IPCA (gratuita, sem chave). Abertura de alerta e aplicação
de reajuste são simuladas localmente (sem tocar no Supabase real) — mesmo
racional do script do A3: a assinatura do JWT do agente (aqui, cron_batch/
agente_ia) já existe (app/orchestrator/agent_auth.py), mas rodar contra um
Supabase real exige a migration 010 aplicada, fora do escopo de um teste
manual local.

Uso:
    python -m scripts.rodar_a4_gestao_contratual
"""

import sys
from datetime import date
from uuid import UUID, uuid4

from app.agents.a4_gestao_contratual.fluxo import (
    processar_alerta_renovacao,
    processar_calculo_reajuste,
)
from app.models.contract_alerts import ContratoParaAlerta
from app.tools.indice_reajuste_client import buscar_percentual_acumulado_12_meses

HOJE = date(2026, 7, 15)


def _contrato(**kwargs) -> ContratoParaAlerta:
    base = {
        "id": uuid4(),
        "telefone_whatsapp": "+5581999999999",
        "valor_aluguel": 1500.0,
    }
    base.update(kwargs)
    return ContratoParaAlerta(**base)


CONTRATOS_FIXTURE = [
    _contrato(
        imovel_identificacao="Apto 302, Ed. Residencial das Flores",
        inquilino_nome="Maria Souza",
        data_inicio=date(2025, 9, 13),
        data_termino=date(2026, 9, 13),  # exatamente 60 dias após HOJE
        indice_reajuste="livre_negociacao",
    ),
    _contrato(
        imovel_identificacao="Apto 1101, Ed. Golden Beach",
        inquilino_nome="João Pereira",
        data_inicio=date(2020, 8, 14),  # aniversário 14/08/2026, exatamente 30 dias após HOJE
        data_termino=date(2030, 8, 14),
        indice_reajuste="igpm",
        valor_aluguel=2200.0,
    ),
    _contrato(
        imovel_identificacao="Casa 12, Cond. Vila Verde",
        inquilino_nome="Ana Costa",
        data_inicio=date(2019, 8, 14),  # aniversário 14/08/2026 também
        data_termino=date(2029, 8, 14),
        indice_reajuste="ipca",
        valor_aluguel=3000.0,
    ),
    _contrato(
        imovel_identificacao="Apto 45, Ed. Central Park",
        inquilino_nome="Pedro Lima",
        data_inicio=date(2021, 8, 14),  # mesmo aniversário, mas sem índice automático
        data_termino=date(2025, 8, 14),
        indice_reajuste="livre_negociacao",
        valor_aluguel=1800.0,
    ),
    _contrato(
        imovel_identificacao="Apto 7, Ed. Solar",
        inquilino_nome="Carla Mendes",
        data_inicio=date(2024, 1, 1),
        data_termino=date(2028, 1, 1),  # fora de qualquer janela
        indice_reajuste="igpm",
        valor_aluguel=1200.0,
    ),
]


class RegistroPersistencia:
    """Stub local: imprime o que seria persistido, sem tocar no Supabase."""

    def __init__(self):
        self.alertas_renovacao: list[tuple[UUID, date]] = []
        self.calculos_reajuste: list[tuple[UUID, date, float, float]] = []

    def registrar_alerta_renovacao(self, contract_id: UUID, data_disparo: date) -> bool:
        self.alertas_renovacao.append((contract_id, data_disparo))
        return True

    def registrar_calculo_reajuste(
        self, contract_id: UUID, data_disparo: date, percentual: float, valor_sugerido: float
    ) -> bool:
        self.calculos_reajuste.append((contract_id, data_disparo, percentual, valor_sugerido))
        return True


def _clausulas_fixture(indice_reajuste: str) -> list[tuple[str, str]]:
    """listar_clausulas_fn recebe contract_id (ver processar_calculo_reajuste) — aqui
    simplificamos e devolvemos direto pelo índice, já que é só o que a fixture varia."""
    return [
        ("4", "O valor do aluguel será pago até o dia 10 de cada mês, via PIX."),
        ("4.1", f"O aluguel será reajustado anualmente pelo {indice_reajuste.upper()}."),
    ]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"=== Teste manual — Agente 4 (Gestão Contratual) — referência: {HOJE.isoformat()} ===\n")

    registro = RegistroPersistencia()
    algo_disparou = False

    for contrato in CONTRATOS_FIXTURE:
        print(f"--- {contrato.imovel_identificacao} ({contrato.inquilino_nome}) ---")

        # Isola erro por contrato — mesmo comportamento de executar_alertas_contratuais
        # em produção: 1 contrato falhando (ex: timeout na API do Banco Central) não
        # pode derrubar a verificação dos demais contratos do lote.
        mensagem_renovacao = None
        try:
            mensagem_renovacao = processar_alerta_renovacao(
                contrato, HOJE, registrar_alerta_renovacao_fn=registro.registrar_alerta_renovacao
            )
            if mensagem_renovacao:
                algo_disparou = True
                print(f"[ALERTA DE RENOVAÇÃO — SIMULADO]\n{mensagem_renovacao}\n")
        except Exception as erro:  # noqa: BLE001
            algo_disparou = True
            print(f"[ERRO — alerta de renovação] {erro}\n")

        mensagem_reajuste = None
        try:
            mensagem_reajuste = processar_calculo_reajuste(
                contrato,
                HOJE,
                buscar_percentual_fn=buscar_percentual_acumulado_12_meses,
                registrar_calculo_reajuste_fn=registro.registrar_calculo_reajuste,
                listar_clausulas_fn=lambda _contract_id: _clausulas_fixture(contrato.indice_reajuste),
            )
            if mensagem_reajuste:
                algo_disparou = True
                print(f"[CÁLCULO DE REAJUSTE — SIMULADO]\n{mensagem_reajuste}\n")
        except Exception as erro:  # noqa: BLE001
            algo_disparou = True
            print(f"[ERRO — cálculo de reajuste] {erro}\n")

        if not mensagem_renovacao and not mensagem_reajuste:
            print("(fora de qualquer janela de alerta hoje)\n")

    if not algo_disparou:
        print("Nenhum contrato fixture entrou em janela de alerta na data de referência.")

    print("=== Execução simulada finalizada ===")


if __name__ == "__main__":
    main()
