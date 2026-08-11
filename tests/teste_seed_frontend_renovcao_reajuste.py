"""
Script de povoamento para testar o FRONTEND (RenovacaoSection.tsx e
ReajustesSection.tsx) sem depender de acertar a janela D-60/D-30 do cron.

Diferença dos outros dois testes desta pasta:
  - test_fluxo_renovacao.py: testa a LÓGICA isolada (fakes, sem banco).
  - teste_cron_a4.py: testa o CRON de verdade contra o banco, respeitando
    a janela de data real (--hoje precisa cair exatamente D-60/D-30).
  - este script: escreve direto no banco o estado que o cron JÁ TERIA
    produzido — não roda nenhuma lógica de janela. Serve só pra colocar
    cards na tela rápido, pra você clicar nos botões e conferir a UI.

IMPORTANTE sobre datas: o frontend não tem noção de "hoje congelado" — ele
sempre calcula contra Date.now() real do navegador (ver diasRestantes() em
RenovacaoSection.tsx e em ReajustesSection.tsx). Por isso este script usa
date.today() de verdade como referência, não um --hoje like os outros dois
scripts.

NOTA sobre o campo usado pro badge (renovação): RenovacaoSection.tsx rotula
o card como "Término: {dataDisparo}" e calcula "Faltam/Vencido há X dias" a
partir de contract_alerts.data_disparo, não de contracts.data_termino —
isso já estava assim antes desta conversa (não é algo que eu introduzi, nem
corrigi, por estar fora do escopo do que foi pedido). Por isso
--dias-restantes controla data_disparo diretamente nos dois grupos de
comandos (renovação e reajuste), que é o campo que a tela de fato usa pro
cálculo visual.

NOVO (reajuste de aniversário): ReajustesSection.tsx (seção "Reajustes de
aniversário") lê contract_alerts tipo='calculo_reajuste_d30', filtrando
decisao_gestora nulo/'pendente' E contracts.status='ativo' (via
contracts!inner — é o fix do bug em que um contrato já desativado ainda
mostrava reajuste pendente). Os comandos `seed-reajuste` e
`seed-reajuste-matriz` cobrem isso, incluindo casos de regressão desse
filtro (contrato inativo com alerta pendente, e alerta já decidido).

Uso:
    # --- Renovação (alerta_renovacao_d60) ---
    python teste_seed_frontend_renovacao_reajuste.py seed-renovacao --tipo-renovacao requer_aditivo --dias-restantes 5
    python teste_seed_frontend_renovacao_reajuste.py seed-renovacao --tipo-renovacao automatica --dias-restantes -3 --vencido-pendente
    python teste_seed_frontend_renovacao_reajuste.py seed-matriz

    # --- Reajuste de aniversário (calculo_reajuste_d30) ---
    python teste_seed_frontend_renovacao_reajuste.py seed-reajuste --percentual 6.5 --dias-restantes 10
    python teste_seed_frontend_renovacao_reajuste.py seed-reajuste --percentual 4.2 --dias-restantes -5
    python teste_seed_frontend_renovacao_reajuste.py seed-reajuste --percentual 5.0 --dias-restantes 15 --decisao renovar_sugerido
    python teste_seed_frontend_renovacao_reajuste.py seed-reajuste-matriz

    # conferir o que está no banco / limpar (cobre os dois grupos)
    python teste_seed_frontend_renovacao_reajuste.py listar
    python teste_seed_frontend_renovacao_reajuste.py clean

Depois de rodar `seed-*`, é só abrir o dashboard no navegador e olhar as
seções "Renovação" e "Reajustes" — os cards devem aparecer sem precisar
rodar cron nenhum.

Variáveis de ambiente esperadas (mesmas dos outros dois scripts):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
import time

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

TIPOS_RENOVACAO = [
    "novo_contrato",
    "requer_aditivo",
    "automatica",
    "indeterminado_por_lei",
    "nao_identificado",
]
TIPOS_ACIONAVEIS = ["requer_aditivo", "automatica", "nao_identificado"]
DECISOES_REAJUSTE = ["pendente", "renovar_sugerido", "renovar_ajustado"]

PREFIXO_NOME = "A4 Front Teste"


def get_admin_client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


# Contador global iniciado com o timestamp para evitar colisões entre diferentes execuções
_telefone_counter = int(time.time()) % 100000

def _get_telefone_unico() -> str:
    global _telefone_counter
    _telefone_counter += 1
    # Gera um número no formato +5581900XXXXX
    return f"+5581900{_telefone_counter:05d}"

def _contrato_base(nome: str, tipo_renovacao: str, status: str, data_referencia: date, pendente: bool) -> dict:
    # data_termino não é o que RenovacaoSection usa pro badge (ver nota no
    # topo do arquivo) — só precisa satisfazer a constraint
    # data_termino > data_inicio do banco. Uso data_referencia pros dois,
    # é o suficiente.
    return {
        "imovel_identificacao": f"{PREFIXO_NOME} - {nome}",
        "imovel_endereco": f"Rua de Testes Frontend, {nome} - Recife/PE",
        "tipo_locatario": "pf",
        "inquilino_nome": f"{PREFIXO_NOME} {nome}",
        "inquilino_cpf_cnpj": "000.000.000-00",
        "telefone_whatsapp": _get_telefone_unico(), # <-- AQUI ESTÁ A CORREÇÃO
        "garantia_tipo": "caucao",
        "garantia_valor": 1000.00,
        "valor_aluguel": 1500.00,
        "dia_vencimento": 10,
        "vencimento_mes_referencia": "atual",
        "data_inicio": (data_referencia - timedelta(days=365)).isoformat(),
        "data_termino": data_referencia.isoformat(),
        "indice_reajuste": None,
        "data_aniversario_reajuste": None,
        "multa_infracao_tipo": "meses_aluguel",
        "multa_infracao_valor": 3,
        "multa_moratoria_percentual": 0.02,
        "juros_moratorio_mensal": 0.01,
        "aviso_previo_dias": 30,
        "aviso_previo_a_partir_mes": 2,
        "prazo_indeterminado": False,
        "tipo_renovacao": tipo_renovacao,
        "pendente_decisao_renovacao": pendente,
        "status": status,
    }


# ============================================================
# Renovação — contract_alerts tipo='alerta_renovacao_d60'
# ============================================================


def seed_renovacao(tipo_renovacao: str, dias_restantes: int, vencido_pendente: bool, nome: str | None = None) -> None:
    if vencido_pendente and tipo_renovacao not in TIPOS_ACIONAVEIS:
        print(f"--vencido-pendente só faz sentido para tipos acionáveis: {TIPOS_ACIONAVEIS}")
        return

    client = get_admin_client()
    data_disparo = date.today() + timedelta(days=dias_restantes)
    nome = nome or f"renovacao_{tipo_renovacao}_{dias_restantes}d{'_pendente' if vencido_pendente else ''}"

    status = "inativo" if vencido_pendente else "ativo"
    contrato = _contrato_base(nome, tipo_renovacao, status, data_disparo, pendente=vencido_pendente)

    result = client.table("contracts").insert(contrato).execute()
    contract_id = result.data[0]["id"]

    alerta = {
        "contract_id": contract_id,
        "tipo": "alerta_renovacao_d60",
        "data_disparo": data_disparo.isoformat(),
        "decisao_gestora": "pendente",
    }
    client.table("contract_alerts").insert(alerta).execute()

    esperado = f"Vencido há {abs(dias_restantes)} dias" if dias_restantes < 0 else f"Faltam {dias_restantes} dias"
    print(f"[renovação] Contrato '{nome}' criado: id={contract_id}")
    print(f"  tipo_renovacao={tipo_renovacao}  status={status}  pendente_decisao_renovacao={vencido_pendente}")
    print(f"  Badge esperado no card: \"{esperado}\"")


def seed_matriz() -> None:
    """5 tipos na janela (dias_restantes=30, dentro de D-60) + os 3
    acionáveis também já vencidos/pendentes (dias_restantes=-5) — cobre a
    mesma matriz do checklist_teste_wizard_renovacao.md, direto no banco."""
    for tipo in TIPOS_RENOVACAO:
        seed_renovacao(tipo, dias_restantes=30, vencido_pendente=False)
    for tipo in TIPOS_ACIONAVEIS:
        seed_renovacao(tipo, dias_restantes=-5, vencido_pendente=True)
    print(f"\n{len(TIPOS_RENOVACAO) + len(TIPOS_ACIONAVEIS)} contratos de renovação criados.")


# ============================================================
# Reajuste de aniversário — contract_alerts tipo='calculo_reajuste_d30'
# ============================================================


def seed_reajuste(
    percentual: float,
    dias_restantes: int,
    decisao: str = "pendente",
    valor_atual: float = 1500.00,
    status: str = "ativo",
    nome: str | None = None,
) -> None:
    """Cria 1 contrato ativo (por padrão) + 1 alerta calculo_reajuste_d30.

    data_disparo aqui representa a data de aniversário (D-30 já vencido no
    momento em que o alerta foi criado) — dias_restantes negativo = já
    passou do aniversário (cenário de aplicação tardia / Migration 015);
    positivo = ainda dentro da janela.

    data_termino do contrato é setada bem à frente (não tem relação com o
    aniversário de reajuste) só pra não confundir com o campo que
    RenovacaoSection usa — os dois testes usam o mesmo prefixo de nome mas
    são conceitualmente independentes.
    """
    if decisao not in DECISOES_REAJUSTE:
        print(f"--decisao inválida, use um de: {DECISOES_REAJUSTE}")
        return

    client = get_admin_client()
    data_disparo = date.today() + timedelta(days=dias_restantes)
    nome = nome or f"reajuste_{percentual}pct_{dias_restantes}d_{decisao}"
    valor_sugerido = round(valor_atual * (1 + percentual / 100), 2)

    data_termino_contrato = date.today() + timedelta(days=400)
    contrato = _contrato_base(nome, "novo_contrato", status, data_termino_contrato, pendente=False)
    contrato["valor_aluguel"] = valor_atual
    contrato["indice_reajuste"] = "igpm"
    contrato["data_inicio"] = (data_disparo - timedelta(days=335)).isoformat()  # só pra ficar coerente

    result = client.table("contracts").insert(contrato).execute()
    contract_id = result.data[0]["id"]

    alerta = {
        "contract_id": contract_id,
        "tipo": "calculo_reajuste_d30",
        "data_disparo": data_disparo.isoformat(),
        "percentual_reajuste": percentual,
        "valor_sugerido": valor_sugerido,
        "decisao_gestora": None if decisao == "pendente" else decisao,
    }
    client.table("contract_alerts").insert(alerta).execute()

    esperado = f"Vencido há {abs(dias_restantes)} dias" if dias_restantes < 0 else f"Faltam {dias_restantes} dias"
    deve_aparecer = decisao == "pendente" and status == "ativo"
    print(f"[reajuste] Contrato '{nome}' criado: id={contract_id}")
    print(f"  status={status}  decisao_gestora={decisao}  percentual={percentual}%  valor_sugerido={valor_sugerido}")
    print(f"  Badge esperado no card: \"{esperado}\"")
    print(f"  Deve aparecer em 'Reajustes de aniversário'? {'SIM' if deve_aparecer else 'NÃO (caso de regressão)'}")


def seed_reajuste_matriz() -> None:
    """Cobre os casos principais de ReajustesAniversarioSection de uma vez:
    - pendente dentro da janela (deve aparecer)
    - pendente já vencido (deve aparecer, badge vermelho)
    - já decidido (renovar_sugerido) — NÃO deve aparecer (filtro decisao_gestora)
    - contrato inativo com alerta pendente — NÃO deve aparecer
      (regressão do bug do join sem !inner, mencionado no código)
    """
    seed_reajuste(percentual=6.5, dias_restantes=12, decisao="pendente", nome="reajuste_pendente_futuro")
    seed_reajuste(percentual=4.2, dias_restantes=-5, decisao="pendente", nome="reajuste_pendente_vencido")
    seed_reajuste(percentual=5.0, dias_restantes=8, decisao="renovar_sugerido", nome="reajuste_ja_decidido")
    seed_reajuste(
        percentual=3.8,
        dias_restantes=-2,
        decisao="pendente",
        status="inativo",
        nome="reajuste_contrato_inativo",
    )
    print("\n4 contratos de reajuste de aniversário criados (2 devem aparecer na tela, 2 não).")


# ============================================================
# Comandos gerais (cobrem os dois grupos, pelo prefixo de nome)
# ============================================================


def listar() -> None:
    client = get_admin_client()
    resp = (
        client.table("contracts")
        .select("id, inquilino_nome, status, tipo_renovacao, pendente_decisao_renovacao, valor_aluguel")
        .like("inquilino_nome", f"{PREFIXO_NOME}%")
        .execute()
    )
    if not resp.data:
        print("Nenhum contrato de teste de frontend encontrado.")
        return

    ids = {r["inquilino_nome"]: r["id"] for r in resp.data}
    for r in resp.data:
        print(
            f"  {r['inquilino_nome']:55s} status={r['status']:10s} "
            f"tipo_renovacao={r['tipo_renovacao']:22s} pendente={r['pendente_decisao_renovacao']} "
            f"valor_aluguel={r['valor_aluguel']}"
        )

    print("\n=== contract_alerts (reajuste de aniversário) ===")
    resp2 = (
        client.table("contract_alerts")
        .select("contract_id, tipo, data_disparo, decisao_gestora, percentual_reajuste, valor_sugerido, valor_aplicado")
        .eq("tipo", "calculo_reajuste_d30")
        .in_("contract_id", list(ids.values()))
        .order("data_disparo")
        .execute()
    )
    for a in resp2.data:
        print(
            f"  contract_id={a['contract_id']}  decisao={a['decisao_gestora']}  "
            f"percentual={a['percentual_reajuste']}  valor_sugerido={a['valor_sugerido']}  "
            f"valor_aplicado={a['valor_aplicado']}"
        )


def clean() -> None:
    client = get_admin_client()
    resp = (
        client.table("contracts")
        .select("id")
        .like("inquilino_nome", f"{PREFIXO_NOME}%")
        .execute()
    )
    ids = [row["id"] for row in resp.data]
    if not ids:
        print("Nenhum contrato de teste de frontend encontrado.")
        return
    client.table("contracts").delete().in_("id", ids).execute()
    print(f"{len(ids)} contrato(s) de teste de frontend removido(s) (contract_alerts cai junto por cascade).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_um = sub.add_parser("seed-renovacao", help="cria 1 contrato + 1 alerta D-60 de renovação")
    p_um.add_argument("--tipo-renovacao", required=True, choices=TIPOS_RENOVACAO)
    p_um.add_argument("--dias-restantes", type=int, required=True, help="negativo = já vencido")
    p_um.add_argument(
        "--vencido-pendente",
        action="store_true",
        help="simula o estado pós-cron: status=inativo, pendente_decisao_renovacao=true "
        "(só para tipos acionáveis)",
    )
    p_um.add_argument("--nome", default=None)

    sub.add_parser("seed-matriz", help="cria a matriz de renovação (8 contratos) de uma vez")

    p_reaj = sub.add_parser("seed-reajuste", help="cria 1 contrato + 1 alerta calculo_reajuste_d30")
    p_reaj.add_argument("--percentual", type=float, required=True, help="percentual de reajuste, ex: 6.5")
    p_reaj.add_argument("--dias-restantes", type=int, required=True, help="negativo = aniversário já passou")
    p_reaj.add_argument("--decisao", choices=DECISOES_REAJUSTE, default="pendente")
    p_reaj.add_argument("--valor-atual", type=float, default=1500.00)
    p_reaj.add_argument("--status", choices=["ativo", "inativo"], default="ativo")
    p_reaj.add_argument("--nome", default=None)

    sub.add_parser("seed-reajuste-matriz", help="cria a matriz de reajuste de aniversário (4 contratos) de uma vez")

    sub.add_parser("listar", help="mostra os contratos e alertas de reajuste de teste de frontend existentes")
    sub.add_parser("clean", help="apaga todos os contratos de teste de frontend (renovação + reajuste)")

    args = parser.parse_args()

    if args.cmd == "seed-renovacao":
        seed_renovacao(args.tipo_renovacao, args.dias_restantes, args.vencido_pendente, args.nome)
    elif args.cmd == "seed-matriz":
        seed_matriz()
    elif args.cmd == "seed-reajuste":
        seed_reajuste(args.percentual, args.dias_restantes, args.decisao, args.valor_atual, args.status, args.nome)
    elif args.cmd == "seed-reajuste-matriz":
        seed_reajuste_matriz()
    elif args.cmd == "listar":
        listar()
    elif args.cmd == "clean":
        clean()

    return 0


if __name__ == "__main__":
    sys.exit(main())