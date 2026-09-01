"""Semeia contrato(s) fictício(s) de homologação no Supabase de TESTE.

Uso:
    python scripts/semear_contrato_homologacao.py --dry-run
    python scripts/semear_contrato_homologacao.py
    python scripts/semear_contrato_homologacao.py --limpar

Telefones: variável de ambiente TELEFONES_HOMOLOGACAO (separados por
vírgula) ou --telefones na linha de comando. Nunca hardcoded.

Lê SUPABASE_TEST_URL/SUPABASE_TEST_SERVICE_ROLE_KEY de .env.test (nunca de
.env de produção) e recusa rodar se não estiverem presentes ou se a URL não
parecer claramente um projeto de teste.

Marca cada contrato criado com imovel_identificacao começando em
"[Homologação]" — é esse marcador que --limpar usa pra decidir o que
apagar, nunca um delete sem filtro.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MARCADOR = "[Homologação]"
_PREFIXO_TELEFONE_INTEGRACAO = "+551199990"  # usado por tests/integration — nunca reutilizar


def _carregar_ambiente() -> tuple[str, str]:
    load_dotenv(_REPO_ROOT / ".env.test", override=True)
    url = os.environ.get("SUPABASE_TEST_URL", "")
    chave = os.environ.get("SUPABASE_TEST_SERVICE_ROLE_KEY", "")

    if not url or not chave:
        print(
            "Faltam SUPABASE_TEST_URL / SUPABASE_TEST_SERVICE_ROLE_KEY.\n"
            "Copie .env.test.example para .env.test e preencha com as "
            "credenciais do projeto Supabase de TESTE (nunca produção)."
        )
        sys.exit(1)

    if ".supabase.co" not in url:
        print(
            f"SUPABASE_TEST_URL não parece um projeto Supabase válido: {url!r}\n"
            "Confira antes de continuar — este script não deve rodar contra nada "
            "que não seja claramente o projeto de teste."
        )
        resposta = input("Continuar mesmo assim? (digite 'sim' para confirmar): ")
        if resposta.strip().lower() != "sim":
            sys.exit(1)

    return url, chave


def _telefones(args: argparse.Namespace) -> list[str]:
    bruto = args.telefones or os.environ.get("TELEFONES_HOMOLOGACAO", "")
    telefones = [t.strip() for t in bruto.split(",") if t.strip()]
    if not telefones:
        print(
            "Nenhum telefone informado. Use --telefones '+55...,+55...' ou "
            "defina TELEFONES_HOMOLOGACAO no ambiente."
        )
        sys.exit(1)
    for t in telefones:
        if t.startswith(_PREFIXO_TELEFONE_INTEGRACAO):
            print(
                f"Telefone {t} usa o prefixo reservado a tests/integration/ "
                f"({_PREFIXO_TELEFONE_INTEGRACAO}...) — escolha outro, pra não colidir "
                "com a suíte automatizada."
            )
            sys.exit(1)
    return telefones


def _contrato_homologacao(telefone: str, indice: int) -> dict[str, Any]:
    hoje = date.today()
    data_vencimento_charge = hoje + timedelta(days=5)  # cai perto do D-5 do A2, útil pra teste manual
    return {
        "imovel_identificacao": f"{_MARCADOR} Apto Teste {indice:03d}",
        "imovel_endereco": "Rua Fictícia de Homologação, 000 — Recife/PE",
        "tipo_locatario": "pf",
        "inquilino_nome": f"Homologação {indice:03d}",
        "inquilino_cpf_cnpj": "00000000000",
        "telefone_whatsapp": telefone,
        "garantia_tipo": "fiador",
        "fiador_nome": "Fiador de Homologação",
        "fiador_cpf": "11111111111",
        "valor_aluguel": 1500.0,
        "dia_vencimento": data_vencimento_charge.day,
        "vencimento_mes_referencia": "atual",
        "data_inicio": (hoje - timedelta(days=180)).isoformat(),
        "data_termino": (hoje + timedelta(days=545)).isoformat(),
        "indice_reajuste": "igpm",
        "multa_infracao_tipo": "meses_aluguel",
        "multa_infracao_valor": 3,
        "multa_moratoria_percentual": 0.02,
        "juros_moratorio_mensal": 0.01,
        "aviso_previo_dias": 30,
        "aviso_previo_a_partir_mes": 1,
        "status": "ativo",
    }, data_vencimento_charge


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telefones", help="Telefones separados por vírgula (ou use TELEFONES_HOMOLOGACAO)")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que seria inserido, sem gravar")
    parser.add_argument("--limpar", action="store_true", help="Remove só os contratos marcados [Homologação]")
    args = parser.parse_args()

    url, chave = _carregar_ambiente()

    from supabase import create_client  # import tardio: falha rápida acima antes de precisar da lib

    client = create_client(url, chave)

    if args.limpar:
        existentes = (
            client.table("contracts")
            .select("id, imovel_identificacao, telefone_whatsapp")
            .like("imovel_identificacao", f"{_MARCADOR}%")
            .execute()
        )
        if not existentes.data:
            print("Nada marcado com [Homologação] encontrado — nada a apagar.")
            return
        for c in existentes.data:
            print(f"Apagando {c['imovel_identificacao']!r} ({c['telefone_whatsapp']})")
        client.table("contracts").delete().like("imovel_identificacao", f"{_MARCADOR}%").execute()
        print(f"{len(existentes.data)} contrato(s) de homologação removido(s).")
        return

    telefones = _telefones(args)

    for i, telefone in enumerate(telefones, start=1):
        existente = (
            client.table("contracts")
            .select("id")
            .eq("telefone_whatsapp", telefone)
            .like("imovel_identificacao", f"{_MARCADOR}%")
            .execute()
        )
        if existente.data:
            print(f"Já existe contrato de homologação para {telefone} (id={existente.data[0]['id']}) — pulando.")
            continue

        dados, data_vencimento_charge = _contrato_homologacao(telefone, i)
        charge = {
            "tipo": "aluguel",
            "mes_referencia": data_vencimento_charge.replace(day=1).isoformat(),
            "valor_esperado": dados["valor_aluguel"],
            "data_vencimento": data_vencimento_charge.isoformat(),
            "status": "pendente",
        }

        if args.dry_run:
            print(f"[dry-run] Criaria contrato para {telefone}:")
            print(f"  {dados}")
            print(f"  charge: {charge}")
            continue

        resposta = client.table("contracts").insert(dados).execute()
        contract_id = resposta.data[0]["id"]
        charge["contract_id"] = contract_id
        client.table("charges").insert(charge).execute()
        print(f"Criado: telefone={telefone} contract_id={contract_id}")

    if args.dry_run:
        print("\n[dry-run] Nada foi gravado.")


if __name__ == "__main__":
    main()
