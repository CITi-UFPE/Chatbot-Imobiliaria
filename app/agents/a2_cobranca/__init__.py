from app.agents.a2_cobranca.cobranca import executar_cobranca_diaria, pausar_charges_em_negociacao
from app.agents.a2_cobranca.comprovante import (
    confirmar_pagamento,
    confirmar_pagamento_combinado,
    iniciar_escolha_pagamento_parcial,
    marcar_apenas_uma_paga,
    marcar_valor_divergente,
    processar_comprovante_recebido,
)
from app.agents.a2_cobranca.orquestrador_a2 import EntradaA2, TipoEntradaA2, processar_entrada_a2
from app.agents.a2_cobranca.schemas import ChargeAtiva, ComprovanteExtraido, DadosCobrancaContrato

__all__ = [
    # Ponto de entrada recomendado pro orquestrador geral chamar:
    "processar_entrada_a2",
    "EntradaA2",
    "TipoEntradaA2",
    # Cron (chamado direto por app/jobs/cron_cobranca_diaria.py, não pelo
    # orquestrador de mensagens):
    "executar_cobranca_diaria",
    # API pública pra outros agentes (hoje: orchestrator) pausarem cobrança durante
    # negociação — ver docstring em cobranca.py:pausar_charges_em_negociacao
    "pausar_charges_em_negociacao",
    # Funções internas — ainda exportadas pra quem precisar chamar direto
    # (ex: testes), mas processar_entrada_a2 é o caminho recomendado:
    "processar_comprovante_recebido",
    "confirmar_pagamento",
    "marcar_valor_divergente",
    "confirmar_pagamento_combinado",
    "iniciar_escolha_pagamento_parcial",
    "marcar_apenas_uma_paga",
    "ChargeAtiva",
    "ComprovanteExtraido",
    "DadosCobrancaContrato",
]