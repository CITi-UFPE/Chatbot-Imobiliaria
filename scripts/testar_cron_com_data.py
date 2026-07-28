"""Roda o cron de cobrança (A2) ou de alertas contratuais (A4) fingindo que
"hoje" é uma data escolhida — útil pra testar os estágios D-5/D0/D+5/D+10/
D+15 (A2) ou D-60/D-30 (A4) sem precisar esperar a data real bater com o
vencimento de uma charge/contrato de teste.

Não manda nada de verdade pro WhatsApp (sem WHATSAPP_ACCESS_TOKEN, só
loga) — mas ESCREVE de verdade no banco (marca charge/alerta como
disparado, idempotente por dia). Rodar só contra dados de teste.

Uso (a partir da RAIZ do repo — precisa ser -m, não o caminho do arquivo
direto, senão o Python não acha o pacote `app`):
    python -m scripts.testar_cron_com_data a2 2026-08-01
    python -m scripts.testar_cron_com_data a4 2026-08-01

Pra A4 já existe um script mais completo da Julia com mais opções —
scripts/rodar_a4_gestao_contratual.py. Este aqui cobre os dois agentes com
a mesma interface simples, útil pra bater rapidinho as duas datas seguidas.
"""

import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("a2", "a4"):
        print("Uso: python -m scripts.testar_cron_com_data [a2|a4] AAAA-MM-DD")
        sys.exit(1)

    agente = sys.argv[1]
    hoje = date.fromisoformat(sys.argv[2])

    if agente == "a2":
        from app.agents.a2_cobranca import executar_cobranca_diaria

        print(f"Rodando cron de cobrança (A2) fingindo hoje = {hoje}...")
        executar_cobranca_diaria(hoje=hoje)
    else:
        from app.agents.a4_gestao_contratual import executar_alertas_contratuais

        print(f"Rodando cron de alertas contratuais (A4) fingindo hoje = {hoje}...")
        resultado = executar_alertas_contratuais(hoje=hoje)
        print(f"Alertas de renovação: {len(resultado.alertas_renovacao)}")
        print(f"Cálculos de reajuste: {len(resultado.calculos_reajuste)}")
        print(f"Reajustes aplicados: {len(resultado.reajustes_aplicados)}")
        if resultado.erros:
            print(f"Erros: {resultado.erros}")

    print("\nConcluído — confira os logs acima (mensagens/escalonamentos que seriam enviados).")


if __name__ == "__main__":
    main()
