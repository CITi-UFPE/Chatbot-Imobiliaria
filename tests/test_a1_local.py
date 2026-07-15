"""Teste manual do A1 — Atendimento ao Inquilino.

Mocka SOMENTE a camada que fala com o Supabase (obter_client_agente) e a
pré-checagem de escalonamento do A5 (avaliar_escalonamento) — a chamada à
API da Anthropic dentro de atendimento.py (client = anthropic.Anthropic())
roda de verdade, sem nenhum mock. Ou seja: você testa o comportamento real
do modelo (será que ele chama a tool? será que cita a cláusula certa?)
contra um "banco de dados" fake, sem precisar de Supabase configurado.

Como rodar:
    export ANTHROPIC_API_KEY=sk-ant-...
    pip install anthropic pydantic
    python testar_a1_manual.py

Ajuste MENSAGEM_TESTE e os dicts de dados mockados abaixo pra simular
cenários diferentes (PF vs PJ, com/sem histórico, com/sem cláusula, etc.).
"""

import logging
import os
import sys
from dotenv import load_dotenv
from pathlib import Path
from unittest.mock import MagicMock, patch

load_dotenv()  # lê .env na raiz do projeto, se existir, pra pegar ANTHROPIC_API_KEY

# Este arquivo vive em tests/, um nível abaixo da raiz do projeto (onde fica
# app/). Rodando com `python3 tests/testar_a1_manual.py`, o Python só coloca
# tests/ no sys.path, não a raiz — então `from app...` falha com
# ModuleNotFoundError. A linha abaixo resolve isso calculando a raiz a partir
# da posição real deste arquivo (Path(__file__).parent = tests/, .parent de
# novo = raiz), então funciona não importa de onde o comando é chamado.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)

# --- Cenário a simular -----------------------------------------------------

CONTRACT_ID_FAKE = "11111111-1111-1111-1111-111111111111"

MENSAGEM_TESTE = "Oi, qual o valor do meu aluguel e quando vence?"

# O que a RPC buscar_dados_inquilino "devolveria" do banco pra este contrato.
# Precisa bater com o schema de app.agents.a1_atendimento.schemas.DadosInquilino
# (nomes de campo espelham contracts/contract_clauses reais, não invenção).
DADOS_INQUILINO_MOCK = {
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
    "clausulas": [
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
    ],
}

# O que a RPC consultar_historico "devolveria" — precisa bater com
# app.agents.a1_atendimento.schemas.RegistroHistorico.
HISTORICO_MOCK = [
    {
        "id": "hist-001",
        "tipo": "manutencao",
        "status": "resolvido",
        "resumo": "Chamado de manutenção (hidraulica, urgência media): vazamento no banheiro.",
        "criado_em": "2026-06-10T14:00:00Z",
    }
]


def _fake_rpc_execute(nome_funcao: str, parametros: dict) -> MagicMock:
    """Simula client.rpc(nome, params).execute() devolvendo os mocks acima
    conforme qual RPC foi chamada — o resto do fluxo (validação Pydantic,
    filtro de campos, etc.) roda igual ao código real.

    Importante: no supabase-py real, client.rpc(...) devolve um "query
    builder" (ainda sem dado nenhum), e só chamar .execute() NELE devolve o
    objeto com .data preenchido. São duas camadas, não uma — por isso o mock
    abaixo devolve um builder_mock cujo .execute() é configurado pra
    devolver o resposta_mock com .data pronto. Se .execute() não for
    configurado explicitamente, MagicMock cria um mock novo e vazio sozinho
    ao ser chamado, e o .data dele também vira um mock vazio — foi
    exatamente esse o bug que gerou o ValidationError anterior.
    """
    resposta_mock = MagicMock()
    if nome_funcao == "buscar_dados_inquilino":
        resposta_mock.data = DADOS_INQUILINO_MOCK
    elif nome_funcao == "consultar_historico":
        resposta_mock.data = HISTORICO_MOCK
    else:
        raise ValueError(f"RPC não mockada neste teste: {nome_funcao}")

    builder_mock = MagicMock()
    builder_mock.execute.return_value = resposta_mock
    return builder_mock


def _client_agente_fake(contract_id: str):
    """Substitui obter_client_agente(contract_id) — devolve um client fake
    cujo .rpc(nome, params).execute() usa o dispatcher acima."""
    client_fake = MagicMock()
    client_fake.rpc.side_effect = lambda nome, params: _fake_rpc_execute(nome, params)
    return client_fake


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Defina ANTHROPIC_API_KEY antes de rodar este teste.")

    # Import feito DEPOIS de garantir a env var, e dentro do escopo dos
    # patches — importa o módulo real, só troca as duas dependências
    # externas (Supabase e a pré-checagem do A5).
    with patch(
        "app.agents.a1_atendimento.atendimento.obter_client_agente",
        side_effect=_client_agente_fake,
    ), patch(
        "app.agents.a1_atendimento.atendimento.avaliar_escalonamento",
        return_value=None,  # simula "não precisa escalar" pra este teste
    ):
        from app.agents.a1_atendimento import responder_inquilino

        resposta = responder_inquilino(
            contract_id=CONTRACT_ID_FAKE,
            mensagem_atual=MENSAGEM_TESTE,
        )

    print("\n--- MENSAGEM DO INQUILINO ---")
    print(MENSAGEM_TESTE)
    print("\n--- RESPOSTA DO A1 (API real, dados mockados) ---")
    print(resposta)


if __name__ == "__main__":
    main()