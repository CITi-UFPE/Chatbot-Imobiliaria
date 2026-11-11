"""Corpos dos templates Meta enviados à administradora, pra gravar em
conversation_logs o texto que ela recebeu.

Espelham docs/whatsapp/templates-meta.md (seções comprovante_para_conferencia,
pagamento_combinado, pagamento_combinado_resolucao_manual, alerta_contratual,
escalonamento_equipe e manutencao_equipe). O envio em si manda nome +
parâmetros e a Meta monta o corpo aprovado; se o corpo aprovado no WhatsApp
Manager mudar, atualizar aqui também. Os corpos dos templates de cobrança ao
inquilino ficam em app/agents/a2_cobranca/mensagens.py.
"""

from app.tools.whatsapp_message_policy import MensagemTemplate

_CORPOS_TEMPLATE_ADMINISTRADORA: dict[str, str] = {
    "comprovante_para_conferencia": (
        "Novo comprovante recebido\n\n"
        "Inquilino: {{1}}\nImóvel: {{2}}\n\n"
        "Valor identificado: {{3}}\nData identificada: {{4}}\n"
        "Valor esperado (contrato): R$ {{5}}\nCritério da correspondência: {{6}}\n\n"
        "Aguardando sua conferência."
    ),
    "pagamento_combinado": (
        "Comprovante recebido — possível pagamento combinado\n\n"
        "Inquilino: {{1}}\nImóvel: {{2}}\n\n"
        "Valor identificado: {{3}}\nData identificada: {{4}}\n\n"
        "Charges em aberto que juntas somam esse valor (R$ {{5}}):\n{{6}}\n\n"
        "Revise as cobranças e selecione uma opção abaixo."
    ),
    "pagamento_combinado_resolucao_manual": (
        "Comprovante recebido — resolução manual necessária\n\n"
        "Inquilino: {{1}}\nImóvel: {{2}}\n\n"
        "Valor identificado: {{3}}\nData identificada: {{4}}\n\n"
        "Cobranças em aberto:\n{{5}}\n\n"
        "Não foi possível distinguir automaticamente a cobrança paga porque há mais de uma "
        "cobrança do mesmo tipo. Acesse a plataforma, localize a cobrança correta, informe a "
        "data e o valor pagos e marque-a como paga."
    ),
    "alerta_contratual": (
        "Alerta de gestão contratual — {{1}}\n\n{{2}}\n\n"
        "Revise as informações e prossiga com a ação necessária."
    ),
    "escalonamento_equipe": (
        "Novo caso escalado — protocolo {{1}}\n"
        "Inquilino: {{4}} — {{5}}\nTelefone: {{6}}\n"
        "Motivo: {{2}}\n{{3}}\n\n"
        "O caso aguarda acompanhamento da equipe."
    ),
    "manutencao_equipe": (
        "Novo chamado de manutenção — {{1}}\nImóvel: {{2}}\nCategoria: {{3}}\n"
        "Urgência: {{4}}\nDescrição do inquilino: {{5}}\n\n"
        "O chamado aguarda acompanhamento da equipe."
    ),
}


def renderizar_template_administradora(nome: str, parametros: tuple[str, ...] | list[str]) -> str:
    """Texto do template já com os parâmetros no lugar. Template desconhecido
    cai num formato `[nome] p1 | p2` — nunca levanta, o log não pode quebrar o
    envio."""
    corpo = _CORPOS_TEMPLATE_ADMINISTRADORA.get(nome)
    if corpo is None:
        return f"[{nome}] " + " | ".join(str(p) for p in parametros)
    # Substitui do maior índice pro menor: "{{1}}" não pode comer o começo de "{{10}}".
    for indice in range(len(parametros), 0, -1):
        corpo = corpo.replace("{{" + str(indice) + "}}", str(parametros[indice - 1]))
    return corpo


def renderizar_mensagem_administradora(mensagem: MensagemTemplate) -> str:
    return renderizar_template_administradora(mensagem.nome, mensagem.parametros)
