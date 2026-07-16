"""Teste manual do A1 — Atendimento ao Inquilino, com múltiplos cenários.

Mocka SOMENTE a camada que fala com o Supabase (obter_client_agente) e a
pré-checagem de escalonamento do A5 (avaliar_escalonamento) — a chamada à
API da Anthropic dentro de atendimento.py (client = anthropic.Anthropic())
roda de verdade, sem nenhum mock. Ou seja: você testa o comportamento real
do modelo contra um "banco de dados" fake, sem precisar de Supabase
configurado.

Como rodar:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 tests/testar_a1_manual.py                # roda todos os cenários
    python3 tests/testar_a1_manual.py pf_simples      # roda só um cenário
    python3 tests/testar_a1_manual.py --listar        # lista os nomes disponíveis

Cada cenário é um dataclass `Cenario` (ver lista CENARIOS no fim do arquivo)
com sua própria mensagem, dados de contrato, histórico e (opcionalmente) uma
decisão de escalonamento pré-fabricada. Pra criar um cenário novo, basta
adicionar outro `Cenario(...)` na lista — não precisa duplicar a lógica de
mock, só os dados.
"""

import logging
import os
import sys
from dotenv import load_dotenv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

load_dotenv()  # lê .env na raiz do projeto, pra pegar ANTHROPIC_API_KEY

# Este arquivo vive em tests/, um nível abaixo da raiz do projeto (onde fica
# app/). Rodando com `python3 tests/testar_a1_manual.py`, o Python só coloca
# tests/ no sys.path, não a raiz — então `from app...` falha com
# ModuleNotFoundError. A linha abaixo resolve isso calculando a raiz a partir
# da posição real deste arquivo, então funciona não importa de onde o
# comando é chamado.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)

CONTRACT_ID_FAKE = "11111111-1111-1111-1111-111111111111"


# --- Estrutura de um cenário -------------------------------------------------


@dataclass
class Cenario:
    nome: str
    descricao: str
    mensagem: str
    dados_inquilino: dict
    historico: list[dict] = field(default_factory=list)
    # Se preenchido, simula avaliar_escalonamento JÁ decidindo escalar --
    # nesse caso o A1 nem chega a entrar no loop de tool-use, só chama
    # executar_escalonamento e devolve a resposta educada. Formato:
    # {"motivo": ..., "descricao": ..., "resposta_para_inquilino": ...}
    escalonamento_esperado: Optional[dict] = None


# --- Dados-base reaproveitados entre cenários -------------------------------

CLAUSULAS_PADRAO = [
    {
        "numero_clausula": "4",
        "titulo_clausula": "Vencimento e mora",
        "texto_clausula": "O aluguel vence todo dia 5 de cada mês, incidindo em caso de "
        "atraso multa moratória de 2% sobre o valor devido, acrescida de juros de 1% ao mês.",
        "categoria": "multa",
    },
    {
        "numero_clausula": "7",
        "titulo_clausula": "Reajuste",
        "texto_clausula": "O valor do aluguel será reajustado anualmente pelo IGP-M, "
        "tomando-se por base a data de aniversário do contrato.",
        "categoria": "financeiro",
    },
]


def _contrato_base(**overrides) -> dict:
    """Monta um DadosInquilino válido com defaults razoáveis, sobrescrevendo
    só o que cada cenário precisar mudar — evita repetir os ~20 campos
    obrigatórios em cada cenário."""
    base = {
        "contract_id": CONTRACT_ID_FAKE,
        "tipo_locatario": "pf",
        "inquilino_nome": "João Pereira",
        "responsavel_contato_nome": None,
        "valor_aluguel": 2200.0,
        "dia_vencimento": 5,
        "vencimento_mes_referencia": "atual",
        "data_inicio": "2025-03-01",
        "data_termino": "2027-03-01",
        "indice_reajuste": "igpm",
        "data_aniversario_reajuste": "2026-03-01",
        "garantia_tipo": "fiador",
        "garantia_valor": None,
        "fiador_nome": "Maria Pereira",
        "multa_infracao_tipo": "meses_aluguel",
        "multa_infracao_valor": 3,
        "multa_moratoria_percentual": 2.0,
        "juros_moratorio_mensal": 0.01,
        "aviso_previo_dias": 30,
        "aviso_previo_a_partir_mes": 12,
        "imovel_identificacao": "Apto 305, Ed. Girassol",
        "imovel_endereco": "Rua das Flores, 123 - Recife/PE",
        "clausulas": CLAUSULAS_PADRAO,
    }
    base.update(overrides)
    return base


# --- Os 5 cenários -----------------------------------------------------------

