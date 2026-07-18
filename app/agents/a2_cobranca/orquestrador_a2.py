"""Orquestrador do Agente 2 — Cobrança e Inadimplência.

Ponto de entrada ÚNICO que o orquestrador geral deve chamar para qualquer
interação (reativa a mensagem/webhook) que pertença ao A2. O orquestrador
geral não precisa conhecer os detalhes internos do A2 (que hoje tem 3
fluxos bem diferentes: comprovante por visão, confirmação por botão,
divergência por botão) — só precisa montar um `EntradaA2` com o
`tipo_entrada` certo e chamar `processar_entrada_a2`.

NÃO incluído aqui: executar_cobranca_diaria (o cron D-5/D0/D+5/D+10/D+15).
Aquele fluxo não nasce de uma mensagem — é disparado direto pelo Railway
Cron via app/jobs/cron_cobranca_diaria.py, fora do ciclo de
mensagem/webhook. Não faz sentido ele passar por um orquestrador pensado
pra decidir "que fazer com ESTA mensagem que chegou agora" quando não há
mensagem nenhuma nesse caminho.

Uso esperado, do lado do orquestrador geral:

    from app.agents.a2_cobranca import EntradaA2, TipoEntradaA2, processar_entrada_a2

    # ... orquestrador geral já identificou que a mensagem é uma foto/PDF
    # numa conversa de um contrato conhecido:
    processar_entrada_a2(EntradaA2(
        tipo_entrada=TipoEntradaA2.COMPROVANTE_RECEBIDO,
        contract_id=contract_id,
        imagem_base64=imagem_base64,
        media_type=media_type,
    ))

    # ... ou o orquestrador geral recebeu o callback de um botão clicado
    # pela Fernanda (via webhook — parsing do callback ainda não existe,
    # ver comprovante.py):
    processar_entrada_a2(EntradaA2(
        tipo_entrada=TipoEntradaA2.CONFIRMACAO_FERNANDA,
        contract_id=contract_id,
        charge_id=charge_id,
    ))

Como o orquestrador geral sabe que uma mensagem é "assunto do A2"? Isso é
decisão de roteamento de fora deste módulo (provavelmente: presença de
mídia de imagem/PDF no payload do WhatsApp -> COMPROVANTE_RECEBIDO; payload
de interactive button reply -> CONFIRMACAO_FERNANDA/DIVERGENCIA_FERNANDA,
dependendo de qual botão veio) — não é este módulo que classifica a
mensagem, só que decide o que fazer uma vez já classificada.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from app.agents.a2_cobranca.comprovante import (
    confirmar_pagamento,
    confirmar_pagamento_combinado,
    marcar_apenas_uma_paga,
    marcar_valor_divergente,
    processar_comprovante_recebido,
)


class TipoEntradaA2(str, Enum):
    """Qual das entradas reativas do A2 o orquestrador geral quer acionar."""

    # Inquilino mandou foto/PDF de comprovante numa conversa do WhatsApp.
    # Exige: contract_id, imagem_base64, media_type.
    COMPROVANTE_RECEBIDO = "comprovante_recebido"

    # Fernanda apertou "Confirmar" na DM de comprovante (ou "Cobre os dois",
    # no caso de pagamento combinado — tratado da mesma forma: charge_id é
    # sempre UMA charge por chamada; pagamento combinado exige uma chamada
    # por charge envolvida, do lado de quem recebe o callback do botão).
    # Exige: contract_id, charge_id.
    CONFIRMACAO_FERNANDA = "confirmacao_fernanda"

    # Fernanda apertou "Valor diverge".
    # Exige: contract_id, charge_id.
    DIVERGENCIA_FERNANDA = "divergencia_fernanda"

    # Fernanda apertou "Cobre os dois" na DM de pagamento combinado (ver
    # notificar_fernanda_pagamento_combinado). Exige: contract_id, charge_ids
    # (lista com todas as charges envolvidas no pagamento combinado).
    PAGAMENTO_COMBINADO_CONFIRMADO = "pagamento_combinado_confirmado"

    # Fernanda apertou "Só uma delas" na mesma DM — só UMA das charges do
    # pagamento combinado foi de fato paga. Exige: contract_id,
    # charge_id_paga, charge_ids_restantes. PONTO EM ABERTO: qual é a
    # charge_id_paga não vem do clique do botão sozinho — precisa de uma
    # interação adicional ainda não desenhada (ver marcar_apenas_uma_paga
    # em comprovante.py).
    PAGAMENTO_COMBINADO_PARCIAL = "pagamento_combinado_parcial"


class EntradaA2(BaseModel):
    """Payload que o orquestrador geral monta antes de chamar
    processar_entrada_a2. Os campos obrigatórios variam conforme
    tipo_entrada — validados em tempo de construção (model_validator
    abaixo), pra falhar cedo com uma mensagem clara em vez de um erro
    genérico de atributo None lá dentro do A2."""

    model_config = ConfigDict(extra="forbid")

    tipo_entrada: TipoEntradaA2

    # Sempre obrigatório, para qualquer tipo_entrada — é o que garante que
    # qualquer ação do A2 fica isolada ao contrato certo (mesma doutrina de
    # obter_client_agente em todo o resto do projeto).
    contract_id: str

    # Obrigatórios só quando tipo_entrada == COMPROVANTE_RECEBIDO.
    imagem_base64: Optional[str] = None
    media_type: Optional[str] = None

    # Obrigatório só quando tipo_entrada in (CONFIRMACAO_FERNANDA, DIVERGENCIA_FERNANDA).
    charge_id: Optional[str] = None

    # Obrigatório só quando tipo_entrada == PAGAMENTO_COMBINADO_CONFIRMADO.
    charge_ids: Optional[list[str]] = None

    # Obrigatórios só quando tipo_entrada == PAGAMENTO_COMBINADO_PARCIAL.
    charge_id_paga: Optional[str] = None
    charge_ids_restantes: Optional[list[str]] = None

    @model_validator(mode="after")
    def _valida_campos_por_tipo(self) -> "EntradaA2":
        if self.tipo_entrada == TipoEntradaA2.COMPROVANTE_RECEBIDO:
            if not self.imagem_base64 or not self.media_type:
                raise ValueError(
                    "tipo_entrada=comprovante_recebido exige imagem_base64 e media_type."
                )
        elif self.tipo_entrada in (TipoEntradaA2.CONFIRMACAO_FERNANDA, TipoEntradaA2.DIVERGENCIA_FERNANDA):
            if not self.charge_id:
                raise ValueError(
                    f"tipo_entrada={self.tipo_entrada.value} exige charge_id."
                )
        elif self.tipo_entrada == TipoEntradaA2.PAGAMENTO_COMBINADO_CONFIRMADO:
            if not self.charge_ids:
                raise ValueError(
                    "tipo_entrada=pagamento_combinado_confirmado exige charge_ids (lista)."
                )
        elif self.tipo_entrada == TipoEntradaA2.PAGAMENTO_COMBINADO_PARCIAL:
            if not self.charge_id_paga or not self.charge_ids_restantes:
                raise ValueError(
                    "tipo_entrada=pagamento_combinado_parcial exige charge_id_paga e "
                    "charge_ids_restantes."
                )
        return self


def processar_entrada_a2(entrada: EntradaA2) -> None:
    """Único ponto de entrada do A2 para o orquestrador geral chamar.

    Decide, a partir de entrada.tipo_entrada, qual das 3 funções internas do
    A2 chamar e com quais argumentos — o chamador não precisa importar nem
    conhecer processar_comprovante_recebido / confirmar_pagamento /
    marcar_valor_divergente diretamente, só este módulo.
    """
    if entrada.tipo_entrada == TipoEntradaA2.COMPROVANTE_RECEBIDO:
        processar_comprovante_recebido(
            entrada.contract_id, entrada.imagem_base64, entrada.media_type
        )
        return

    if entrada.tipo_entrada == TipoEntradaA2.CONFIRMACAO_FERNANDA:
        confirmar_pagamento(entrada.contract_id, entrada.charge_id)
        return

    if entrada.tipo_entrada == TipoEntradaA2.DIVERGENCIA_FERNANDA:
        marcar_valor_divergente(entrada.contract_id, entrada.charge_id)
        return

    if entrada.tipo_entrada == TipoEntradaA2.PAGAMENTO_COMBINADO_CONFIRMADO:
        confirmar_pagamento_combinado(entrada.contract_id, entrada.charge_ids)
        return

    if entrada.tipo_entrada == TipoEntradaA2.PAGAMENTO_COMBINADO_PARCIAL:
        marcar_apenas_uma_paga(
            entrada.contract_id, entrada.charge_id_paga, entrada.charge_ids_restantes
        )
        return

    # Inalcançável se EntradaA2 for sempre construída via Pydantic (o Enum
    # já restringe os valores possíveis) — mantido por defesa em
    # profundidade, caso tipo_entrada chegue de alguma forma não validada.
    raise ValueError(f"tipo_entrada desconhecido: {entrada.tipo_entrada}")