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

# Status considerados "em aberto" pra fins de pausar_charges_em_negociacao
# (Opção A) — charges nesse estado é que precisam ser movidas pra
# 'em_negociacao' quando o orquestrador (via A5) detecta pedido de desconto.
STATUS_CHARGES_ABERTAS = ("pendente", "atrasado")


def pausar_charges_em_negociacao(contract_id: str) -> None:
    """API pública do A2 pra outros módulos chamarem quando detectarem um
    pedido de desconto/renegociação numa conversa (hoje, chamada por
    app.orchestrator.orchestrator._rotear_para_a5, logo após
    executar_escalonamento identificar motivo='desconto_renegociacao' — o
    classificador de intenção já roteia esse tipo de pedido direto pro A5,
    nunca pro A1) — mora aqui, não em quem chama, porque `charges` é dado
    do domínio do A2. O chamador só decide QUANDO pausar; COMO pausar
    (quais status, qual RPC, qual valor) é encapsulado aqui, no mesmo
    espírito de avaliar_escalonamento/executar_escalonamento serem a
    interface pública do A5 em vez de cada módulo reimplementar lógica de
    escalonamento.

    Opção A (decisão explícita, não tenta identificar a charge exata):
    marca TODAS as charges em aberto (pendente/atrasado) do contrato como
    'em_negociacao'. Não precisa de migration — 'em_negociacao' já é valor
    válido no CHECK constraint de charges.status (Migration 001), e
    agent_update_charge_status já aceita esse valor em p_status.

    Efeito: STATUS_PAUSADOS (acima) já faz o cron ignorar essas charges
    até a staff resolver via charge_negotiations (que muda o status pra
    'quitado' ou 'atrasado' — ver CobrancasSection.tsx, resolverMutation).
    """
    client = obter_client_agente(contract_id)
    resposta = (
        client.table("charges")
        .select("id")
        .eq("contract_id", contract_id)
        .in_("status", STATUS_CHARGES_ABERTAS)
        .execute()
    )
    charges_abertas = resposta.data or []

    for charge in charges_abertas:
        try:
            client.rpc(
                "agent_update_charge_status",
                {"p_charge_id": charge["id"], "p_status": "em_negociacao"},
            ).execute()
        except Exception:
            logger.exception(
                "Falha ao pausar charge %s (contrato %s) para negociação.",
                charge["id"],
                contract_id,
            )


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
    novo_status = "atrasado" if dias_atraso_hoje > 0 else charge.status

    # Estágio de MENSAGEM (-5/0/5/10/15) é uma coisa; estado objetivo de
    # atraso (dias_atraso/status) é outra. Antes as duas ficavam presas ao
    # mesmo gate, e dias_atraso só avançava nos dias em que uma mensagem
    # saía — subestimando o painel de gestão do 1º ao 4º dia (e em todo
    # intervalo fora dos estágios). Agora dias_atraso/status são
    # recalculados TODO dia; só mensagem_estagio (e o envio em si) ficam
    # restritos aos estágios definidos.
    estagio = _determinar_estagio(dias_atraso_hoje)
    deve_enviar_mensagem = estagio is not None and estagio != charge.mensagem_estagio
    novo_mensagem_estagio = estagio if deve_enviar_mensagem else charge.mensagem_estagio

    client_agente = None

    if deve_enviar_mensagem:
        client_agente = obter_client_agente(charge.contract_id)
        dados_contrato = _buscar_dados_cobranca_contrato(client_agente)

        texto = montar_mensagem(charge, dados_contrato, estagio, dias_atraso_hoje)
        enviar_mensagem_cobranca(dados_contrato.telefone_whatsapp, texto)

    # Update é feito só quando algo de fato mudou — evita RPC (e write no
    # banco) todo dia pra charges cujo dias_atraso já está correto (ex.:
    # charges ainda não vencidas, onde dias_atraso_hoje é negativo e igual
    # ao já registrado).
    precisa_atualizar = (
        dias_atraso_hoje != charge.dias_atraso
        or novo_status != charge.status
        or novo_mensagem_estagio != charge.mensagem_estagio
    )
    if precisa_atualizar:
        if client_agente is None:
            client_agente = obter_client_agente(charge.contract_id)
        client_agente.rpc(
            "agent_update_charge_status",
            {
                "p_charge_id": charge.charge_id,
                "p_status": novo_status,
                "p_dias_atraso": dias_atraso_hoje,
                "p_mensagem_estagio": novo_mensagem_estagio,
            },
        ).execute()

    if estagio == "d+15" and deve_enviar_mensagem:
        # Disparado pelo PROCESSO (este cron), não por mensagem do inquilino
        # — por isso não passa por avaliar_escalonamento (que só avalia
        # texto de conversa), e sim monta o AvaliacaoEscalonamento direto e
        # chama executar_escalonamento, reaproveitando o mesmo protocolo/
        # notificação do A5. Ver criterios.py: motivo="atraso_severo",
        # deteccao_via_mensagem=False.
        #
        # deve_enviar_mensagem=True aqui garante que só escalamos no dia em
        # que d+15 é *alcançado pela primeira vez*, não em todo dia
        # subsequente (16, 17, 18...) em que dias_atraso_hoje continua >= 15
        # mas mensagem_estagio já é "d+15" — senão duplicaria o
        # escalonamento a cada execução do cron.
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