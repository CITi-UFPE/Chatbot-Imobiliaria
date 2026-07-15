"""Teste manual e simulado, de ponta a ponta, do Agente 3 (manutenção).

Roda a conversa real no terminal: você digita como o inquilino, e o fluxo
(app/agents/a3_manutencao/fluxo.py) processa cada turno usando a classificação
REAL da API Claude (classificar_manutencao / gerar_pergunta_esclarecimento).

Abertura de ticket e escalonamento são simulados localmente (sem tocar no
Supabase real) — gera um protocolo fake e imprime o que seria enviado à
gestora, já que a assinatura do JWT do agente é escopo de feat/jwt-webhook-a5
(ver docs/specs/agente-manutencao.md).

Uso:
    python -m scripts.chat_a3_manutencao
"""

import itertools
import sys
from uuid import uuid4

from app.agents.a3_manutencao.fluxo import (
    EstadoAtendimentoManutencao,
    iniciar_atendimento,
    processar_turno,
)
from app.models.maintenance import ClassificacaoManutencao, TicketManutencao

IMOVEL_ENDERECO = "Ed. Residencial das Flores"
IMOVEL_NUMERO = "302"

_contador_protocolo = itertools.count(1)


def _abrir_ticket_fake(
    classificacao: ClassificacaoManutencao, descricao: str, incerta: bool
) -> TicketManutencao:
    protocolo = f"MNT-2026-{next(_contador_protocolo):04d}"
    return TicketManutencao(
        id=uuid4(),
        protocolo=protocolo,
        categoria=classificacao.categoria,
        urgencia=classificacao.urgencia,
        descricao=descricao,
        sinais_risco=classificacao.sinais_risco,
        classificacao_incerta=incerta,
    )


def _criar_escalonamento_fake(motivo: str, descricao: str) -> None:
    print(f"\n[ESCALONAMENTO SIMULADO] motivo={motivo!r} descricao={descricao!r}\n")


def main() -> None:
    # Console do Windows (cp1252) quebra nos emojis da notificação (🔧🔴🟡🟢) sem isto.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=== Teste manual — Agente 3 (Manutenção) ===")
    print(f"Imóvel simulado: apto {IMOVEL_NUMERO}, {IMOVEL_ENDERECO}")
    print("(classificação real via API Claude; ticket/escalonamento simulados localmente)\n")

    resultado = iniciar_atendimento(IMOVEL_ENDERECO, IMOVEL_NUMERO)
    print(f"Agente: {resultado.resposta_inquilino}")

    estado = resultado.estado
    while estado.etapa != "finalizado":
        try:
            mensagem = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrado.")
            return

        if not mensagem:
            continue

        resultado = processar_turno(
            estado,
            mensagem,
            imovel_endereco=IMOVEL_ENDERECO,
            imovel_numero=IMOVEL_NUMERO,
            abrir_ticket_fn=_abrir_ticket_fake,
            criar_escalonamento_fn=_criar_escalonamento_fake,
        )
        estado = resultado.estado

        print(f"Agente: {resultado.resposta_inquilino}")

        if resultado.ticket is not None:
            print(f"\n[TICKET SIMULADO] {resultado.ticket.model_dump()}")
        if resultado.notificacao_gestora is not None:
            print(f"\n[NOTIFICAÇÃO À GESTORA]\n{resultado.notificacao_gestora}")

    print("\n=== Atendimento finalizado ===")


if __name__ == "__main__":
    main()
