"""Script agendado (Railway Cron) — cobrança diária do A2.

Roda 1x/dia via `python -m app.jobs.cron_cobranca_diaria`, num serviço
Railway Cron dedicado (cada serviço de cron aceita só um horário de disparo,
por isso é um serviço separado do cron_alertas_contratuais.py). Reaproveita
as mesmas funções de negócio do agente A2 — sem duplicar lógica de
cobrança aqui nem em SQL.

Duas etapas, nesta ordem:
  1. gerar_charges_aluguel — cria a charge de aluguel dos contratos cujo
     vencimento está chegando (Migration 025). Falha aqui é logada e NÃO
     impede a etapa 2: as charges que já existem continuam sendo cobradas.
  2. executar_cobranca_diaria — estágios D-5/D0/D+5/D+10/D+15, que já
     enxerga as charges criadas na etapa 1.
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    from app.agents.a2_cobranca import executar_cobranca_diaria, gerar_charges_aluguel

    try:
        gerar_charges_aluguel()
    except Exception:
        logger.exception("Falha na geração de charges de aluguel — seguindo com a cobrança do dia.")

    executar_cobranca_diaria()
    return 0


if __name__ == "__main__":
    sys.exit(main())
