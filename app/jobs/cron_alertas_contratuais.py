"""Script agendado (Railway Cron) — alertas de renovação (D-60) e cálculo de
reajuste (D-30) do A4.

Roda 1x/dia via `python -m app.jobs.cron_alertas_contratuais`, num serviço
Railway Cron separado do cron_cobranca_diaria.py (cada serviço de cron
aceita só um horário de disparo). Reaproveita a mesma função de negócio já
usada pelo agente A4 — sem duplicar lógica de reajuste/renovação aqui nem em
SQL.

Estado atual: app/agents/a4_gestao_contratual/ ainda não tem nenhuma função
de negócio implementada (só o pacote vazio). Este script já está pronto pra
rodar assim que ela existir — só falta o import abaixo parar de falhar.
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        from app.agents.a4_gestao_contratual import executar_alertas_contratuais
    except ImportError:
        logger.error(
            "app.agents.a4_gestao_contratual.executar_alertas_contratuais ainda não "
            "existe — este script está pronto pra rodar assim que a lógica de negócio "
            "do A4 (alertas D-60 / D-30) for implementada. Nada foi executado."
        )
        return 1

    executar_alertas_contratuais()
    return 0


if __name__ == "__main__":
    sys.exit(main())
