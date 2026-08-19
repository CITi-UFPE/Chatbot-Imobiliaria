"""
Extrai um contrato via Claude (sempre Sonnet — mais barato, e nos testes com
01-04 bateu igual ou melhor que Opus em campos-chave, ver
scripts/PLANO_teste_modelos_extracao.md) e imprime um relatório curto de
conferência manual: contagem de cláusulas, campos-chave do contrato, qual
cláusula o A4 identificaria como a de reajuste (mesma lógica de
app/tools/calculo_reajuste.py::identificar_clausula_reajuste), e as
observações que o modelo registrou sobre ambiguidades do contrato.

Salva o JSON completo em data/extracoes/<nome_do_pdf>.json (mesmo destino de
sempre) e não grava nada no Supabase — só extração + relatório de leitura.

Uso (sempre como módulo, a partir da raiz do repo — senão `app` não é encontrado):
    python -m scripts.extrair_contrato_com_relatorio "data/contratos/01_[...].pdf"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.tools.calculo_reajuste import identificar_clausula_reajuste
from app.tools.contract_extraction import DIRETORIO_EXTRACOES, extrair_dados_contrato

logging.basicConfig(level=logging.INFO, format="%(message)s")

MODEL = "claude-sonnet-5"


def _imprimir_relatorio(caminho_pdf: Path, resultado) -> None:
    c = resultado.contrato
    clausulas = resultado.clausulas

    print(f"\n{'=' * 60}")
    print(f"RELATÓRIO — {caminho_pdf.name}")
    print(f"modelo: {MODEL}")
    print(f"{'=' * 60}")

    print(f"\ncláusulas extraídas: {len(clausulas)}")

    print("\n--- campos-chave ---")
    print(f"  tipo_locatario:              {c.tipo_locatario}")
    print(f"  valor_aluguel:                {c.valor_aluguel}")
    print(f"  data_inicio / data_termino:   {c.data_inicio} -> {c.data_termino}")
    print(f"  indice_reajuste:              {c.indice_reajuste}")
    print(f"  data_aniversario_reajuste:    {c.data_aniversario_reajuste}")
    print(f"  garantia_tipo / valor:        {c.garantia_tipo} / {c.garantia_valor}")
    print(f"  multa_infracao (tipo/valor):  {c.multa_infracao_tipo} / {c.multa_infracao_valor}")
    print(f"  multa_moratoria_percentual:   {c.multa_moratoria_percentual}")
    print(f"  banco_agencia / banco_conta:  {c.banco_agencia} / {c.banco_conta}")

    clausulas_financeiras = [
        (cl.numero_clausula, cl.texto_clausula) for cl in clausulas if cl.categoria == "financeiro"
    ]
    numero_clausula_reajuste = identificar_clausula_reajuste(clausulas_financeiras)
    print("\n--- o que o A4 enxergaria ---")
    print(f"  cláusulas categoria=financeiro: {len(clausulas_financeiras)}")
    print(f"  cláusula de reajuste identificada: {numero_clausula_reajuste or 'NÃO IDENTIFICADA'}")

    contagem_por_categoria: dict[str, int] = {}
    for cl in clausulas:
        contagem_por_categoria[cl.categoria] = contagem_por_categoria.get(cl.categoria, 0) + 1
    print("\n--- cláusulas por categoria ---")
    for categoria, qtd in sorted(contagem_por_categoria.items()):
        print(f"  {categoria}: {qtd}")

    if c.observacoes:
        print("\n--- observações do modelo (ambiguidades do contrato) ---")
        print(f"  {c.observacoes}")

    print(f"\n{'=' * 60}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("caminho_pdf", help="Caminho do PDF do contrato a extrair")
    args = parser.parse_args()

    caminho_pdf = Path(args.caminho_pdf)
    resultado = extrair_dados_contrato(str(caminho_pdf), model=MODEL)

    DIRETORIO_EXTRACOES.mkdir(parents=True, exist_ok=True)
    caminho_saida = DIRETORIO_EXTRACOES / f"{caminho_pdf.stem}.json"
    caminho_saida.write_text(resultado.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")

    _imprimir_relatorio(caminho_pdf, resultado)
    print(f"JSON completo salvo em: {caminho_saida}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
