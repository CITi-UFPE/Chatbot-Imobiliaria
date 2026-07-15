"""Script agendado (Railway Cron) — cobrança diária do A2.

Roda 1x/dia via `python -m app.jobs.cron_cobranca_diaria`, num serviço
Railway Cron dedicado (cada serviço de cron aceita só um horário de disparo,
por isso é um serviço separado do cron_alertas_contratuais.py). Reaproveita
a mesma função de negócio já usada pelo agente A2 — sem duplicar lógica de
cobrança aqui nem em SQL.

Estado atual: app/agents/a2_cobranca/ ainda não tem nenhuma função de
negócio implementada (só o pacote vazio). Este script já está pronto pra
rodar assim que ela existir — só falta o import abaixo parar de falhar. A
estrutura (logging, código de saída, ponto único de entrada) não deve
precisar mudar quando isso acontecer.
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        from app.agents.a2_cobranca import executar_cobranca_diaria
    except ImportError:
        logger.error(
            "app.agents.a2_cobranca.executar_cobranca_diaria ainda não existe — "
            "este script está pronto pra rodar assim que a lógica de negócio do A2 "
            "for implementada. Nada foi executado."
        )
        return 1

    executar_cobranca_diaria()
    return 0


if __name__ == "__main__":
    sys.exit(main())
