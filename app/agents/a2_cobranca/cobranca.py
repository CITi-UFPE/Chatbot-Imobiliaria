"""Agente 2 — Cobrança e Inadimplência. Núcleo do cron diário.

Fluxo, em duas camadas de autenticação (ver Migration 008 e
agent_auth_ADICIONAR.py):

  1. obter_client_cron_batch() — só leitura, cross-contrato, só pra decidir
     QUAIS charges precisam de ação hoje (cron_listar_charges_ativas).
  2. Para cada charge que precisa de ação, troca pro client normal do
     agente_ia (obter_client_agente(contract_id)) — mesmo padrão do A1 — pra
     buscar dado pessoal (buscar_dados_cobranca_contrato) e para escrever
     (agent_update_charge_status estendida, Migration 011).

Timezone fixo em America/Recife (zoneinfo, não o timezone do host) — sem
isso, rodar num serviço Railway com timezone diferente do esperado faria
"hoje" calcular errado e disparar mensagem no dia trocado.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.agents.a2_cobranca.mensagens import montar_mensagem
from app.agents.a2_cobranca.notificacao import enviar_mensagem_cobranca
from app.agents.a2_cobranca.schemas import ChargeAtiva, DadosCobrancaContrato, EstagioCobranca
from app.agents.a5_escalonamento import AvaliacaoEscalonamento, executar_escalonamento
from app.orchestrator.agent_auth import obter_client_agente, obter_client_cron_batch

logger = logging.getLogger(__name__)

TIMEZONE_COBRANCA = ZoneInfo("America/Recife")

# Status que pausam a cobrança automática — negociação em andamento
# (charge_negotiations), comprovante já em análise pela Fernanda, ou já
# confirmado/quitado. Nenhuma mensagem D-5/D0/D+5/D+10/D+15 deve sair pra
# esses casos, mesmo que a data bata com um estágio.
STATUS_PAUSADOS = frozenset({"em_negociacao", "aguardando_confirmacao", "confirmado", "quitado"})


def _determinar_estagio(dias_atraso: int) -> EstagioCobranca | None:
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


def _buscar_dados_cobranca_contrato(client_agente) -> DadosCobrancaContrato:
    resposta = client_agente.rpc("buscar_dados_cobranca_contrato", {}).execute()
    dados = resposta.data or {}
    return DadosCobrancaContrato.model_validate(dados)


def _processar_charge(charge_raw: dict, hoje: date) -> None:
    charge = ChargeAtiva.model_validate(charge_raw)

    if charge.status in STATUS_PAUSADOS:
        return  # pausa automática — negociação, análise de comprovante, ou já resolvido

    dias_atraso_hoje = (hoje - charge.data_vencimento).days
    estagio = _determinar_estagio(dias_atraso_hoje)
    if estagio is None:
        return

    if estagio == charge.mensagem_estagio:
        return  # já mandamos a mensagem desse estágio, não repetir

    client_agente = obter_client_agente(charge.contract_id)
    dados_contrato = _buscar_dados_cobranca_contrato(client_agente)

    texto = montar_mensagem(charge, dados_contrato, estagio, dias_atraso_hoje)
    enviar_mensagem_cobranca(dados_contrato.telefone_whatsapp, texto)

    novo_status = "atrasado" if dias_atraso_hoje > 0 else charge.status
    client_agente.rpc(
        "agent_update_charge_status",
        {
            "p_charge_id": charge.charge_id,
            "p_status": novo_status,
            "p_dias_atraso": dias_atraso_hoje,
            "p_mensagem_estagio": estagio,
        },
    ).execute()

    if estagio == "d+15":
        # Disparado pelo PROCESSO (este cron), não por mensagem do inquilino
        # — por isso não passa por avaliar_escalonamento (que só avalia
        # texto de conversa), e sim monta o AvaliacaoEscalonamento direto e
        # chama executar_escalonamento, reaproveitando o mesmo protocolo/
        # notificação do A5. Ver criterios.py: motivo="atraso_severo",
        # deteccao_via_mensagem=False.
        avaliacao = AvaliacaoEscalonamento(
            motivo="atraso_severo",
            descricao=(
                f"{charge.tipo.capitalize()} do imóvel {dados_contrato.imovel_identificacao} "
                f"em atraso há {dias_atraso_hoje} dias, sem comprovante de pagamento. "
                f"Detectado automaticamente pelo cron diário do A2."
            ),
            resposta_para_inquilino="",  # não aplicável — este caminho não responde chat nenhum
        )
        executar_escalonamento(charge.contract_id, avaliacao)


def executar_cobranca_diaria(hoje: date | None = None) -> None:
    """Ponto de entrada chamado por app/jobs/cron_cobranca_diaria.py.

    `hoje` é opcional e serve só pra permitir travar a data em testes/
    cenários (ex.: fixtures com offsets como -5, +15 dias em relação a uma
    data de referência fixa). Em produção, o cron real nunca passa esse
    argumento — o cálculo continua sendo `datetime.now()` no timezone de
    Recife, garantindo que "hoje" seja sempre o dia corrente de verdade
    quando rodando via Railway Cron.
    """
    if hoje is None:
        hoje = datetime.now(TIMEZONE_COBRANCA).date()

    client_cron = obter_client_cron_batch()
    resposta = client_cron.rpc("cron_listar_charges_ativas", {}).execute()
    charges_ativas = resposta.data or []

    logger.info("Cron de cobrança: %s charges ativas para avaliar em %s.", len(charges_ativas), hoje)

    for charge_raw in charges_ativas:
        try:
            _processar_charge(charge_raw, hoje)
        except Exception:
            # Uma charge com dado inconsistente não pode travar o lote
            # inteiro — loga e segue pras próximas, igual ao padrão de
            # tolerância a erro já usado em processar_mensagem_recebida.
            logger.exception(
                "Falha ao processar charge %s (contrato %s) — pulando.",
                charge_raw.get("charge_id"),
                charge_raw.get("contract_id"),
            )