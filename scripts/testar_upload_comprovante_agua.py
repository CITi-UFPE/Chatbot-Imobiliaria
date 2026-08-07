"""Script manual — fluxo de upload de comprovante (pagamento + água):
extração por IA + confirmação humana obrigatória, incluindo caminhos de
erro/ambiguidade (não só o caminho feliz).

Diferente de testar_a2_e2e.py (que precisa do backend rodando local e de um
contrato já cadastrado na mão), este script é autocontido: cria e apaga seus
próprios contratos fictícios no projeto Supabase de TESTE (.env.test) e chama
as funções de app/ diretamente — mesmo espírito de tests/integration/, mas
fora do pytest porque roda alguns cenários repetidas vezes reaproveitando os
mesmos 6 arquivos reais de data/pagamentos_agua/ (custa dinheiro de API a
cada execução — não rodar em excesso).

Requisitos:
  - .env com ANTHROPIC_API_KEY
  - .env.test com SUPABASE_TEST_* preenchidos (ver tests/integration/README.md
    — é o MESMO projeto Supabase de teste, não precisa criar outro)
  - data/pagamentos_agua/ com os 6 arquivos (2 comprovantes de pagamento reais,
    4 contas de água reais) — não versionado (gitignored), específico de quem
    rodar localmente
  - data/contratos/ com os contratos 03 (Golden Beach 1304) e 07 (Golden Beach
    403) — usados como candidatos REAIS pro matching de conta de água

Uso (a partir da raiz do repo):
    python -m scripts.testar_upload_comprovante_agua
"""

import base64
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(".env.test"), override=True)

os.environ["SUPABASE_URL"] = os.environ["SUPABASE_TEST_URL"]
os.environ["SUPABASE_ANON_KEY"] = os.environ["SUPABASE_TEST_ANON_KEY"]
os.environ["SUPABASE_JWT_SECRET"] = os.environ["SUPABASE_TEST_JWT_SECRET"]
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("TIMEZONE", "America/Recife")

from supabase import create_client  # noqa: E402

from app.agents.a2_cobranca.comprovante import (  # noqa: E402
    confirmar_pagamento,
    confirmar_pagamento_combinado,
    marcar_valor_divergente,
    processar_comprovante_recebido,
)
from app.models.charge import ContratoParaMatch  # noqa: E402
from app.orchestrator.agent_auth import obter_client_agente  # noqa: E402
from app.tools.water_bill_extraction import extrair_e_identificar_conta_agua  # noqa: E402

BASE = Path("data/pagamentos_agua")
PREFIXO_TELEFONE = "+55819009"  # faixa exclusiva deste script, não colide com tests/integration

service_role = create_client(
    os.environ["SUPABASE_TEST_URL"], os.environ["SUPABASE_TEST_SERVICE_ROLE_KEY"]
)

RESULTADOS: list[dict] = []


def _titulo(texto: str) -> None:
    print("\n" + "=" * 70)
    print(texto)
    print("=" * 70)


# ============================================================
# Setup / cleanup de contratos fictícios
# ============================================================

def _novo_telefone() -> str:
    return f"{PREFIXO_TELEFONE}{uuid.uuid4().int % 10000:04d}"


def _contrato_base(telefone: str, valor_aluguel: float) -> dict:
    hoje = date.today()
    return {
        "imovel_identificacao": "Apto Teste Upload Comprovante",
        "imovel_endereco": "Rua de Teste, 1 — Recife/PE",
        "tipo_locatario": "pf",
        "inquilino_nome": "Fixture Upload Comprovante",
        "inquilino_cpf_cnpj": "00000000000",
        "garantia_tipo": "fiador",
        "fiador_nome": "Fiador Teste",
        "fiador_cpf": "11111111111",
        "valor_aluguel": valor_aluguel,
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
        "telefone_whatsapp": telefone,
    }


def _criar_contrato(telefone: str, valor_aluguel: float, charges: list[dict]) -> str:
    dados = _contrato_base(telefone, valor_aluguel)
    contract_id = service_role.table("contracts").insert(dados).execute().data[0]["id"]
    for c in charges:
        c["contract_id"] = contract_id
        c.setdefault("mes_referencia", date.today().replace(day=1).isoformat())
        c.setdefault("data_vencimento", (date.today() + timedelta(days=20)).isoformat())
    if charges:
        service_role.table("charges").insert(charges).execute()
    return contract_id


