"""
Script de teste manual (terminal) para o cron do A4 (Gestão Contratual).

Espelha teste_cron_a2.py: mesmo padrão de comandos (seed/run/report/clean),
mesma forma de "congelar" a data via --hoje. Cobre Fluxo A (renovação) e
Fluxo B (reajuste) juntos, porque os dois rodam dentro do mesmo
executar_alertas_contratuais() por contrato.

NÃO envia WhatsApp: diferente do A2, executar_alertas_contratuais nunca
chama nenhuma função de envio — as mensagens ficam só como texto nas
listas alertas_renovacao/calculos_reajuste do resultado. Não há nada pra
mockar quanto a isso.

CHAMA a API real do Banco Central (buscar_percentual_acumulado_12_meses)
para os contratos com indice_reajuste in ('igpm', 'ipca') que caírem na
janela D-30 — API pública, sem autenticação, sem custo. Se a máquina onde
você roda isso não tiver acesso à internet, essa chamada falha; isso vira
uma entrada em resultado.erros (por contrato, isolado), não derruba o
script inteiro.

Uso — ver PLANO_DE_TESTE.md para o passo a passo completo com os 3
cenários de reajuste + 3 de renovação + o teste de aplicação tardia
(Migration 015).

Variáveis de ambiente esperadas:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
        Só para seed/report/clean (client admin, ignora RLS). MESMA
        RESSALVA do teste_cron_a2.py: nunca aponte isso pra produção.
    (as que app/orchestrator/agent_auth.py já exige para `run` funcionar
    — as mesmas do ambiente real, nada de especial aqui)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()


# Cada entrada vira 1 contrato de teste. inquilino_nome = "A4 Teste <chave>"
# — é assim que report/confirmar-decisao/clean acham os contratos depois.
CONTRATOS_TESTE = {
    "reajuste_padrao": {
        "imovel": "A4 Teste - Reajuste Padrao",
        "indice_reajuste": "igpm",
        "data_aniversario_reajuste": None,
        "prazo_indeterminado": False,
        "tipo_renovacao": "novo_contrato",
        "vence_hoje": False,
    },
    "elias_prazo_indeterminado": {
        "imovel": "A4 Teste - Elias prazo indeterminado",
        "indice_reajuste": "igpm",
        "data_aniversario_reajuste": None,
        "prazo_indeterminado": True,
        "tipo_renovacao": "indeterminado_por_lei",
        "vence_hoje": False,
    },
    "renovacao_novo_contrato": {
        "imovel": "A4 Teste - Renovacao novo_contrato",
        "indice_reajuste": None,
        "data_aniversario_reajuste": None,
        "prazo_indeterminado": False,
        "tipo_renovacao": "novo_contrato",
        "vence_hoje": True,
    },
    "arco_requer_aditivo": {
        "imovel": "A4 Teste - ARCO (requer aditivo, clausula 3.2)",
        "indice_reajuste": None,
        "data_aniversario_reajuste": None,
        "prazo_indeterminado": False,
        "tipo_renovacao": "requer_aditivo",
        "vence_hoje": True,
    },
    "renovacao_indeterminado_por_lei": {
        "imovel": "A4 Teste - Renovacao indeterminado_por_lei",
        "indice_reajuste": None,
        "data_aniversario_reajuste": None,
        "prazo_indeterminado": False,
        "tipo_renovacao": "indeterminado_por_lei",
        "vence_hoje": True,
    },
}


def get_admin_client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _data_inicio_para_aniversario_d30(hoje: date) -> date:
    """data_inicio tal que o próximo aniversário anual (mesmo mês/dia de
    data_inicio) caia exatamente 30 dias à frente de `hoje` — espelha
    app/tools/calculo_reajuste.py::proximo_aniversario_contrato "de trás
    pra frente". 5 anos atrás é arbitrário, só pra parecer um contrato já
    em vigência há tempo."""
    aniversario_alvo = hoje + timedelta(days=30)
    return aniversario_alvo.replace(year=aniversario_alvo.year - 5)


import time # Certifique-se de que o time está importado lá no topo junto com os outros imports

def seed(hoje: date) -> None:
    client = get_admin_client()
    data_inicio_reajuste = _data_inicio_para_aniversario_d30(hoje)
    data_termino_longa = hoje + timedelta(days=730)  # fora de qualquer janela D-60

    # Cria um número base dinâmico usando o timestamp atual.
    # Exemplo: 558190000000 + 45213 = 558190045213
    sufixo_dinamico = int(time.time()) % 100000
    tel_wpp = 558190000000 + sufixo_dinamico

    rows = []
    for nome, cfg in CONTRATOS_TESTE.items():
        data_termino = hoje if cfg["vence_hoje"] else data_termino_longa
        data_inicio = (
            data_inicio_reajuste if not cfg["vence_hoje"] else (data_termino - timedelta(days=365))
        )

        rows.append(
            {
                "imovel_identificacao": cfg["imovel"],
                "imovel_endereco": f"Rua de Testes A4, {nome} - Recife/PE",
                "tipo_locatario": "pf",
                "inquilino_nome": f"A4 Teste {nome}",
                "inquilino_cpf_cnpj": "000.000.000-00",
                "telefone_whatsapp": f"+{tel_wpp}",
                "garantia_tipo": "caucao",
                "garantia_valor": 1000.00,
                "valor_aluguel": 1500.00,
                "dia_vencimento": 10,
                "vencimento_mes_referencia": "atual",
                "data_inicio": data_inicio.isoformat(),
                "data_termino": data_termino.isoformat(),
                "indice_reajuste": cfg["indice_reajuste"],
                "data_aniversario_reajuste": cfg["data_aniversario_reajuste"],
                "multa_infracao_tipo": "meses_aluguel",
                "multa_infracao_valor": 3,
                "multa_moratoria_percentual": 0.02,
                "juros_moratorio_mensal": 0.01,
                "aviso_previo_dias": 30,
                "aviso_previo_a_partir_mes": 2,
                "prazo_indeterminado": cfg["prazo_indeterminado"],
                "tipo_renovacao": cfg["tipo_renovacao"],
                "status": "ativo",
            }
        )
        # Incrementa para o próximo contrato dentro desta mesma rodada
        tel_wpp += 1  

    result = client.table("contracts").insert(rows).execute()
    print(f"{len(result.data)} contratos de teste inseridos (hoje={hoje}).\n")
    for r in result.data:
        print(
            f"  [{r['inquilino_nome']:45s}] id={r['id']}  "
            f"data_inicio={r['data_inicio']}  data_termino={r['data_termino']}"
        )


def _ids_teste(client) -> dict[str, str]:
    resp = (
        client.table("contracts")
        .select("id, inquilino_nome")
        .like("inquilino_nome", "A4 Teste %")
        .execute()
    )
    return {row["inquilino_nome"].replace("A4 Teste ", "", 1): row["id"] for row in resp.data}


def confirmar_decisao(nome: str, modo: str) -> None:
    """Simula a gestora confirmando a decisão de reajuste na tela (que
    ainda não existe) — atualiza decisao_gestora direto no alerta mais
    recente de calculo_reajuste_d30 ainda pendente para o contrato `nome`.
    Precisa que `run` já tenha criado esse alerta antes."""
    client = get_admin_client()
    ids = _ids_teste(client)
    if nome not in ids:
        print(f"Contrato de teste '{nome}' não encontrado — rode `seed` primeiro.")
        return

    # NOTA: .is_("valor_aplicado", "null") assume a sintaxe do supabase-py
    # mais comum para IS NULL. Se a versão instalada no seu projeto usar
    # outra forma (ex: .is_("valor_aplicado", None)), ajuste esta linha —
    # não tenho como confirmar a versão exata do pacote no seu ambiente.
    resp = (
        client.table("contract_alerts")
        .select("id, data_disparo, valor_sugerido")
        .eq("contract_id", ids[nome])
        .eq("tipo", "calculo_reajuste_d30")
        .is_("valor_aplicado", "null")
        .order("data_disparo", desc=True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        print(f"Nenhum alerta de calculo_reajuste_d30 pendente para '{nome}' — rode `run` primeiro.")
        return

    alerta = resp.data[0]
    client.table("contract_alerts").update({"decisao_gestora": modo}).eq("id", alerta["id"]).execute()
    print(f"decisao_gestora do alerta {alerta['id']} (contrato '{nome}') atualizada para '{modo}'.")
    print(f"  data_disparo={alerta['data_disparo']}  valor_sugerido={alerta['valor_sugerido']}")


def run(hoje: date) -> None:
    from app.agents.a4_gestao_contratual.fluxo import executar_alertas_contratuais

    resultado = executar_alertas_contratuais(hoje=hoje)

    print(f"Cron A4 executado para hoje={hoje}\n")
    print(f"Alertas de renovação disparados: {len(resultado.alertas_renovacao)}")
    for msg in resultado.alertas_renovacao:
        print(f"  - {msg}\n")
    print(f"Cálculos de reajuste disparados: {len(resultado.calculos_reajuste)}")
    for msg in resultado.calculos_reajuste:
        print(f"  - {msg}\n")
    print(f"Reajustes aplicados agora: {resultado.reajustes_aplicados}")
    print(f"Contratos finalizados (tipo_renovacao=novo_contrato): {resultado.contratos_finalizados}")
    print(
        f"Contratos transicionados p/ prazo indeterminado: "
        f"{resultado.contratos_transicionados_indeterminado}"
    )
    print(f"Contratos com pendência de renovação: {resultado.contratos_pendentes_renovacao}")
    if resultado.erros:
        print(f"\nERROS ({len(resultado.erros)}):")
        for erro in resultado.erros:
            print(f"  ! {erro}")


def report() -> None:
    client = get_admin_client()

    print("=== contracts ===")
    resp = (
        client.table("contracts")
        .select(
            "id, inquilino_nome, status, tipo_renovacao, prazo_indeterminado, "
            "pendente_decisao_renovacao, data_termino, valor_aluguel"
        )
        .like("inquilino_nome", "A4 Teste %")
        .execute()
    )
    for r in resp.data:
        print(
            f"  {r['inquilino_nome']:45s} status={r['status']:10s} "
            f"tipo_renovacao={r['tipo_renovacao']:22s} "
            f"prazo_indet={str(r['prazo_indeterminado']):5s} "
            f"pendente={str(r['pendente_decisao_renovacao']):5s} "
            f"data_termino={r['data_termino']} valor_aluguel={r['valor_aluguel']}"
        )

    print("\n=== contract_alerts ===")
    ids = _ids_teste(client)
    for nome, contract_id in ids.items():
        resp = (
            client.table("contract_alerts")
            .select("tipo, data_disparo, decisao_gestora, percentual_reajuste, valor_sugerido, valor_aplicado")
            .eq("contract_id", contract_id)
            .order("data_disparo")
            .execute()
        )
        if not resp.data:
            continue
        print(f"  [{nome}]")
        for a in resp.data:
            print(
                f"    tipo={a['tipo']:22s} data_disparo={a['data_disparo']} "
                f"decisao_gestora={a['decisao_gestora']:20s} "
                f"percentual={a['percentual_reajuste']} valor_sugerido={a['valor_sugerido']} "
                f"valor_aplicado={a['valor_aplicado']}"
            )


def clean() -> None:
    client = get_admin_client()
    ids = _ids_teste(client)
    if not ids:
        print("Nenhum contrato de teste A4 encontrado.")
        return
    client.table("contracts").delete().in_("id", list(ids.values())).execute()
    print(f"{len(ids)} contrato(s) de teste A4 removido(s) (contract_alerts cai junto por cascade).")


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seed = sub.add_parser("seed", help="insere os 5 contratos de teste (reajuste + renovação)")
    p_seed.add_argument("--hoje", type=parse_date, required=True)

    p_run = sub.add_parser("run", help="roda executar_alertas_contratuais com data travada")
    p_run.add_argument("--hoje", type=parse_date, required=True)

    sub.add_parser("report", help="mostra o estado atual de contracts e contract_alerts")

    p_confirmar = sub.add_parser(
        "confirmar-decisao", help="simula a gestora confirmando decisao_gestora de um alerta de reajuste"
    )
    p_confirmar.add_argument("--nome", required=True, choices=list(CONTRATOS_TESTE.keys()))
    p_confirmar.add_argument(
        "--modo", choices=["renovar_sugerido", "renovar_ajustado"], default="renovar_sugerido"
    )

    sub.add_parser("clean", help="apaga todos os contratos de teste A4")

    args = parser.parse_args()

    if args.cmd == "seed":
        seed(args.hoje)
    elif args.cmd == "run":
        run(args.hoje)
    elif args.cmd == "report":
        report()
    elif args.cmd == "confirmar-decisao":
        confirmar_decisao(args.nome, args.modo)
    elif args.cmd == "clean":
        clean()

    return 0


if __name__ == "__main__":
    sys.exit(main())