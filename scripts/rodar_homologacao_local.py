"""HML-02 — roda, com um único comando, os cenários LOCAIS da matriz de
homologação (docs/whatsapp/homologacao-staging.md, seção 4) contra o
contrato de teste semeado por scripts/semear_contrato_homologacao.py.

Cobre os cenários 1 (A1), 2 (A3), 6 (cron A2), 7 (cron A4), 8 (A5) e 12
(kill switch). Nenhum deles depende de credencial real da Meta — os
cenários 3, 4, 5, 9, 10 e 11 (marcados [REAL] na matriz) exigem transporte
de verdade e ficam para a HML-04, depois do deploy em staging.

Pré-requisitos (ver docs/whatsapp/homologacao-staging.md, seção 1):
    1. `.env.test` preenchido, apontando pro Supabase de TESTE (nunca
       produção) — mesmo arquivo usado por `pytest -m integration` e por
       `scripts/semear_contrato_homologacao.py`.
    2. `.env` preenchido com AS MESMAS credenciais do Supabase de teste, sob
       os nomes "de produção" (`SUPABASE_URL`/`SUPABASE_ANON_KEY`/
       `SUPABASE_SERVICE_ROLE_KEY`/`SUPABASE_JWT_SECRET`) — é o que o
       servidor local (`app/api/main.py`) e este próprio script realmente
       leem. Nunca aponte nenhum dos dois pra produção.
    3. Um contrato já semeado:
       `python -m scripts.semear_contrato_homologacao --telefones "+55..."`
    4. O servidor rodando À PARTE, num outro terminal:
       `python -m uvicorn app.api.main:app --reload`
       (precisa de `ENVIRONMENT` != `production`, senão `/dev/chat-simulado`
       não existe — ver `app/api/main.py`).

Uso:
    python -m scripts.rodar_homologacao_local --telefone "+5581999999999"

Ordem dos cenários conversacionais (1 -> 8 -> 2) é proposital: o cenário 2
(A3) é o único com estado de conversa multi-turno
(`agent_conversation_states`) — rodá-lo por último evita que um fluxo A3
inacabado "sequestre" a classificação de uma mensagem de um cenário
seguinte no mesmo telefone. Isto é só uma conveniência pra homologação com
um único telefone de teste; rodando cada cenário conversacional com um
telefone próprio (semeando mais de um com `--telefones "+55...,+55..."`)
elimina esse risco por completo — recomendado se algum resultado abaixo
parecer "contaminado" por um cenário anterior.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MARCADOR = "[Homologação]"


class ResultadoCenario:
    def __init__(self, numero: int, nome: str):
        self.numero = numero
        self.nome = nome
        self.ok: Optional[bool] = None  # None = "confira manualmente", não passou/falhou
        self.evidencia = ""
        self.observacao = ""

    def linha_resumo(self) -> str:
        marca = "OK" if self.ok else ("CONFERIR" if self.ok is None else "FALHOU")
        return f"[{marca}] Cenário {self.numero} ({self.nome}): {self.evidencia}"


def _carregar_ambiente_teste() -> tuple[str, str]:
    """Mesmo padrão de scripts/semear_contrato_homologacao.py — carrega
    .env.test (nunca .env de produção) só para CONSULTAR o contrato/charge
    já semeados. Recusa seguir se a URL não parecer claramente de teste."""
    load_dotenv(_REPO_ROOT / ".env.test", override=True)
    import os

    url = os.environ.get("SUPABASE_TEST_URL", "")
    chave = os.environ.get("SUPABASE_TEST_SERVICE_ROLE_KEY", "")
    if not url or not chave:
        print(
            "Faltam SUPABASE_TEST_URL / SUPABASE_TEST_SERVICE_ROLE_KEY em .env.test — "
            "sem isso não dá pra descobrir automaticamente o vencimento da charge "
            "semeada. Use --vencimento AAAA-MM-DD pra pular esta consulta."
        )
        sys.exit(1)
    if ".supabase.co" not in url:
        print(f"SUPABASE_TEST_URL não parece um projeto Supabase de teste: {url!r}. Abortando.")
        sys.exit(1)
    return url, chave


def _descobrir_vencimento_charge(telefone: str) -> date:
    url, chave = _carregar_ambiente_teste()
    from supabase import create_client

    client = create_client(url, chave)
    contrato = (
        client.table("contracts")
        .select("id, imovel_identificacao")
        .eq("telefone_whatsapp", telefone)
        .like("imovel_identificacao", f"{_MARCADOR}%")
        .limit(1)
        .execute()
    )
    if not contrato.data:
        print(
            f"Nenhum contrato marcado {_MARCADOR!r} encontrado para {telefone!r}. "
            "Rode antes: python -m scripts.semear_contrato_homologacao --telefones "
            f'"{telefone}"'
        )
        sys.exit(1)
    contract_id = contrato.data[0]["id"]

    charge = (
        client.table("charges")
        .select("data_vencimento")
        .eq("contract_id", contract_id)
        .order("data_vencimento", desc=True)
        .limit(1)
        .execute()
    )
    if not charge.data:
        print(f"Contrato {contract_id} não tem nenhuma charge — rode o seed de novo.")
        sys.exit(1)
    return date.fromisoformat(charge.data[0]["data_vencimento"])


def _servidor_no_ar(base_url: str) -> bool:
    import httpx

    try:
        resp = httpx.get(f"{base_url}/dev/chat-simulado/", timeout=5.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _mandar_mensagem(base_url: str, telefone: str, texto: str) -> str:
    import httpx

    resp = httpx.post(
        f"{base_url}/dev/chat-simulado/mensagem",
        json={"telefone": telefone, "texto": texto},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json().get("resposta", "")


# ======================================================================
# Cenário 1 — A1 responde pergunta contratual
# ======================================================================


def _cenario_1_a1(base_url: str, telefone: str) -> ResultadoCenario:
    r = ResultadoCenario(1, "A1 responde pergunta contratual")
    pergunta = "Qual o percentual de multa moratória em caso de atraso no pagamento do aluguel?"
    resposta = _mandar_mensagem(base_url, telefone, pergunta)
    print(f"  Pergunta: {pergunta!r}\n  Resposta: {resposta!r}")

    # scripts/semear_contrato_homologacao.py fixa multa_moratoria_percentual=0.02
    # (2%) pra todo contrato que ele cria — valor conhecido, não inventado.
    r.ok = "2%" in resposta or "2 %" in resposta
    r.evidencia = (
        "resposta cita '2%' (multa_moratoria_percentual do contrato semeado)"
        if r.ok
        else "resposta NÃO cita '2%' — confira manualmente se o A1 respondeu com o dado certo"
    )
    r.observacao = f"Verificar em conversation_logs (remetente inquilino/agente, p_agente_responsavel='A1')."
    return r


# ======================================================================
# Cenário 8 — A5 escala e notifica equipe
# ======================================================================


def _cenario_8_a5(base_url: str, telefone: str) -> ResultadoCenario:
    r = ResultadoCenario(8, "A5 escala e notifica equipe")
    pedido = (
        "Isso é um absurdo, já pedi isso antes e ninguém resolve! Quero falar "
        "com um atendente humano agora."
    )
    resposta = _mandar_mensagem(base_url, telefone, pedido)
    print(f"  Mensagem: {pedido!r}\n  Resposta: {resposta!r}")

    resposta_lower = resposta.lower()
    r.ok = "protocolo" in resposta_lower or "esc-" in resposta_lower or "humano" in resposta_lower
    r.evidencia = (
        "resposta indica escalonamento (protocolo/atendente humano)"
        if r.ok
        else "resposta não menciona protocolo/atendente humano — confira manualmente"
    )
    r.observacao = "Verificar registro em `escalations` (motivo, protocolo) pra este contrato."
    return r


# ======================================================================
# Cenário 2 — A3 abre manutenção e retorna protocolo
# ======================================================================


def _cenario_2_a3(base_url: str, telefone: str) -> ResultadoCenario:
    r = ResultadoCenario(2, "A3 abre manutenção e retorna protocolo")
    turnos = [
        "O cano da pia da cozinha está vazando bastante água",
        "sim, correto",
        "O cano da pia da cozinha está vazando bastante água, já tem poça grande no chão",
    ]
    respostas: list[str] = []
    for texto in turnos:
        resposta = _mandar_mensagem(base_url, telefone, texto)
        print(f"  Você: {texto!r}\n  Agente: {resposta!r}")
        respostas.append(resposta)

    # Classificação é feita pela API real da Claude — se a confiança ficar
    # baixa, o A3 pede mais um esclarecimento em vez de abrir o ticket direto
    # (ver app/agents/a3_manutencao/fluxo.py). Damos mais uma chance antes de
    # desistir, em vez de marcar falso-negativo por causa disso.
    if "MNT-" not in respostas[-1]:
        esclarecimento = (
            "É vazamento moderado, contínuo, categoria hidráulica, urgência média."
        )
        resposta = _mandar_mensagem(base_url, telefone, esclarecimento)
        print(f"  Você: {esclarecimento!r}\n  Agente: {resposta!r}")
        respostas.append(resposta)

    r.ok = any("MNT-" in resp for resp in respostas)
    r.evidencia = (
        "protocolo MNT-... retornado ao inquilino"
        if r.ok
        else "nenhuma resposta trouxe protocolo MNT-... — confira manualmente (pode ter parado em "
        "'aguardando_esclarecimento'; rodar mais um turno manual via /dev/chat-simulado)"
    )
    r.observacao = "Verificar `maintenance_tickets` (protocolo/categoria/urgência) e se a equipe recebeu manutencao_equipe."
    return r


# ======================================================================
# Cenário 6 — cron de cobrança (A2), 5 estágios
# ======================================================================

_ESTAGIOS_A2 = {"D-5": -5, "D0": 0, "D+5": 5, "D+10": 10, "D+15": 15}


def _cenario_6_cron_a2(vencimento: date) -> ResultadoCenario:
    r = ResultadoCenario(6, "Cron A2 envia D-5/D0/D+5/D+10/D+15 por template")
    print(f"  Vencimento da charge de referência: {vencimento.isoformat()}")

    algum_falhou = False
    linhas_log: list[str] = []
    for rotulo, offset in _ESTAGIOS_A2.items():
        data_simulada = vencimento + timedelta(days=offset)
        print(f"  --- estágio {rotulo} (hoje simulado = {data_simulada.isoformat()}) ---")
        processo = subprocess.run(
            [sys.executable, "-m", "scripts.testar_cron_com_data", "a2", data_simulada.isoformat()],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        saida = (processo.stdout or "") + (processo.stderr or "")
        print(saida.strip())
        if processo.returncode != 0:
            algum_falhou = True
        linhas_log.extend(
            linha for linha in saida.splitlines() if "operacao=enviar_template" in linha
        )

    r.ok = not algum_falhou
    if linhas_log:
        r.evidencia = f"{len(linhas_log)} chamada(s) a enviar_template logadas (simulado=True) — ver saída acima."
    else:
        r.evidencia = (
            "nenhuma chamada a enviar_template logada em nenhum estágio — confira manualmente "
            "se a charge está no estado esperado (STATUS_PAUSADOS bloqueia o cron; ver "
            "app/agents/a2_cobranca/cobranca.py)."
        )
    r.observacao = "Cada execução é idempotente por dia — rodar de novo no mesmo dia não duplica o estágio."
    return r


# ======================================================================
# Cenário 7 — A4 envia alerta contratual
# ======================================================================


def _cenario_7_cron_a4() -> ResultadoCenario:
    r = ResultadoCenario(7, "A4 envia alerta contratual")
    processo = subprocess.run(
        [sys.executable, "-m", "scripts.rodar_a4_gestao_contratual"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    saida = (processo.stdout or "") + (processo.stderr or "")
    print(saida.strip())

    r.ok = processo.returncode == 0 and (
        "ALERTA DE RENOVAÇÃO" in saida or "CÁLCULO DE REAJUSTE" in saida
    )
    r.evidencia = (
        "script rodou e disparou alerta/cálculo simulado (fixtures fixas em HOJE=2026-07-15)"
        if r.ok
        else "script rodou mas não disparou nenhum alerta/cálculo — confira a saída acima"
    )
    r.observacao = (
        "Este script usa contratos-fixture locais (não o contrato semeado na HML-01) e "
        "simula a persistência sem tocar no Supabase — ver docstring do próprio script."
    )
    return r


# ======================================================================
# Cenário 12 — kill switch
# ======================================================================


def _cenario_12_kill_switch() -> ResultadoCenario:
    r = ResultadoCenario(12, "Kill switch impede envio real sem afetar processamento")

    import os

    import httpx

    from app.tools import whatsapp_client

    env_originais = {
        chave: os.environ.get(chave)
        for chave in (
            "WHATSAPP_ENVIO_ATIVO",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_ACCESS_TOKEN",
        )
    }
    construir_client_original = whatsapp_client._construir_client

    try:
        # --- 1) kill switch desligado (padrão) ---
        os.environ["WHATSAPP_ENVIO_ATIVO"] = "false"
        resultado_desligado = whatsapp_client.enviar_texto("+5581999990000", "teste kill switch")
        print(f"  Desligado -> {resultado_desligado.model_dump()}")

        # --- 2) kill switch ligado, transporte MOCKADO (nunca a Meta real) ---
        os.environ["WHATSAPP_ENVIO_ATIVO"] = "true"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "id-fake-homologacao-local"
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "token-fake-homologacao-local"

        def _transporte_mockado(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"messages": [{"id": "wamid.mock-homologacao-local"}]})

        def _client_mockado() -> httpx.Client:
            return httpx.Client(
                timeout=whatsapp_client.TIMEOUT_PADRAO_SEGUNDOS,
                transport=httpx.MockTransport(_transporte_mockado),
            )

        whatsapp_client._construir_client = _client_mockado
        resultado_ligado = whatsapp_client.enviar_texto("+5581999990000", "teste kill switch")
        print(f"  Ligado (mock) -> {resultado_ligado.model_dump()}")

        r.ok = (
            resultado_desligado.simulado is True
            and resultado_desligado.message_id is None
            and resultado_ligado.simulado is False
            and resultado_ligado.message_id == "wamid.mock-homologacao-local"
        )
        r.evidencia = (
            "simulado=True sem WHATSAPP_ENVIO_ATIVO, simulado=False com o kill switch ligado "
            "(transporte mockado, nenhuma chamada real à Meta)"
            if r.ok
            else "comportamento do kill switch não bateu com o esperado — ver saída acima"
        )
        r.observacao = (
            "Transporte mockado (httpx.MockTransport) — nenhuma requisição de rede real foi feita "
            "em nenhuma das duas chamadas."
        )
    finally:
        whatsapp_client._construir_client = construir_client_original
        for chave, valor in env_originais.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor

    return r


# ======================================================================
# main
# ======================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--telefone", required=True, help="Telefone semeado pela HML-01, formato +55DDD9XXXXXXXX")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="URL do servidor local (uvicorn)")
    parser.add_argument(
        "--vencimento",
        help="Data de vencimento (AAAA-MM-DD) da charge semeada. Se omitido, consulta o Supabase de teste.",
    )
    args = parser.parse_args()

    load_dotenv(_REPO_ROOT / ".env", override=False)

    if not _servidor_no_ar(args.base_url):
        print(
            f"Não consegui falar com {args.base_url}/dev/chat-simulado/ — suba o servidor antes:\n"
            "  python -m uvicorn app.api.main:app --reload\n"
            "(precisa de ENVIRONMENT != production, senão essa rota nem existe)."
        )
        sys.exit(1)

    vencimento = (
        date.fromisoformat(args.vencimento) if args.vencimento else _descobrir_vencimento_charge(args.telefone)
    )

    resultados: list[ResultadoCenario] = []

    print("\n=== Cenário 1 — A1 responde pergunta contratual [LOCAL] ===")
    resultados.append(_cenario_1_a1(args.base_url, args.telefone))

    print("\n=== Cenário 8 — A5 escala e notifica equipe [LOCAL ou REAL] ===")
    resultados.append(_cenario_8_a5(args.base_url, args.telefone))

    print("\n=== Cenário 2 — A3 abre manutenção e retorna protocolo [LOCAL ou REAL] ===")
    print("(rodado por último de propósito — ver docstring deste script)")
    resultados.append(_cenario_2_a3(args.base_url, args.telefone))

    print("\n=== Cenário 6 — Cron A2 (D-5/D0/D+5/D+10/D+15) [LOCAL] ===")
    resultados.append(_cenario_6_cron_a2(vencimento))

    print("\n=== Cenário 7 — Cron A4 (alerta contratual) [LOCAL] ===")
    resultados.append(_cenario_7_cron_a4())

    print("\n=== Cenário 12 — Kill switch [LOCAL] ===")
    resultados.append(_cenario_12_kill_switch())

    print("\n\n========== RESUMO — pronto para colar na seção 7 (Evidências) ==========\n")
    for r in resultados:
        print(r.linha_resumo())
        if r.observacao:
            print(f"        {r.observacao}")

    print(
        "\nTelefone usado (mascare antes de colar na seção 7 — só os últimos 4 dígitos visíveis): "
        f"{args.telefone}"
    )
    print(f"Data/hora desta execução: preencha manualmente ao colar na tabela (UTC ou horário local, dizer qual).")

    if any(r.ok is False for r in resultados):
        sys.exit(1)


if __name__ == "__main__":
    main()