def _limpar(telefone: str) -> None:
    service_role.table("contracts").delete().eq("telefone_whatsapp", telefone).execute()


def _charges(contract_id: str, client_agente) -> list[dict]:
    return (
        client_agente.table("charges")
        .select("*")
        .eq("contract_id", contract_id)
        .order("valor_esperado")
        .execute()
        .data
    )


def _b64(caminho: Path) -> str:
    return base64.b64encode(caminho.read_bytes()).decode("ascii")


ARQUIVO_JPEG = BASE / "8b1cc066-8eff-479f-8339-28f2445d916e.jpeg"
VALOR_JPEG = 1165.71
MEDIA_TYPE_JPEG = "image/jpeg"

_IMAGEM_1X1_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


def _registrar(cenario: str, ok: bool, detalhe: str) -> None:
    RESULTADOS.append({"cenario": cenario, "ok": ok, "detalhe": detalhe})
    print(f"  [{'OK' if ok else 'FALHOU'}] {detalhe}")


# ============================================================
# PARTE 1 — Comprovante de pagamento: caminho feliz (Caso A)
# ============================================================

def cenario_caso_a_feliz() -> None:
    _titulo("PAGAMENTO 1/6 — Caso A: 1 charge em aberto, valor bate (caminho feliz)")
    telefone = _novo_telefone()
    contract_id = _criar_contrato(
        telefone, VALOR_JPEG,
        [{"tipo": "aluguel", "valor_esperado": VALOR_JPEG, "status": "pendente"}],
    )
    try:
        processar_comprovante_recebido(contract_id, _b64(ARQUIVO_JPEG), MEDIA_TYPE_JPEG)
        client = obter_client_agente(contract_id)
        charges = _charges(contract_id, client)
        c = charges[0]
        _registrar(
            "caso_a_feliz",
            c["status"] == "aguardando_confirmacao" and abs((c["valor_identificado"] or 0) - VALOR_JPEG) < 0.01,
            f"status={c['status']} valor_identificado={c['valor_identificado']}",
        )

        confirmar_pagamento(contract_id, c["id"])
        charges = _charges(contract_id, client)
        _registrar(
            "caso_a_feliz_confirmacao",
            charges[0]["status"] == "confirmado",
            f"status pós-confirmação={charges[0]['status']}",
        )
    finally:
        _limpar(telefone)


# ============================================================
# PARTE 1 — Caminhos alternativos / erro
# ============================================================

def cenario_ilegivel() -> None:
    _titulo("PAGAMENTO 2/6 — Imagem ilegível/errada (PNG 1x1, não é comprovante)")
    telefone = _novo_telefone()
    contract_id = _criar_contrato(
        telefone, 1000.0, [{"tipo": "aluguel", "valor_esperado": 1000.0, "status": "pendente"}]
    )
    try:
        processar_comprovante_recebido(contract_id, _IMAGEM_1X1_PNG, "image/png")
        client = obter_client_agente(contract_id)
        charges = _charges(contract_id, client)
        _registrar(
            "ilegivel_nao_muda_status",
            charges[0]["status"] == "pendente",
            f"status permaneceu={charges[0]['status']} (esperado: nenhuma mudança, imagem ilegível)",
        )
    finally:
        _limpar(telefone)


def cenario_valor_diverge() -> None:
    _titulo("PAGAMENTO 3/6 — Fernanda marca 'Valor diverge'")
    telefone = _novo_telefone()
    contract_id = _criar_contrato(
        telefone, VALOR_JPEG,
        [{"tipo": "aluguel", "valor_esperado": VALOR_JPEG, "status": "pendente"}],
    )
    try:
        processar_comprovante_recebido(contract_id, _b64(ARQUIVO_JPEG), MEDIA_TYPE_JPEG)
        client = obter_client_agente(contract_id)
        charge_id = _charges(contract_id, client)[0]["id"]
        marcar_valor_divergente(contract_id, charge_id)
        status_final = _charges(contract_id, client)[0]["status"]
        _registrar("valor_diverge", status_final == "divergente", f"status final={status_final}")
    finally:
        _limpar(telefone)


