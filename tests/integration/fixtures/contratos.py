"""Os contratos fictícios usados pelos testes de integração — mesmo shape do
insert feito pelo UploadWizard (frontend/src/components/gestao/ContratosSection.tsx).

Cada fixture é function-scoped (criada e apagada a cada teste, não
compartilhada entre testes) — mais simples de raciocinar e evita vazamento
de estado entre testes que mutam o contrato (ex: finalização automática,
pausar_charges_em_negociacao), ao custo de mais algumas chamadas REST por
teste. Sempre criadas/apagadas via `service_role_client`: o papel agente_ia
não tem GRANT de insert em `contracts`/`charges` (só via RPC, ver
docs/schemas/002_auth_rbac_rls.sql) — só o service_role pode inserir os
dados fictícios diretamente.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterator

import pytest
from supabase import Client

PREFIXO_TELEFONE_FIXTURE = "+551199990"
TELEFONES_FIXTURE_NORMALIZACAO = (
    "+55 (81) 9876-5420",
    "(81) 3456-7821",
    "81998765420",
)


def _telefone(sufixo: int) -> str:
    return f"{PREFIXO_TELEFONE_FIXTURE}{sufixo:03d}"


def _contrato_base(**overrides: Any) -> dict[str, Any]:
    hoje = date.today()
    base: dict[str, Any] = {
        "imovel_identificacao": "Apto Fixture",
        "imovel_endereco": "Rua de Teste, 100 — Recife/PE",
        "tipo_locatario": "pf",
        "inquilino_nome": "Fixture de Teste",
        "inquilino_cpf_cnpj": "00000000000",
        "garantia_tipo": "fiador",
        "fiador_nome": "Fiador de Teste",
        "fiador_cpf": "11111111111",
        "valor_aluguel": 1500.0,
        "dia_vencimento": 10,
        "vencimento_mes_referencia": "atual",
        "data_inicio": (hoje - timedelta(days=365)).isoformat(),
        "data_termino": (hoje + timedelta(days=365)).isoformat(),
        "indice_reajuste": "igpm",
        "multa_infracao_tipo": "meses_aluguel",
        "multa_infracao_valor": 3,
        "multa_moratoria_percentual": 0.02,
        "juros_moratorio_mensal": 0.01,
        "aviso_previo_dias": 30,
        "aviso_previo_a_partir_mes": 1,
        "status": "ativo",
    }
    base.update(overrides)
    return base


def _criar(
    service_role_client: Client,
    dados: dict[str, Any],
    clausulas: list[dict[str, Any]] | None = None,
    charges: list[dict[str, Any]] | None = None,
) -> str:
    resposta = service_role_client.table("contracts").insert(dados).execute()
    contract_id = resposta.data[0]["id"]

    if clausulas:
        for c in clausulas:
            c["contract_id"] = contract_id
        service_role_client.table("contract_clauses").insert(clausulas).execute()

    if charges:
        for c in charges:
            c["contract_id"] = contract_id
        service_role_client.table("charges").insert(charges).execute()

    return contract_id


def _limpar(service_role_client: Client, telefone: str) -> None:
    """`on delete cascade` até contracts cuida de charges, contract_clauses,
    maintenance_tickets, escalations, contract_alerts, conversation_logs,
    agent_conversation_states e charge_negotiations — ver
    docs/schemas/001_create_tables.sql e 007_estado_conversa_agente.sql."""
    service_role_client.table("contracts").delete().eq("telefone_whatsapp", telefone).execute()


# ============================================================
# 1 — PF padrão
# ============================================================
@pytest.fixture
def contrato_pf_padrao(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(1)
    dados = _contrato_base(
        imovel_identificacao="Apto 101, Ed. Fixture PF",
        telefone_whatsapp=telefone,
    )
    clausulas = [
        {
            "numero_clausula": "5.1",
            "titulo_clausula": "Multa moratória",
            "texto_clausula": (
                "Em caso de atraso no pagamento do aluguel, incidirá multa "
                "moratória de 2% sobre o valor devido, além de juros de 1% ao mês."
            ),
            "categoria": "financeiro",
        },
        {
            "numero_clausula": "8.2",
            "titulo_clausula": "Água e energia",
            "texto_clausula": (
                "As contas de água e energia elétrica são de responsabilidade "
                "exclusiva do LOCATÁRIO, que deve efetuar a transferência de "
                "titularidade em até 30 dias da entrega das chaves."
            ),
            "categoria": "agua_energia",
        },
    ]
    # Âncora fixa (hoje + 20 dias) pro teste do A2 poder "viajar no tempo"
    # chamando executar_cobranca_diaria(hoje=data_vencimento - 5) e depois
    # executar_cobranca_diaria(hoje=data_vencimento) pra exercitar os
    # estágios D-5 e D0 sem depender da data real do sistema.
    data_vencimento_charge = date.today() + timedelta(days=20)
    charges = [
        {
            "tipo": "aluguel",
            "mes_referencia": data_vencimento_charge.replace(day=1).isoformat(),
            "valor_esperado": dados["valor_aluguel"],
            "data_vencimento": data_vencimento_charge.isoformat(),
            "status": "pendente",
        }
    ]
    contract_id = _criar(service_role_client, dados, clausulas=clausulas, charges=charges)
    yield {
        "contract_id": contract_id,
        "telefone": telefone,
        "dados": dados,
        "data_vencimento_charge": data_vencimento_charge,
    }
    _limpar(service_role_client, telefone)


# ============================================================
# 2 — PJ com caução (padrão ARCO) + charge de água já processada
# ============================================================
@pytest.fixture
def contrato_pj_caucao(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(2)
    hoje = date.today()
    dados = _contrato_base(
        imovel_identificacao="Sala 302, Ed. Fixture PJ (ARCO)",
        telefone_whatsapp=telefone,
        tipo_locatario="pj",
        inquilino_nome="Fixture Empreendimentos LTDA",
        inquilino_cpf_cnpj="00000000000100",
        responsavel_contato_nome="Responsável Fixture",
        garantia_tipo="caucao",
        fiador_nome=None,
        fiador_cpf=None,
        garantia_valor=4500.0,
    )
    charges = [
        {
            "tipo": "agua",
            "mes_referencia": hoje.replace(day=1).isoformat(),
            "valor_esperado": 120.50,
            "valor_identificado": 120.50,
            "consumo_m3": 8.0,
            "data_vencimento": hoje.replace(day=15).isoformat(),
            "data_pagamento": hoje.isoformat(),
            "status": "confirmado",
        }
    ]
    contract_id = _criar(service_role_client, dados, charges=charges)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


# ============================================================
# 3 — Prazo indeterminado por inércia (padrão Elias)
# ============================================================
@pytest.fixture
def contrato_prazo_indeterminado(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(3)
    hoje = date.today()
    dados = _contrato_base(
        imovel_identificacao="Sala Ubaias, Ed. Fixture Elias",
        telefone_whatsapp=telefone,
        # data_termino no passado: decorativa, nunca usada pra decisão do A4
        # quando prazo_indeterminado=true (Migration 013).
        data_inicio=(hoje - timedelta(days=900)).isoformat(),
        data_termino=(hoje - timedelta(days=30)).isoformat(),
        prazo_indeterminado=True,
        # livre_negociacao: sem cálculo automático de reajuste (Fluxo B),
        # pra o teste de A4 sobre este contrato (guard do Fluxo
        # A/finalização) não correr risco de o Fluxo B de reajuste
        # coincidir com a mesma janela simulada de "hoje" e poluir o
        # resultado por um motivo não relacionado ao que está sendo testado.
        indice_reajuste="livre_negociacao",
    )
    contract_id = _criar(service_role_client, dados)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


# ============================================================
# 4 — Em negociação (via A5 desconto_renegociacao -> A2 pausar_charges_em_negociacao)
# ============================================================
@pytest.fixture
def contrato_para_negociacao(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(4)
    hoje = date.today()
    dados = _contrato_base(
        imovel_identificacao="Apto 404, Ed. Fixture Negociação",
        telefone_whatsapp=telefone,
    )
    # pendente/atrasado — exatamente os status que
    # pausar_charges_em_negociacao (STATUS_CHARGES_ABERTAS) move para
    # 'em_negociacao' quando o A5 detecta motivo=desconto_renegociacao.
    charges = [
        {
            "tipo": "aluguel",
            "mes_referencia": hoje.replace(day=1).isoformat(),
            "valor_esperado": dados["valor_aluguel"],
            "data_vencimento": hoje.replace(day=dados["dia_vencimento"]).isoformat(),
            "status": "atrasado",
            "dias_atraso": 5,
        }
    ]
    contract_id = _criar(service_role_client, dados, charges=charges)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


# ============================================================
# 5 — Prestes a vencer (alerta D-60 + finalização automática)
# ============================================================
@pytest.fixture
def contrato_prestes_a_vencer(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(5)
    hoje = date.today()
    dados = _contrato_base(
        imovel_identificacao="Apto 707, Ed. Fixture Vencimento",
        telefone_whatsapp=telefone,
        # data_inicio 1 ano antes de data_termino, pra bater o "12 meses" que
        # a mensagem de alerta de renovação monta (ver
        # app/tools/mensagens_gestao_contratual.py::montar_alerta_renovacao).
        data_inicio=(hoje + timedelta(days=60) - timedelta(days=365)).isoformat(),
        data_termino=(hoje + timedelta(days=60)).isoformat(),
    )
    contract_id = _criar(service_role_client, dados)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


# ============================================================
# 6 — Escalonamento simples (motivo != desconto_renegociacao)
# ============================================================
@pytest.fixture
def contrato_para_escalonamento(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(6)
    dados = _contrato_base(
        imovel_identificacao="Apto 808, Ed. Fixture Escalonamento",
        telefone_whatsapp=telefone,
    )
    contract_id = _criar(service_role_client, dados)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


# ============================================================
# 7 — Manutenção (A3, ciclo completo da máquina de estados)
# ============================================================
@pytest.fixture
def contrato_para_manutencao(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(7)
    dados = _contrato_base(
        imovel_identificacao="Apto 909, Ed. Fixture Manutenção",
        telefone_whatsapp=telefone,
    )
    contract_id = _criar(service_role_client, dados)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


# ============================================================
# 8 — Segundo contrato "qualquer", só para os testes de isolamento por RLS
# ============================================================
@pytest.fixture
def contrato_outro_para_isolamento(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = _telefone(8)
    dados = _contrato_base(
        imovel_identificacao="Apto 1010, Ed. Fixture Isolamento",
        telefone_whatsapp=telefone,
    )
    contract_id = _criar(service_role_client, dados)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


# ============================================================
# 9 e 10 — Resolução por telefone brasileiro (Migration 019)
# ============================================================
@pytest.fixture
def contrato_telefone_movel_legado(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = TELEFONES_FIXTURE_NORMALIZACAO[0]
    dados = _contrato_base(
        imovel_identificacao="Apto Fixture Telefone Móvel",
        telefone_whatsapp=telefone,
    )
    contract_id = _criar(service_role_client, dados)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)


@pytest.fixture
def contrato_telefone_fixo(service_role_client: Client) -> Iterator[dict[str, Any]]:
    telefone = TELEFONES_FIXTURE_NORMALIZACAO[1]
    dados = _contrato_base(
        imovel_identificacao="Sala Fixture Telefone Fixo",
        telefone_whatsapp=telefone,
    )
    contract_id = _criar(service_role_client, dados)
    yield {"contract_id": contract_id, "telefone": telefone, "dados": dados}
    _limpar(service_role_client, telefone)
