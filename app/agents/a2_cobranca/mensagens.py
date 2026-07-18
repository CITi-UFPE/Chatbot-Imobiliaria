"""Templates das mensagens de cobrança — D-5/D0/D+5/D+10/D+15.

Textos de 'aluguel' são cópia literal da doc validada com o cliente
(docs/specs/mensagens-cobranca.md) — não reescrever o tom sem confirmar de
novo com quem validou.

Textos de 'conta' (água, e no futuro possivelmente gás ou outras contas do
imóvel) são um template genérico próprio, mais simples e direto que o de
aluguel — decisão explícita: já que charges.tipo hoje só aceita 'agua'
(Migration 001), mas a ideia é generalizar pra "conta do imóvel" sem
precisar reescrever mensagem a cada tipo novo que aparecer (gás, por
exemplo, exigiria só um valor novo no CHECK constraint + uma entrada no
dicionário ROTULOS_CONTA abaixo — não uma nova função de mensagem).

Decisão confirmada: aluguel e conta NUNCA são combinados numa mensagem só,
mesmo quando vencem no mesmo dia — o inquilino recebe duas mensagens
separadas. Ver cobranca.py: cada linha de `charges` (cada charge_id) é
processada e notificada de forma independente.

Nota sobre o rótulo do estágio: a Mensagem 1 na doc está com um conflito
interno — o título diz "D-5" mas o texto do gatilho diz "2 dias antes do
vencimento". Segui o nome do estágio (5 dias), até porque
charges.mensagem_estagio só aceita literalmente 'd-5' no CHECK constraint
(não existe 'd-2' no schema).
"""

from app.agents.a2_cobranca.schemas import ChargeAtiva, DadosCobrancaContrato, EstagioCobranca

# Generalização de propósito: hoje só 'agua' é um tipo válido em
# charges.tipo (Migration 001), mas a mensagem de "conta" é escrita para
# cobrir qualquer tipo além de aluguel. Adicionar 'gas' (ou outro) no
# futuro é só: (1) nova migration ampliando o CHECK constraint de
# charges.tipo, (2) uma entrada nova aqui — a lógica de mensagem em si não
# muda.
ROTULOS_CONTA: dict[str, str] = {
    "agua": "água",
}


def _rotulo_conta(tipo: str) -> str:
    return ROTULOS_CONTA.get(tipo, "conta")


def _calcular_encargos(
    valor_esperado: float,
    dias_atraso: int,
    multa_moratoria_percentual: float | None,
    juros_moratorio_mensal: float,
) -> tuple[float, float, float]:
    """Multa é flat (não proporcional aos dias); juros é prorateado por dia
    num mês de 30 dias — convenção assumida, não especificada na doc.
    multa_moratoria_percentual é fração (0.02 = 2%), não percentual inteiro
    — ver nota de unidade em Migration 011, ainda não validada contra dado
    real."""
    percentual_multa = multa_moratoria_percentual or 0.0
    valor_multa = valor_esperado * percentual_multa
    valor_juros = valor_esperado * juros_moratorio_mensal * (dias_atraso / 30)
    valor_total = valor_esperado + valor_multa + valor_juros
    return round(valor_multa, 2), round(valor_juros, 2), round(valor_total, 2)