CENARIOS: list[Cenario] = [
    Cenario(
        nome="pf_simples",
        descricao="PF perguntando valor e vencimento do aluguel — caminho feliz básico.",
        mensagem="Oi, qual o valor do meu aluguel e quando vence?",
        dados_inquilino=_contrato_base(),
    ),
    Cenario(
        nome="pj_formal",
        descricao=(
            "PJ perguntando reajuste — checa se o tom vira formal (razão social) e se "
            "responsavel_contato_nome é usado sem virar 'autorização' inexistente."
        ),
        mensagem="Qual o índice de reajuste do nosso contrato?",
        dados_inquilino=_contrato_base(
            tipo_locatario="pj",
            inquilino_nome="Comércio de Roupas Estrela Ltda.",
            responsavel_contato_nome="Frederico Watanabe",
            garantia_tipo="caucao",
            garantia_valor=6600.0,
            fiador_nome=None,
        ),
    ),
    Cenario(
        nome="historico_manutencao",
        descricao=(
            "Inquilino pergunta sobre chamado de manutenção anterior — checa se o A1 "
            "chama consultar_historico e cita o registro mockado."
        ),
        mensagem="Já abri algum chamado de manutenção? Como ficou aquele vazamento?",
        dados_inquilino=_contrato_base(),
        historico=[
            {
                "id": "hist-001",
                "tipo": "manutencao",
                "status": "resolvido",
                "resumo": "Chamado de manutenção (hidraulica, urgência media): vazamento no banheiro.",
                "criado_em": "2026-06-10T14:00:00Z",
            }
        ],
    ),
    Cenario(
        nome="escalonamento_desconto",
        descricao=(
            "Pedido de desconto — o A5 (mockado) já decide escalar ANTES do A1 tentar "
            "responder o conteúdo. Checa que a resposta final é a do A5, não uma "
            "tentativa do A1 de negociar."
        ),
        mensagem="Vocês conseguem me dar um desconto de 20% no aluguel esse mês?",
        dados_inquilino=_contrato_base(),
        escalonamento_esperado={
            "motivo": "desconto_renegociacao",
            "descricao": "Inquilino pediu desconto de 20% no aluguel do mês.",
            "resposta_para_inquilino": (
                "Entendi seu pedido! Vou encaminhar para a equipe avaliar e você recebe "
                "um retorno em breve."
            ),
        },
    ),
    Cenario(
        nome="clausula_ausente",
        descricao=(
            "Pergunta sobre algo que não tem cláusula estruturada no mock (sublocação) — "
            "checa que o A1 avisa que vai verificar, em vez de inventar uma resposta. "
            "Relacionado ao TODO de 'sem_clausula' documentado em atendimento.py: hoje "
            "isso NÃO abre uma escalação formal sozinho, só o texto da resposta muda."
        ),
        mensagem="Posso sublocar o imóvel pro meu primo por uns meses?",
        dados_inquilino=_contrato_base(clausulas=[CLAUSULAS_PADRAO[0]]),  # sem cláusula de sublocação
    ),
]


# --- Motor de mock (igual pros 5 cenários, só os dados mudam) ---------------


def _fake_rpc_execute(nome_funcao: str, parametros: dict, cenario: Cenario) -> MagicMock:
    """Simula client.rpc(nome, params).execute(). Duas camadas, igual ao
    supabase-py real: client.rpc(...) devolve um builder ainda sem dado, e só
    .execute() nele devolve o objeto com .data preenchido — se .execute()
    não for configurado explicitamente, MagicMock inventa um mock vazio
    sozinho, e foi esse o bug corrigido na rodada anterior de testes."""
    resposta_mock = MagicMock()
    if nome_funcao == "buscar_dados_inquilino":
        resposta_mock.data = cenario.dados_inquilino
    elif nome_funcao == "consultar_historico":
        resposta_mock.data = cenario.historico
    else:
        raise ValueError(f"RPC não mockada neste teste: {nome_funcao}")

    builder_mock = MagicMock()
    builder_mock.execute.return_value = resposta_mock
    return builder_mock


def _client_agente_fake(contract_id: str, cenario: Cenario):
    client_fake = MagicMock()
    client_fake.rpc.side_effect = lambda nome, params: _fake_rpc_execute(nome, params, cenario)
    return client_fake


def _rodar_cenario(cenario: Cenario) -> None:
    print(f"\n{'=' * 70}")
    print(f"CENÁRIO: {cenario.nome}")
    print(f"{cenario.descricao}")
    print(f"{'=' * 70}")

    avaliacao_mock = None
    if cenario.escalonamento_esperado is not None:
        # Import tardio (só quando necessário) pra não exigir o pacote a5
        # em cenários que não mexem com escalonamento.
        from app.agents.a5_escalonamento import AvaliacaoEscalonamento

        avaliacao_mock = AvaliacaoEscalonamento(**cenario.escalonamento_esperado)

    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        side_effect=lambda contract_id: _client_agente_fake(contract_id, cenario),
    ), patch(
        "app.agents.a1_atendimento.atendimento.avaliar_escalonamento",
        return_value=avaliacao_mock,
    ), patch(
        "app.agents.a1_atendimento.atendimento.executar_escalonamento",
        return_value="ESC-2026-00001",  # protocolo fake, evita bater no Supabase de verdade
    ) as mock_executar_escalonamento:
        from app.agents.a1_atendimento import responder_inquilino

        resposta = responder_inquilino(
            contract_id=CONTRACT_ID_FAKE,
            mensagem_atual=cenario.mensagem,
        )

        if cenario.escalonamento_esperado is not None:
            escalou = mock_executar_escalonamento.called
            print(f"\n[checagem] executar_escalonamento foi chamado: {escalou}")

    print(f"\n--- MENSAGEM DO INQUILINO ---\n{cenario.mensagem}")
    print(f"\n--- RESPOSTA DO A1 ---\n{resposta}")


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Defina ANTHROPIC_API_KEY antes de rodar este teste.")

    if "--listar" in sys.argv:
        for c in CENARIOS:
            print(f"{c.nome}: {c.descricao}")
        return

    nomes_pedidos = [a for a in sys.argv[1:] if not a.startswith("--")]
    cenarios_a_rodar = (
        [c for c in CENARIOS if c.nome in nomes_pedidos] if nomes_pedidos else CENARIOS
    )

    if nomes_pedidos and not cenarios_a_rodar:
        nomes_validos = ", ".join(c.nome for c in CENARIOS)
        raise SystemExit(f"Nenhum cenário encontrado para {nomes_pedidos}. Válidos: {nomes_validos}")

    for cenario in cenarios_a_rodar:
        _rodar_cenario(cenario)


if __name__ == "__main__":
    main()