def cenario_b_a_match_individual() -> None:
    _titulo("PAGAMENTO 4/6 — Caso B.a: 2 charges em aberto, valor bate com só UMA")
    telefone = _novo_telefone()
    contract_id = _criar_contrato(
        telefone, VALOR_JPEG,
        [
            {"tipo": "aluguel", "valor_esperado": VALOR_JPEG, "status": "pendente"},
            {"tipo": "agua", "valor_esperado": 500.00, "status": "pendente"},
        ],
    )
    try:
        processar_comprovante_recebido(contract_id, _b64(ARQUIVO_JPEG), MEDIA_TYPE_JPEG)
        client = obter_client_agente(contract_id)
        charges = _charges(contract_id, client)
        alvo = next(c for c in charges if c["valor_esperado"] == VALOR_JPEG)
        outra = next(c for c in charges if c["valor_esperado"] == 500.00)
        _registrar(
            "b_a_match_individual",
            alvo["status"] == "aguardando_confirmacao" and outra["status"] == "pendente",
            f"charge_alvo={alvo['status']} charge_outra(nao_deveria_mudar)={outra['status']}",
        )
    finally:
        _limpar(telefone)


def cenario_b_b_pagamento_combinado() -> None:
    _titulo("PAGAMENTO 5/6 — Caso B.b: valor bate com a SOMA de 2 charges (pagamento combinado)")
    telefone = _novo_telefone()
    valor_1, valor_2 = 615.71, 550.00  # soma = 1165.71 = VALOR_JPEG
    contract_id = _criar_contrato(
        telefone, valor_1,
        [
            {"tipo": "aluguel", "valor_esperado": valor_1, "status": "pendente"},
            {"tipo": "agua", "valor_esperado": valor_2, "status": "pendente"},
        ],
    )
    try:
        processar_comprovante_recebido(contract_id, _b64(ARQUIVO_JPEG), MEDIA_TYPE_JPEG)
        client = obter_client_agente(contract_id)
        charges = _charges(contract_id, client)
        ambas_aguardando = all(c["status"] == "aguardando_confirmacao" for c in charges)
        _registrar(
            "b_b_pagamento_combinado_extracao",
            ambas_aguardando,
            f"status das 2 charges={[c['status'] for c in charges]}",
        )

        confirmar_pagamento_combinado(contract_id, [c["id"] for c in charges])
        charges_depois = _charges(contract_id, client)
        _registrar(
            "b_b_pagamento_combinado_confirmacao",
            all(c["status"] == "confirmado" for c in charges_depois),
            f"status pós-confirmação={[c['status'] for c in charges_depois]}",
        )
    finally:
        _limpar(telefone)


def cenario_b_c_sem_match() -> None:
    _titulo("PAGAMENTO 6/6 — Caso B.c: valor não bate com nenhuma nem com a soma")
    telefone = _novo_telefone()
    contract_id = _criar_contrato(
        telefone, 300.0,
        [
            {"tipo": "aluguel", "valor_esperado": 300.00, "status": "pendente"},
            {"tipo": "agua", "valor_esperado": 400.00, "status": "pendente"},
        ],
    )
    try:
        processar_comprovante_recebido(contract_id, _b64(ARQUIVO_JPEG), MEDIA_TYPE_JPEG)
        client = obter_client_agente(contract_id)
        charges = _charges(contract_id, client)
        nenhuma_mudou = all(c["status"] in ("pendente", "atrasado") for c in charges)
        _registrar(
            "b_c_sem_match_nao_adivinha",
            nenhuma_mudou,
            f"status das 2 charges (nenhuma deveria mudar)={[c['status'] for c in charges]}",
        )
    finally:
        _limpar(telefone)


# ============================================================
# PARTE 2 — Conta de água: matching contra contratos REAIS
# (data/contratos/03_..._1304 e 07_..._403, ambos no Ed. Golden Beach)
# ============================================================

CONTRATOS_AGUA_REAIS = [
    ContratoParaMatch(
        id="contrato-golden-1304",
        imovel_identificacao="Apto 1304",
        imovel_endereco="Edifício Golden Beach, R. Amália Bernardino de Sousa, 234 - Boa Viagem, Recife/PE",
    ),
    ContratoParaMatch(
        id="contrato-golden-403",
        imovel_identificacao="Apto 403",
        imovel_endereco="Edifício Golden Beach, R. Amália Bernardino de Sousa, 234 - Boa Viagem, Recife/PE",
    ),
]

