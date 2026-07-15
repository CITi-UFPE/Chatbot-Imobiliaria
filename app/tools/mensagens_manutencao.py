from typing import Optional

from app.models.maintenance import TicketManutencao, UrgenciaManutencao

_EMOJI_URGENCIA = {"alta": "🔴", "media": "🟡", "baixa": "🟢"}


def prazo_resposta(urgencia: UrgenciaManutencao) -> Optional[str]:
    if urgencia == "alta":
        return "1h"
    if urgencia == "media":
        return "24h"
    return None


def montar_notificacao_gestora(
    ticket: TicketManutencao,
    imovel_endereco: str,
    imovel_numero: str,
    descricao_inquilino: str,
) -> str:
    prazo = prazo_resposta(ticket.urgencia)
    prazo_texto = prazo if prazo else "sem prazo — fila programada"
    sinais_texto = ", ".join(ticket.sinais_risco) if ticket.sinais_risco else "nenhum"
    incerteza = "\n⚠️ Classificação com incerteza — revisar" if ticket.classificacao_incerta else ""

    return (
        f"🔧 Novo chamado de manutenção — {ticket.protocolo}\n\n"
        f"Imóvel: {imovel_endereco}, apto {imovel_numero}\n"
        f"Categoria: {ticket.categoria}\n"
        f"Urgência: {ticket.urgencia} {_EMOJI_URGENCIA[ticket.urgencia]}\n"
        f'Descrição do inquilino: "{descricao_inquilino}"\n'
        f"Sinais de risco: {sinais_texto}\n"
        f"Prazo de resposta: {prazo_texto}"
        f"{incerteza}"
    )


def montar_confirmacao_inquilino(ticket: TicketManutencao) -> str:
    if ticket.urgencia == "alta":
        return (
            f"Registrei seu chamado ({ticket.protocolo}) como urgente e já avisei a gestora agora. "
            "Você deve receber um retorno em até 1h. Se for risco imediato (gás, fumaça, choque), "
            "procure ajuda de emergência agora."
        )
    return f"Chamado {ticket.protocolo} aberto e encaminhado. Você deve receber um retorno em até 24h."
