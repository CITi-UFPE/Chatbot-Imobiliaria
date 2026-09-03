"""Script agendado (Railway Cron) — alertas de renovação (D-60) e cálculo de
reajuste (D-30) do A4.

Roda 1x/dia via `python -m app.jobs.cron_alertas_contratuais`, num serviço
Railway Cron separado do cron_cobranca_diaria.py (cada serviço de cron
aceita só um horário de disparo). Reaproveita a mesma função de negócio já
usada pelo agente A4 — sem duplicar lógica de reajuste/renovação aqui nem em
SQL.

A4 já está implementado (app/agents/a4_gestao_contratual/fluxo.py) — o
try/except de ImportError abaixo é só defesa histórica, não reflete mais o
estado atual.

Loga o resumo do resultado (e cada erro capturado, contrato por contrato,
via a mesma isolação de falha de executar_alertas_contratuais) porque o
Railway Cron não expõe valor de retorno nenhum: sem logar aqui, um erro
isolado por contrato (ex: falha ao enviar WhatsApp) processa silenciosamente
e o job "termina bem" (exit 0) sem ninguém saber que algo não foi
transportado.
"""

import logging
import sys
from datetime import date

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

    hoje = date.today()
    resultado = executar_alertas_contratuais()
    logger.info(
        "Cron de alertas contratuais: %d alerta(s) de renovacao, %d calculo(s) de "
        "reajuste, %d reajuste(s) aplicado(s), %d contrato(s) finalizado(s)/em "
        "pendencia de renovacao, %d erro(s) em %s.",
        len(resultado.alertas_renovacao),
        len(resultado.calculos_reajuste),
        len(resultado.reajustes_aplicados),
        len(resultado.contratos_finalizados)
        + len(resultado.contratos_pendentes_renovacao)
        + len(resultado.contratos_transicionados_indeterminado),
        len(resultado.erros),
        hoje,
    )
    for erro in resultado.erros:
        logger.error("Cron de alertas contratuais — erro: %s", erro)
    return 0


if __name__ == "__main__":
    sys.exit(main())