def _montar_mensagem_aluguel(
    charge: ChargeAtiva, dados: DadosCobrancaContrato, estagio: EstagioCobranca, dias_atraso: int
) -> str:
    """Texto literal validado com o cliente — não reescrever o tom aqui."""
    nome = dados.inquilino_nome
    imovel = dados.imovel_identificacao
    data_venc_fmt = charge.data_vencimento.strftime("%d/%m/%Y")

    if estagio == "d-5":
        return (
            f"Bom dia, {nome}! \n\n"
            f"Passando para lembrar que o vencimento do aluguel do {imovel} é "
            f"dia {data_venc_fmt}.\n\n"
            f"Qualquer dúvida, é só chamar por aqui."
        )

    if estagio == "d0":
        return (
            f"Bom dia, {nome}!\n\n"
            f"Passando para lembrar que hoje é o vencimento do aluguel do {imovel}.\n\n"
            f"Assim que fizer o pagamento, envie o comprovante por aqui."
        )

    valor_multa, valor_juros, valor_total = _calcular_encargos(
        charge.valor_esperado, dias_atraso, dados.multa_moratoria_percentual, dados.juros_moratorio_mensal
    )

    if estagio == "d+5":
        return (
            f"Bom dia, {nome}.\n\n"
            f"Não localizamos o pagamento do aluguel referente ao vencimento de "
            f"{data_venc_fmt}. Poderia enviar o comprovante, por favor?\n\n"
            f"Conforme o contrato, o valor já está sujeito a multa e juros por atraso:\n\n"
            f"Aluguel: R$ {charge.valor_esperado:.2f}\n"
            f"Multa contratual: R$ {valor_multa:.2f}\n"
            f"Juros ({dias_atraso} dias): R$ {valor_juros:.2f}\n\n"
            f"Valor total para pagamento: R$ {valor_total:.2f}\n\n"
            f"Assim que fizer o pagamento, envie o comprovante por aqui."
        )

    if estagio == "d+10":
        return (
            f"{nome}, bom dia.\n\n"
            f"O aluguel referente ao vencimento de {data_venc_fmt} segue em aberto há "
            f"{dias_atraso} dias.\n\n"
            f"Valor atualizado com multa e juros:\n\n"
            f"Aluguel: R$ {charge.valor_esperado:.2f}\n"
            f"Multa contratual: R$ {valor_multa:.2f}\n"
            f"Juros ({dias_atraso} dias): R$ {valor_juros:.2f}\n\n"
            f"Valor total para pagamento: R$ {valor_total:.2f}\n\n"
            f"Pedimos que regularize o quanto antes. Caso o pagamento não seja identificado "
            f"nos próximos dias, o caso será encaminhado para a gestão do imóvel."
        )

    # d+15
    return (
        f"Bom dia, {nome}.\n\n"
        f"O aluguel referente ao vencimento de {data_venc_fmt} está em aberto há "
        f"{dias_atraso} dias, sem que tenhamos recebido comprovante de pagamento.\n\n"
        f"Valor atualizado com multa e juros:\n\n"
        f"Aluguel: R$ {charge.valor_esperado:.2f}\n"
        f"Multa contratual: R$ {valor_multa:.2f}\n"
        f"Juros ({dias_atraso} dias): R$ {valor_juros:.2f}\n\n"
        f"Valor total para pagamento: R$ {valor_total:.2f}\n\n"
        f"Pedimos a regularização o quanto antes. A partir de agora, o caso também será "
        f"acompanhado diretamente pela gestão do imóvel."
    )


def _montar_mensagem_conta(
    charge: ChargeAtiva, dados: DadosCobrancaContrato, estagio: EstagioCobranca, dias_atraso: int
) -> str:
    """Texto novo, não validado com o cliente (a doc original só cobria
    aluguel) — mais simples e direto de propósito: uma linha de valor em vez
    da quebra multa/juros/total separada, sem "conforme o contrato" nem
    explicações longas. Ainda formal (trata por nome, sem gírias), só mais
    enxuto. Generaliza pra qualquer tipo de conta via ROTULOS_CONTA."""
    nome = dados.inquilino_nome
    rotulo = _rotulo_conta(charge.tipo)
    data_venc_fmt = charge.data_vencimento.strftime("%d/%m/%Y")

    if estagio == "d-5":
        return (
            f"Olá, {nome}. Sua conta de {rotulo} vence dia {data_venc_fmt}. "
            f"Qualquer dúvida, estamos à disposição."
        )

    if estagio == "d0":
        return (
            f"Olá, {nome}. Hoje é o vencimento da sua conta de {rotulo}. "
            f"Assim que pagar, envie o comprovante por aqui."
        )

    valor_multa, valor_juros, valor_total = _calcular_encargos(
        charge.valor_esperado, dias_atraso, dados.multa_moratoria_percentual, dados.juros_moratorio_mensal
    )

    if estagio == "d+5":
        return (
            f"Olá, {nome}. Não identificamos o pagamento da conta de {rotulo} "
            f"(vencimento {data_venc_fmt}). Valor atualizado com encargos: R$ {valor_total:.2f}. "
            f"Pode enviar o comprovante assim que possível?"
        )

    if estagio == "d+10":
        return (
            f"Olá, {nome}. A conta de {rotulo} (vencimento {data_venc_fmt}) segue em "
            f"aberto há {dias_atraso} dias. Valor atualizado: R$ {valor_total:.2f}. "
            f"Pedimos a regularização o quanto antes."
        )

    # d+15
    return (
        f"Olá, {nome}. A conta de {rotulo} (vencimento {data_venc_fmt}) está em aberto há "
        f"{dias_atraso} dias, sem comprovante recebido. Valor atualizado: R$ {valor_total:.2f}. "
        f"A partir de agora, a gestão do imóvel também acompanha este caso."
    )


def montar_mensagem(
    charge: ChargeAtiva,
    dados: DadosCobrancaContrato,
    estagio: EstagioCobranca,
    dias_atraso: int,
) -> str:
    if charge.tipo == "aluguel":
        return _montar_mensagem_aluguel(charge, dados, estagio, dias_atraso)
    return _montar_mensagem_conta(charge, dados, estagio, dias_atraso)