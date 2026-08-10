"""
Script de teste manual (terminal) para o cron de cobrança do A2.

NÃO requer conexão com WhatsApp: a função de envio real
(enviar_mensagem_cobranca) é substituída por um "envio fake" que só
imprime no terminal e guarda em memória o que teria sido enviado.

Uso:
    # 1) crie manualmente um contrato de teste com status='ativo' e pegue o UUID

    # 2) semeia charges cobrindo os 5 estágios x 2 tipos + cenários extras
    python teste_cron_a2.py seed --contract-id <UUID> --hoje 2026-08-15

    # 3) roda o cron "congelado" nessa data
    python teste_cron_a2.py run --hoje 2026-08-15

    # 4) roda de novo com a MESMA data -> testa idempotência
    #    (não deve reenviar mensagem nem duplicar escalonamento)
    python teste_cron_a2.py run --hoje 2026-08-15

    # 5) confere o estado final de tudo
    python teste_cron_a2.py report --contract-id <UUID>

    # 6) limpa as charges de teste pra rodar de novo do zero
    python teste_cron_a2.py clean --contract-id <UUID>

Pré-requisito: o contrato (<UUID>) já precisa existir e estar com
status='ativo'. Este script só mexe na tabela `charges`, nunca em
`contracts` — a criação/edição do contrato de teste é manual, como você
pediu.

Variáveis de ambiente esperadas:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
        Precisa ser a service role (não o token do agente_ia nem o token
        de staff usado no frontend) porque este script insere/apaga
        charges arbitrárias ignorando RLS. NUNCA aponte isso pra um
        projeto Supabase de produção com contratos reais — use um projeto
        de teste/staging, ou pelo menos um contrato dedicado só de teste
        que você consiga identificar e limpar com segurança.

Dependências (além do que o projeto já usa):
    pip install python-dateutil
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
from datetime import date
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# ------------------------------------------------------------------
# AJUSTE AQUI: caminho do módulo Python onde `_processar_charge` está
# definido (o arquivo que você colou na conversa). É dentro desse módulo
# que `enviar_mensagem_cobranca` foi importado via
# `from app.agents.a2_cobranca.notificacao import enviar_mensagem_cobranca`
# — o mock precisa mirar nesse nome DENTRO do módulo que o usa, não no
# módulo `notificacao` original (regra clássica do unittest.mock: patch
# onde a função é usada, não onde é definida).
#
# Confirme o nome real do arquivo (provavelmente algo como
# app/agents/a2_cobranca/cobranca.py ou app/agents/a2_cobranca/core.py)
# e ajuste a linha abaixo.
# ------------------------------------------------------------------
MODULO_A2 = "app.agents.a2_cobranca.cobranca"  # <-- confirme e ajuste

TEST_TIPOS = ["aluguel", "agua"]
VALOR_POR_TIPO = {"aluguel": 1500.00, "agua": 180.00}

ESTAGIOS = [
    ("d-5", -5),
    ("d0", 0),
    ("d+5", 5),
    ("d+10", 10),
    ("d+15", 15),
]

STATUS_PAUSADOS_PARA_TESTAR = ["em_negociacao", "aguardando_confirmacao", "confirmado"]


def get_admin_client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def month_start(d: date) -> date:
    return d.replace(day=1)


# Duplicata proposital de app/agents/a2_cobranca/cobranca.py::_determinar_estagio
# — só pra este script conseguir prever, sem importar o módulo de produção,
# qual mensagem_estagio uma charge JÁ TERIA no momento em que foi pausada
# pra negociação (ex: "estava em d+5 quando o inquilino pediu desconto").
# Se a lógica de estágios mudar no Python, ajuste aqui também.
def _determinar_estagio_local(dias_atraso: int) -> str | None:
    if dias_atraso == -5:
        return "d-5"
    if dias_atraso == 0:
        return "d0"
    if dias_atraso == 5:
        return "d+5"
    if dias_atraso == 10:
        return "d+10"
    if dias_atraso >= 15:
        return "d+15"
    return None


def seed(contract_id: str, hoje: date) -> None:
    client = get_admin_client()
    rows: list[dict] = []

    # mes_referencia é a "competência" lógica da charge, não precisa bater
    # com o mês real do vencimento (ver comentário sobre
    # vencimento_mes_referencia na Migration 001 — casos como Lara/1706).
    # Uso um contador de meses só pra garantir que cada linha inserida
    # tenha um mes_referencia distinto por tipo e nunca colida com a
    # constraint unique(contract_id, tipo, mes_referencia).
    mes_offset = itertools.count()

    def proximo_mes_referencia() -> str:
        return (month_start(hoje) - relativedelta(months=next(mes_offset))).isoformat()

    # --- Casos principais: 5 estágios x 2 tipos --------------------
    for nome_estagio, offset_dias in ESTAGIOS:
        data_vencimento = hoje - relativedelta(days=offset_dias)
        for tipo in TEST_TIPOS:
            rows.append(
                {
                    "contract_id": contract_id,
                    "tipo": tipo,
                    "mes_referencia": proximo_mes_referencia(),
                    "valor_esperado": VALOR_POR_TIPO[tipo],
                    "data_vencimento": data_vencimento.isoformat(),
                    "status": "pendente",
                    "dias_atraso": 0,
                }
            )

    # --- Casos de pausa: cron deve LISTAR (RPC não filtra) mas IGNORAR
    # (STATUS_PAUSADOS dentro de _processar_charge) ------------------
    for status_pausado in STATUS_PAUSADOS_PARA_TESTAR:
        for tipo in TEST_TIPOS:
            rows.append(
                {
                    "contract_id": contract_id,
                    "tipo": tipo,
                    "mes_referencia": proximo_mes_referencia(),
                    "valor_esperado": VALOR_POR_TIPO[tipo],
                    "data_vencimento": (hoje - relativedelta(days=20)).isoformat(),
                    "status": status_pausado,
                    "dias_atraso": 20,
                }
            )

    # --- Caso "atraso crítico antigo, d+15 já disparado antes" -------
    # Serve pra confirmar que rodar o cron de novo não reenvia a
    # mensagem nem duplica o escalonamento (deve_enviar_mensagem só é
    # True quando o estágio MUDA em relação ao mensagem_estagio salvo).
    rows.append(
        {
            "contract_id": contract_id,
            "tipo": "aluguel",
            "mes_referencia": proximo_mes_referencia(),
            "valor_esperado": VALOR_POR_TIPO["aluguel"],
            "data_vencimento": (hoje - relativedelta(days=25)).isoformat(),
            "status": "atrasado",
            "dias_atraso": 25,
            "mensagem_estagio": "d+15",
        }
    )

    result = client.table("charges").insert(rows).execute()
    print(f"{len(result.data)} charges de teste inseridas para o contrato {contract_id}.\n")
    for r in result.data:
        print(f"  [{r['tipo']:8s}] vencimento={r['data_vencimento']} status={r['status']}")


class EnvioFake:
    """Substitui o envio real de WhatsApp. Só guarda e imprime no terminal."""

    def __init__(self):
        self.enviados: list[tuple[str, str]] = []

    def __call__(self, telefone: str, texto: str) -> None:
        self.enviados.append((telefone, texto))
        print("-" * 70)
        print(f"[FAKE WHATSAPP] para {telefone}:")
        print(texto)
        print("-" * 70)


def run(hoje: date, envio_modo: str = "real") -> None:
    """
    envio_modo="real" (padrão): chama enviar_mensagem_cobranca de verdade,
    sem mock. Isso é seguro porque a implementação atual (notificacao.py)
    já degrada sozinha sem WHATSAPP_ACCESS_TOKEN configurado — só loga via
    `logger.warning(...)` (aparece no terminal) e retorna, sem exceção.
    CONFIRME que WHATSAPP_ACCESS_TOKEN não está setado no seu .env de teste
    antes de rodar assim — se estiver, o envio real ainda não está
    implementado (NotImplementedError) e a charge fica travada sem
    atualizar dias_atraso/status/mensagem_estagio, só logando "Falha ao
    processar charge... pulando".

    envio_modo="fake": mocka enviar_mensagem_cobranca e guarda o texto em
    memória — útil se você quiser fazer asserts automáticos no conteúdo
    da mensagem em vez de conferir visualmente no terminal.
    """
    from app.agents.a2_cobranca import executar_cobranca_diaria

    if envio_modo == "fake":
        envio_fake = EnvioFake()
        with patch(f"{MODULO_A2}.enviar_mensagem_cobranca", envio_fake):
            executar_cobranca_diaria(hoje=hoje)
        print(f"\nCron executado para hoje={hoje} (envio FAKE, em memória).")
        print(f"{len(envio_fake.enviados)} mensagem(ns) capturada(s).")
    else:
        print(f"Cron executado para hoje={hoje} (envio REAL — sem mock).")
        print("As mensagens que seriam enviadas via WhatsApp vão aparecer")
        print("abaixo como warning de log (WHATSAPP_ACCESS_TOKEN ausente).\n")
        executar_cobranca_diaria(hoje=hoje)
        print("\nCron finalizado.")


def report(contract_id: str) -> None:
    client = get_admin_client()
    resp = (
        client.table("charges")
        .select("id, tipo, mes_referencia, data_vencimento, dias_atraso, status, mensagem_estagio")
        .eq("contract_id", contract_id)
        .order("tipo")
        .order("data_vencimento")
        .execute()
    )
    print(f"{'tipo':8s} {'vencimento':11s} {'dias_atraso':11s} {'status':22s} mensagem_estagio")
    for row in resp.data:
        print(
            f"{row['tipo']:8s} {row['data_vencimento']:11s} "
            f"{str(row['dias_atraso']):11s} {row['status']:22s} {row['mensagem_estagio'] or '-'}"
        )
    print(
        "\n(o conteúdo das mensagens de cobrança não fica no banco — "
        "notificacao.py só usa logger.warning; confira o terminal de onde "
        "você rodou `run`.)"
    )


def clean(contract_id: str) -> None:
    client = get_admin_client()
    client.table("charges").delete().eq("contract_id", contract_id).execute()
    print(f"Charges de teste do contrato {contract_id} removidas.")


# ------------------------------------------------------------------
# TRAJETÓRIA: uma única charge que você acompanha avançando --hoje ao
# longo de várias chamadas de `run`, em vez de estágios já prontos e
# isolados. Prova a TRANSIÇÃO (d+10 -> d+15 quando a data chega), não só
# o conteúdo de cada estágio isolado.
# ------------------------------------------------------------------
def seed_trajetoria(contract_id: str, tipo: str, hoje_inicial: date, dias_ate_vencer: int = 20) -> None:
    client = get_admin_client()
    data_vencimento = hoje_inicial + relativedelta(days=dias_ate_vencer)
    # mês bem fora do range usado pelo `seed` normal, só pra nunca colidir
    # com a constraint unique(contract_id, tipo, mes_referencia) se você
    # rodar os dois no mesmo contrato.
    mes_referencia = month_start(hoje_inicial) + relativedelta(months=200)

    row = {
        "contract_id": contract_id,
        "tipo": tipo,
        "mes_referencia": mes_referencia.isoformat(),
        "valor_esperado": VALOR_POR_TIPO[tipo],
        "data_vencimento": data_vencimento.isoformat(),
        "status": "pendente",
        "dias_atraso": 0,
    }
    result = client.table("charges").insert(row).execute()
    charge_id = result.data[0]["id"]

    print(f"Charge de trajetória criada: {charge_id}  (tipo={tipo})")
    print(f"  vencimento = {data_vencimento.isoformat()}\n")
    print("  Rode `run --hoje <data>` nesta ordem pra observar a progressão real:")
    for nome_estagio, offset in ESTAGIOS:
        hoje_do_estagio = data_vencimento + relativedelta(days=offset)
        print(f"    {nome_estagio:5s} -> python teste_cron_a2.py run --hoje {hoje_do_estagio.isoformat()}")
    print(
        "\n  Rode `report` depois de cada uma. Confira também um --hoje NO MEIO "
        "de dois estágios (ex: vencimento+3 dias) — deve atualizar dias_atraso "
        "mas NÃO mandar mensagem nenhuma."
    )


# ------------------------------------------------------------------
# CENÁRIO: negociação PRECOCE — pedido de desconto feito antes da charge
# chegar em d+15 (ex.: ainda não venceu, ou está em d+5), pausada em
# 'em_negociacao', e só resolvida como "negado" bem depois, quando a
# charge já passou dos 15 dias reais de atraso.
#
# Dúvida original que este cenário responde: será que esse caso tem o
# mesmo bug do cenário "pausado já em d+15" (mensagem/escalonamento nunca
# mais disparam)? A resposta esperada é NÃO — porque o mensagem_estagio
# congelado no momento da pausa (ex.: "d+5", "d-5" ou None) é diferente
# de "d+15", então quando o cron reavalia depois da resolução, a
# comparação `estagio_recalculado != mensagem_estagio_salvo` dá True e a
# mensagem/escalonamento disparam normalmente — ao contrário do cenário
# "pausado já em d+15", onde os dois valores coincidem e travam pra
# sempre. Este script serve pra confirmar isso contra o banco de verdade,
# não só por leitura de código.
# ------------------------------------------------------------------
def cenario_negociacao_precoce_preparar(
    contract_id: str, hoje: date, dias_atraso_ao_pausar: int = 5
) -> None:
    """
    dias_atraso_ao_pausar: havia quantos dias de atraso quando a
    negociação começou (o que fica congelado em dias_atraso/mensagem_estagio
    até a resolução). Use negativo pra simular pedido feito ANTES do
    vencimento (ex.: -5 = pausada em d-5, -3 = pausada 3 dias antes de
    vencer, sem bater exatamente em nenhum estágio). Default 5 = pausada
    já em d+5, como no exemplo que você deu.
    """
    client = get_admin_client()
    data_vencimento = hoje - relativedelta(days=dias_atraso_ao_pausar)
    mes_referencia = month_start(hoje) + relativedelta(months=202)

    mensagem_estagio_no_pausar = _determinar_estagio_local(dias_atraso_ao_pausar)

    row = {
        "contract_id": contract_id,
        "tipo": "aluguel",
        "mes_referencia": mes_referencia.isoformat(),
        "valor_esperado": VALOR_POR_TIPO["aluguel"],
        "data_vencimento": data_vencimento.isoformat(),
        "status": "em_negociacao",
        "dias_atraso": dias_atraso_ao_pausar,
        "mensagem_estagio": mensagem_estagio_no_pausar,
    }
    result = client.table("charges").insert(row).execute()
    charge_id = result.data[0]["id"]

    print(f"Charge criada em 'em_negociacao', simulando pedido de desconto precoce: {charge_id}")
    print(f"  vencimento = {data_vencimento.isoformat()}")
    print(f"  dias_atraso salvo (congelado na pausa) = {dias_atraso_ao_pausar}")
    print(f"  mensagem_estagio salvo (congelado na pausa) = {mensagem_estagio_no_pausar or '(nenhum — não batia em estágio nenhum ainda)'}")
    print("\nPróximo passo:")
    print(f"  python teste_cron_a2.py cenario-negociacao-precoce-resolver --charge-id {charge_id}")


def cenario_negociacao_precoce_resolver(charge_id: str) -> None:
    # Replica EXATAMENTE o update que resolverMutation faz no frontend pro
    # ramo "negado" hoje — só `status`, sem tocar em dias_atraso nem
    # mensagem_estagio. Se um dia esse ramo do frontend mudar, ajuste aqui
    # pra continuar espelhando o comportamento real.
    client = get_admin_client()
    client.table("charges").update({"status": "atrasado"}).eq("id", charge_id).execute()
    print(f"Charge {charge_id} resolvida como 'negado' (status -> atrasado; dias_atraso e")
    print("mensagem_estagio ficaram como estavam na pausa, igual ao frontend faz hoje).")
    print("\nPróximo passo — rode `run` com uma data BEM à frente do vencimento")
    print("(mais de 15 dias depois) e depois `report`. Comportamento esperado (sem bug):")
    print("  - dias_atraso é corrigido pro valor real;")
    print("  - mensagem_estagio muda para 'd+15';")
    print("  - UMA mensagem nova aparece no terminal do `run`;")
    print("  - o escalonamento (executar_escalonamento) é chamado — confira a tabela")
    print("    `escalations` pra essa charge.")
    print("Isso confirma que negociações pausadas ANTES de d+15 se recuperam sozinhas")
    print("quando resolvidas como 'negado', sem precisar de nenhuma correção no frontend.")


# ------------------------------------------------------------------
# PRAZO PRÓXIMO: charges 'pendente' vencendo hoje e amanhã, só pra testar
# visualmente o badge do PendenteCard (deve ficar laranja/urgente nesses
# dois casos, e no formato "outline" neutro pra qualquer coisa além disso
# — ver descreverPrazo em CobrancasSection.tsx). Não passa pelo cron, é só
# pra abrir a tela e olhar depois de rodar isto.
# ------------------------------------------------------------------
def seed_prazo_proximo(contract_id: str, hoje: date) -> None:
    client = get_admin_client()
    mes_referencia_base = month_start(hoje) + relativedelta(months=300)

    casos = [
        ("Vence hoje", 0),
        ("Vence amanhã", 1),
        # controle: não deveria ficar laranja, só de referência visual lado a lado
        ("Vence em 5 dias (controle, não deve ficar laranja)", 5),
    ]

    rows = []
    for i, (rotulo, offset) in enumerate(casos):
        rows.append(
            {
                "contract_id": contract_id,
                "tipo": "aluguel" if i % 2 == 0 else "agua",
                "mes_referencia": (mes_referencia_base + relativedelta(months=i)).isoformat(),
                "valor_esperado": VALOR_POR_TIPO["aluguel" if i % 2 == 0 else "agua"],
                "data_vencimento": (hoje + relativedelta(days=offset)).isoformat(),
                "status": "pendente",
                "dias_atraso": -offset,
            }
        )
        print(f"  {rotulo}: vencimento = {(hoje + relativedelta(days=offset)).isoformat()}")

    result = client.table("charges").insert(rows).execute()
    print(f"\n{len(result.data)} charges de teste de prazo inseridas para o contrato {contract_id}.")
    print("Abra a tela agora (sem precisar rodar `run`) e confira em 'Cobranças em Dia':")
    print("  - 'Vence hoje' e 'Vence amanhã' -> badge laranja (mesma cor de 'Em Negociação')")
    print("  - 'Vence em 5 dias' -> badge outline neutro, sem cor")


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seed = sub.add_parser("seed", help="insere charges de teste cobrindo a matriz de estágios")
    p_seed.add_argument("--contract-id", required=True)
    p_seed.add_argument("--hoje", type=parse_date, default=date.today())

    p_run = sub.add_parser("run", help="roda executar_cobranca_diaria com data travada")
    p_run.add_argument("--hoje", type=parse_date, default=date.today())
    p_run.add_argument(
        "--envio",
        choices=["real", "fake"],
        default="real",
        help="real = chama enviar_mensagem_cobranca de verdade (padrão, "
        "seguro sem WHATSAPP_ACCESS_TOKEN). fake = mocka e captura em memória.",
    )

    p_report = sub.add_parser("report", help="mostra o estado atual das charges de teste")
    p_report.add_argument("--contract-id", required=True)

    p_clean = sub.add_parser("clean", help="apaga as charges de teste do contrato")
    p_clean.add_argument("--contract-id", required=True)

    p_traj = sub.add_parser(
        "seed-trajetoria", help="cria 1 charge pra observar a progressão real dia a dia"
    )
    p_traj.add_argument("--contract-id", required=True)
    p_traj.add_argument("--tipo", choices=TEST_TIPOS, default="aluguel")
    p_traj.add_argument("--hoje", type=parse_date, default=date.today())
    p_traj.add_argument("--dias-ate-vencer", type=int, default=20)

    p_prec_prep = sub.add_parser(
        "cenario-negociacao-precoce-preparar",
        help="cria charge pausada em negociação ANTES de d+15 (ex.: d+5, ou antes de vencer)",
    )
    p_prec_prep.add_argument("--contract-id", required=True)
    p_prec_prep.add_argument("--hoje", type=parse_date, default=date.today())
    p_prec_prep.add_argument(
        "--dias-atraso-ao-pausar",
        type=int,
        default=5,
        help="dias de atraso no momento em que a negociação começou; negativo = antes de vencer",
    )

    p_prec_resolve = sub.add_parser(
        "cenario-negociacao-precoce-resolver",
        help="aplica o update de 'negado' (igual ao frontend) na charge preparada",
    )
    p_prec_resolve.add_argument("--charge-id", required=True)

    p_prazo = sub.add_parser(
        "seed-prazo-proximo",
        help="cria charges vencendo hoje/amanhã/em 5 dias, pra testar o badge de prazo na tela",
    )
    p_prazo.add_argument("--contract-id", required=True)
    p_prazo.add_argument("--hoje", type=parse_date, default=date.today())

    args = parser.parse_args()

    if args.cmd == "seed":
        seed(args.contract_id, args.hoje)
    elif args.cmd == "run":
        run(args.hoje, envio_modo=args.envio)
    elif args.cmd == "report":
        report(args.contract_id)
    elif args.cmd == "clean":
        clean(args.contract_id)
    elif args.cmd == "seed-trajetoria":
        seed_trajetoria(args.contract_id, args.tipo, args.hoje, args.dias_ate_vencer)
    elif args.cmd == "cenario-negociacao-precoce-preparar":
        cenario_negociacao_precoce_preparar(args.contract_id, args.hoje, args.dias_atraso_ao_pausar)
    elif args.cmd == "cenario-negociacao-precoce-resolver":
        cenario_negociacao_precoce_resolver(args.charge_id)
    elif args.cmd == "seed-prazo-proximo":
        seed_prazo_proximo(args.contract_id, args.hoje)

    return 0


if __name__ == "__main__":
    sys.exit(main())