AGUA = [
    {
        "nome": "relatorio_1304 (tem contrato correspondente)",
        "arquivo": BASE / "relatorio-individual-7-2026_260720_120619.pdf",
        "contrato_esperado": "contrato-golden-1304",
    },
    {
        "nome": "relatorio_1305 (SEM contrato cadastrado)",
        "arquivo": BASE / "relatorio-individual-7-2026_260720_120641.pdf",
        "contrato_esperado": None,
    },
    {
        "nome": "relatorio_1706 (SEM contrato cadastrado)",
        "arquivo": BASE / "relatorio-individual-7-2026_260720_120704.pdf",
        "contrato_esperado": None,
    },
    {
        "nome": "relatorio_2702 (SEM contrato cadastrado)",
        "arquivo": BASE / "relatorio-individual-7-2026_260720_120729.pdf",
        "contrato_esperado": None,
    },
]


def cenario_agua_matching(item: dict) -> None:
    _titulo(f"ÁGUA — {item['nome']}")
    extraido = extrair_e_identificar_conta_agua(str(item["arquivo"]), CONTRATOS_AGUA_REAIS)
    candidatos = [(c.contract_id, round(c.confianca, 2)) for c in extraido.candidatos]
    melhor = extraido.candidatos[0] if extraido.candidatos else None

    if item["contrato_esperado"] is not None:
        ok = melhor is not None and melhor.contract_id == item["contrato_esperado"] and melhor.confianca >= 0.7
        detalhe = f"esperado={item['contrato_esperado']} candidatos={candidatos}"
    else:
        # Não deve forçar um match de alta confiança pra um apto que não
        # está cadastrado — aceita lista vazia OU o melhor candidato com
        # confiança baixa (sistema "sabe que não sabe").
        ok = melhor is None or melhor.confianca < 0.7
        detalhe = f"esperado=nenhum match confiável candidatos={candidatos}"

    _registrar(f"agua_{item['nome'][:20]}", ok, detalhe)


def cenario_agua_documento_errado() -> None:
    _titulo("ÁGUA — PDF errado (comprovante de pagamento mandado como se fosse conta de água)")
    arquivo_errado = BASE / "Comprovante-76FB799A-ED29-40B3-AA6A-1ECDB9576F6F.pdf"
    try:
        extraido = extrair_e_identificar_conta_agua(str(arquivo_errado), CONTRATOS_AGUA_REAIS)
        # Não deve inventar candidato nenhum pra um documento que não é
        # conta de água — melhor resultado aceitável é candidatos vazios
        # (ou baixa confiança); pior resultado seria "confiante e errado".
        melhor = extraido.candidatos[0] if extraido.candidatos else None
        ok = melhor is None or melhor.confianca < 0.7
        detalhe = f"não levantou RuntimeError; candidatos={[(c.contract_id, c.confianca) for c in extraido.candidatos]}"
        _registrar("agua_documento_errado", ok, detalhe)
    except RuntimeError as e:
        _registrar("agua_documento_errado", True, f"rejeitado com RuntimeError (aceitável): {e}")


def cenario_agua_upload_content_type_errado() -> None:
    _titulo("ÁGUA — endpoint HTTP rejeita content-type que não é PDF (sem custo de API)")
    from fastapi.testclient import TestClient

    from app.api.main import app

    with TestClient(app) as client:
        with open(BASE / "8b1cc066-8eff-479f-8339-28f2445d916e.jpeg", "rb") as f:
            resp = client.post(
                "/charges/agua/extrair",
                files={"arquivo": ("teste.jpeg", f, "image/jpeg")},
                data={"contratos": "[]"},
            )
    _registrar(
        "agua_endpoint_rejeita_nao_pdf",
        resp.status_code == 415,
        f"status_code={resp.status_code} (esperado 415)",
    )


# ============================================================
# EXECUÇÃO
# ============================================================

def main() -> None:
    cenario_caso_a_feliz()
    cenario_ilegivel()
    cenario_valor_diverge()
    cenario_b_a_match_individual()
    cenario_b_b_pagamento_combinado()
    cenario_b_c_sem_match()

    for item in AGUA:
        cenario_agua_matching(item)
    cenario_agua_documento_errado()
    cenario_agua_upload_content_type_errado()

    _titulo("RESUMO")
    total = len(RESULTADOS)
    passou = sum(1 for r in RESULTADOS if r["ok"])
    for r in RESULTADOS:
        print(f"{'OK' if r['ok'] else 'FALHOU':7s} {r['cenario']:35s} {r['detalhe']}")
    print(f"\n{passou}/{total} cenários passaram.")


if __name__ == "__main__":
    main()
