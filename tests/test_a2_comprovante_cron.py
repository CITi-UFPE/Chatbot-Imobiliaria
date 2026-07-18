"""Teste manual do A2 — Cobrança e Inadimplência, com múltiplos cenários.

Segue o mesmo espírito de tests/testar_a1_manual.py: mocka SOMENTE a camada
que fala com o Supabase (obter_client_agente / obter_client_cron_batch) e,
quando aplicável, a notificação de saída (WhatsApp) e o A5
(executar_escalonamento) — tudo o que é lógica de negócio pura do A2 roda
de verdade contra esses mocks.

O A2 tem DOIS fluxos bem diferentes, e só um deles chama a API da Claude:

  1. CRON DE COBRANÇA (D-5/D0/D+5/D+10/D+15) — app.agents.a2_cobranca.cobranca
     Não chama a API da Claude em nenhum momento: as mensagens são
     montadas por template puro (mensagens.py), sem LLM no meio. Os
     cenários de cron abaixo, portanto, são 100% determinísticos e não
     precisam de ANTHROPIC_API_KEY — testam a lógica de estágio (D-X),
     a pausa por status (STATUS_PAUSADOS), o não-reenvio de mensagem já
     mandada, o recálculo de dias_atraso a partir de `hoje` (em vez de
     confiar no que veio salvo no banco) e o escalonamento automático no
     D+15.

  2. LEITURA DE COMPROVANTE POR VISÃO — app.agents.a2_cobranca.comprovante
     Este SIM chama a API da Claude de verdade (extrair_dados_comprovante,
     com tool_choice forçado) — igual ao padrão do A1, a chamada real à
     Anthropic não é mockada, só a camada Supabase e o envio de WhatsApp.
     Como não temos comprovantes reais à mão, os cenários abaixo geram
     imagens SINTÉTICAS (via Pillow) com texto de recibo desenhado nelas —
     valor, data, favorecido — pra exercitar a extração por visão de
     verdade, incluindo o caso combinado (Caso B.b), o caso ambíguo
     resolvido por valor (Caso B.a) e o caso de imagem ilegível/errada
     (ex.: inquilino manda foto de outra coisa por engano).

IMPORTANTE — nomes de módulo assumidos: os arquivos que você mandou não
tinham o nome do arquivo no cabeçalho, só docstrings internas se referindo
a "cobranca.py" e "comprovante.py". Assumi:
    app.agents.a2_cobranca.cobranca      (executar_cobranca_diaria, _processar_charge)
    app.agents.a2_cobranca.comprovante   (processar_comprovante_recebido, extrair_dados_comprovante, ...)
    app.agents.a2_cobranca.notificacao
    app.agents.a2_cobranca.schemas
Se algum desses nomes for diferente no seu projeto, ajuste os imports no
topo da seção correspondente (marcados com # AJUSTE SE NECESSÁRIO).

DEPENDÊNCIA da correção anterior: os cenários de cron chamam
`executar_cobranca_diaria(hoje=HOJE)` usando o parâmetro opcional `hoje`
que adicionamos pra travar a data — sem ele, os offsets (-5, 0, +5, +10,
+15) só bateriam se você rodasse o teste exatamente no dia certo.

Como rodar:
    export ANTHROPIC_API_KEY=sk-ant-...
    pip install pillow                      # só necessário p/ gerar as imagens sintéticas
    python3 tests/testar_a2_manual.py                     # roda todos os cenários (cron + comprovante)
    python3 tests/testar_a2_manual.py --listar             # lista os nomes disponíveis
    python3 tests/testar_a2_manual.py --so-cron             # só os cenários de cron (sem API)
    python3 tests/testar_a2_manual.py --so-comprovante      # só os cenários de comprovante (com API)
    python3 tests/testar_a2_manual.py aluguel_d15_escalonamento comprovante_sem_match  # cenários específicos

Não há assert automático "passou/falhou" — cada cenário imprime o que
esperávamos e o que de fato aconteceu (mensagens enviadas, updates de
status, escalonamentos, notificações), pra você conferir manualmente,
principalmente a parte de extração por visão, que depende do modelo.
"""

import base64
import io
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv

load_dotenv()

# Mesmo ajuste de sys.path do teste do A1: este arquivo vive em tests/, um
# nível abaixo da raiz do projeto — sem isso, `from app...` falha com
# ModuleNotFoundError quando rodado como `python3 tests/testar_a2_manual.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)

HOJE = date(2026, 7, 17)  # data travada — ver dependência da correção do parâmetro `hoje`

CONTRACT_ID_ALUGUEL = "22222222-2222-2222-2222-222222222222"
CONTRACT_ID_AGUA = "33333333-3333-3333-3333-333333333333"
CONTRACT_ID_ESCALONAMENTO = "44444444-4444-4444-4444-444444444444"
CONTRACT_ID_PAUSADO = "55555555-5555-5555-5555-555555555555"
CONTRACT_ID_DUPLICADO = "66666666-6666-6666-6666-666666666666"
CONTRACT_ID_LOTE_ERRO_OK = "77777777-7777-7777-7777-777777777777"

DADOS_CONTRATO_PADRAO = {
    "telefone_whatsapp": "+5581999990000",
    "inquilino_nome": "João Pereira",
    "imovel_identificacao": "Apto 305, Ed. Girassol",
    "multa_moratoria_percentual": 0.02,
    "juros_moratorio_mensal": 0.01,
}


# =============================================================================
# PARTE 1 — CRON DE COBRANÇA (sem chamada à API da Claude — puro template)
# =============================================================================


@dataclass
class CenarioCron:
    nome: str
    descricao: str
    charges_raw: list  # o lote inteiro devolvido por cron_listar_charges_ativas
    dados_por_contrato: dict  # contract_id -> DadosCobrancaContrato (dict)
    esperado: str  # texto livre descrevendo o que checar no output


def _charge_raw(
    *,
    contract_id: str,
    charge_id: str,
    tipo: str,
    valor_esperado: float,
    dias_offset: int,
    status: str,
    mensagem_estagio: Optional[str],
    dias_atraso_salvo_errado: int = 999,
) -> dict:
    """Monta uma linha crua de charges_ativas. `dias_offset` é relativo a
    HOJE (negativo = vencimento no futuro). `dias_atraso_salvo_errado` é
    proposital: simula o campo `dias_atraso` vindo "desatualizado" do banco
    — a lógica de _processar_charge NUNCA deveria confiar nesse valor
    salvo, só no recálculo feito a partir de `hoje` (ver cobranca.py). Se o
    teste passar mesmo com esse valor errado, confirma que o recálculo está
    correto."""
    vencimento = HOJE - timedelta(days=dias_offset)
    return {
        "contract_id": contract_id,
        "charge_id": charge_id,
        "tipo": tipo,
        "mes_referencia": vencimento.replace(day=1).isoformat(),
        "valor_esperado": valor_esperado,
        "data_vencimento": vencimento.isoformat(),
        "data_pagamento": None,
        "dias_atraso": dias_atraso_salvo_errado,
        "status": status,
        "mensagem_estagio": mensagem_estagio,
    }


CENARIOS_CRON: list[CenarioCron] = [
    CenarioCron(
        nome="aluguel_d_menos_5",
        descricao="Aluguel vence em 5 dias — deve disparar o lembrete D-5, sem mexer no status.",
        charges_raw=[
            _charge_raw(
                contract_id=CONTRACT_ID_ALUGUEL,
                charge_id="charge-d5-antes",
                tipo="aluguel",
                valor_esperado=2200.0,
                dias_offset=-5,  # vence daqui a 5 dias
                status="pendente",
                mensagem_estagio=None,
            )
        ],
        dados_por_contrato={CONTRACT_ID_ALUGUEL: DADOS_CONTRATO_PADRAO},
        esperado=(
            "1 mensagem enviada (template 'd-5' de aluguel, citando o vencimento). "
            "1 update de status: p_status='pendente' (inalterado), p_dias_atraso=-5, "
            "p_mensagem_estagio='d-5'. Sem escalonamento."
        ),
    ),
    CenarioCron(
        nome="conta_agua_d0",
        descricao="Conta de água vence hoje — deve usar o template de CONTA (mais enxuto), não o de aluguel.",
        charges_raw=[
            _charge_raw(
                contract_id=CONTRACT_ID_AGUA,
                charge_id="charge-agua-d0",
                tipo="agua",
                valor_esperado=95.30,
                dias_offset=0,
                status="pendente",
                mensagem_estagio=None,
            )
        ],
        dados_por_contrato={CONTRACT_ID_AGUA: DADOS_CONTRATO_PADRAO},
        esperado=(
            "1 mensagem enviada, template de conta ('Hoje é o vencimento da sua conta de água'), "
            "sem quebra de multa/juros/total (isso só aparece a partir de D+5). "
            "Update: p_status='pendente', p_dias_atraso=0, p_mensagem_estagio='d0'."
        ),
    ),
    CenarioCron(
        nome="aluguel_d15_escalonamento",
        descricao=(
            "Aluguel 15 dias atrasado, já tinha recebido a mensagem de D+10 — deve mandar a "
            "mensagem de D+15 E acionar o escalonamento automático (motivo=atraso_severo)."
        ),
        charges_raw=[
            _charge_raw(
                contract_id=CONTRACT_ID_ESCALONAMENTO,
                charge_id="charge-d15",
                tipo="aluguel",
                valor_esperado=2200.0,
                dias_offset=15,
                status="atrasado",
                mensagem_estagio="d+10",
            )
        ],
        dados_por_contrato={CONTRACT_ID_ESCALONAMENTO: DADOS_CONTRATO_PADRAO},
        esperado=(
            "1 mensagem enviada (template d+15, com multa/juros/total calculados). Update: "
            "p_status='atrasado', p_dias_atraso=15, p_mensagem_estagio='d+15'. "
            "1 chamada a executar_escalonamento com motivo='atraso_severo', "
            "deteccao_via_mensagem=False (verificar na sua AvaliacaoEscalonamento real) e "
            "descricao citando 15 dias."
        ),
    ),
    CenarioCron(
        nome="charge_pausada_em_negociacao",
        descricao=(
            "Charge com status='em_negociacao' — mesmo com 10 dias de atraso (bateria D+10), "
            "a pausa automática (STATUS_PAUSADOS) deve impedir QUALQUER ação."
        ),
        charges_raw=[
            _charge_raw(
                contract_id=CONTRACT_ID_PAUSADO,
                charge_id="charge-pausada",
                tipo="aluguel",
                valor_esperado=2200.0,
                dias_offset=10,
                status="em_negociacao",
                mensagem_estagio=None,
            )
        ],
        dados_por_contrato={CONTRACT_ID_PAUSADO: DADOS_CONTRATO_PADRAO},
        esperado="ZERO mensagens enviadas, ZERO updates de status, ZERO escalonamentos.",
    ),
    CenarioCron(
        nome="mensagem_estagio_ja_enviada",
        descricao=(
            "Charge em D+5 cujo mensagem_estagio já é 'd+5' — não deve reenviar a mesma "
            "mensagem (idempotência do cron rodando todo dia)."
        ),
        charges_raw=[
            _charge_raw(
                contract_id=CONTRACT_ID_DUPLICADO,
                charge_id="charge-duplicada",
                tipo="aluguel",
                valor_esperado=2200.0,
                dias_offset=5,
                status="atrasado",
                mensagem_estagio="d+5",
            )
        ],
        dados_por_contrato={CONTRACT_ID_DUPLICADO: DADOS_CONTRATO_PADRAO},
        esperado="ZERO mensagens enviadas, ZERO updates de status (estagio == mensagem_estagio já salvo).",
    ),
    CenarioCron(
        nome="lote_com_charge_invalida",
        descricao=(
            "Lote com uma charge corrompida (contract_id ausente, falha na validação do "
            "schema ChargeAtiva) MISTURADA com uma charge válida — o cron não pode travar "
            "o lote inteiro por causa de uma linha ruim; a válida tem que ser processada "
            "normalmente e a corrompida só deve gerar um log de erro."
        ),
        charges_raw=[
            {  # charge corrompida: falta contract_id (campo obrigatório do schema)
                "charge_id": "charge-corrompida",
                "tipo": "aluguel",
                "mes_referencia": HOJE.replace(day=1).isoformat(),
                "valor_esperado": 2200.0,
                "data_vencimento": HOJE.isoformat(),
                "data_pagamento": None,
                "dias_atraso": 0,
                "status": "pendente",
                "mensagem_estagio": None,
            },
            _charge_raw(
                contract_id=CONTRACT_ID_LOTE_ERRO_OK,
                charge_id="charge-valida-no-lote",
                tipo="agua",
                valor_esperado=95.30,
                dias_offset=0,
                status="pendente",
                mensagem_estagio=None,
            ),
        ],
        dados_por_contrato={CONTRACT_ID_LOTE_ERRO_OK: DADOS_CONTRATO_PADRAO},
        esperado=(
            "1 mensagem enviada (só a charge válida, template conta d0). 1 log de erro "
            "('Falha ao processar charge...') para a charge corrompida. O lote continua "
            "até o fim — sem exceção não tratada subindo até o chamador."
        ),
    ),
]


def _cliente_agente_fake_cron(dados_por_contrato: dict, updates_registrados: list) -> MagicMock:
    """Fabrica de clients fake, um por contract_id — mesma assinatura de
    obter_client_agente(contract_id) no código real."""

    def _fabrica(contract_id: str) -> MagicMock:
        client = MagicMock()

        def _rpc(nome_funcao: str, parametros: dict):
            builder = MagicMock()
            if nome_funcao == "buscar_dados_cobranca_contrato":
                builder.execute.return_value = MagicMock(data=dados_por_contrato[contract_id])
            elif nome_funcao == "agent_update_charge_status":
                updates_registrados.append({"contract_id": contract_id, **parametros})
                builder.execute.return_value = MagicMock(data=None)
            else:
                raise ValueError(f"RPC não mockada neste teste (client_agente): {nome_funcao}")
            return builder

        client.rpc.side_effect = _rpc
        return client

    return _fabrica


def _rodar_cenario_cron(cenario: CenarioCron) -> None:
    print(f"\n{'=' * 78}\nCENÁRIO (CRON): {cenario.nome}\n{cenario.descricao}\n{'=' * 78}")

    mensagens_enviadas: list = []
    escalonamentos: list = []
    updates_status: list = []

    client_cron_fake = MagicMock()
    client_cron_fake.rpc.return_value.execute.return_value = MagicMock(data=cenario.charges_raw)

    def _fake_enviar_mensagem(telefone: str, texto: str) -> None:
        mensagens_enviadas.append({"telefone": telefone, "texto": texto})

    def _fake_executar_escalonamento(contract_id: str, avaliacao) -> str:
        escalonamentos.append({"contract_id": contract_id, "avaliacao": avaliacao})
        return "ESC-2026-TESTE"

    with patch(
        "app.agents.a2_cobranca.cobranca.obter_client_cron_batch",
        return_value=client_cron_fake,
    ), patch(
        "app.agents.a2_cobranca.cobranca.obter_client_agente",
        side_effect=_cliente_agente_fake_cron(cenario.dados_por_contrato, updates_status),
    ), patch(
        "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca",
        side_effect=_fake_enviar_mensagem,
    ), patch(
        "app.agents.a2_cobranca.cobranca.executar_escalonamento",
        side_effect=_fake_executar_escalonamento,
    ):
        from app.agents.a2_cobranca.cobranca import executar_cobranca_diaria

        executar_cobranca_diaria(hoje=HOJE)

    print(f"\n--- ESPERADO ---\n{cenario.esperado}")

    print(f"\n--- MENSAGENS ENVIADAS ({len(mensagens_enviadas)}) ---")
    for m in mensagens_enviadas:
        print(f"[{m['telefone']}]\n{m['texto']}\n")

    print(f"--- UPDATES DE STATUS ({len(updates_status)}) ---")
    for u in updates_status:
        print(u)

    print(f"\n--- ESCALONAMENTOS ({len(escalonamentos)}) ---")
    for e in escalonamentos:
        print(f"contract_id={e['contract_id']} avaliacao={e['avaliacao']}")


# =============================================================================
# PARTE 2 — LEITURA DE COMPROVANTE POR VISÃO (chamada REAL à API da Claude)
# =============================================================================


def _gerar_imagem_recibo_sintetico(linhas: list) -> str:
    """Desenha um 'recibo' fake com Pillow (fundo branco, texto preto) e
    devolve como PNG em base64 — usado pra exercitar extrair_dados_comprovante
    de verdade, sem precisar de um comprovante real."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (700, 450), color="white")
    draw = ImageDraw.Draw(img)
    try:
        fonte = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    except OSError:
        fonte = ImageFont.load_default()

    y = 40
    for linha in linhas:
        draw.text((40, y), linha, font=fonte, fill="black")
        y += 45

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _gerar_imagem_nao_e_recibo() -> str:
    """Simula o inquilino mandando a foto errada por engano — um cartão de
    aniversário, não um comprovante de pagamento. Testa se o modelo marca
    legivel=False corretamente em vez de alucinar um valor."""
    return _gerar_imagem_recibo_sintetico(
        [
            "Feliz aniversário, Maria!",
            "",
            "Que seu dia seja repleto de alegria",
            "e muitas felicidades.",
            "",
            "Com carinho, sua família <3",
        ]
    )


@dataclass
class CenarioComprovante:
    nome: str
    descricao: str
    contract_id: str
    charges_abertas: list  # [{"id":..., "tipo":..., "valor_esperado":...}, ...]
    dados_contrato: dict
    esperado: str
    linhas_recibo: Optional[list] = None  # None => usa _gerar_imagem_nao_e_recibo()


CENARIOS_COMPROVANTE: list[CenarioComprovante] = [
    CenarioComprovante(
        nome="comprovante_unica_charge_aberta",
        descricao="Só 1 charge em aberto no contrato (Caso A) — sem ambiguidade nenhuma pra resolver.",
        contract_id="aaaaaaaa-0000-0000-0000-000000000001",
        charges_abertas=[{"id": "charge-unica", "tipo": "aluguel", "valor_esperado": 2200.0}],
        dados_contrato=DADOS_CONTRATO_PADRAO,
        linhas_recibo=[
            "COMPROVANTE DE TRANSFERÊNCIA PIX",
            "Valor: R$ 2.200,00",
            "Data: 15/07/2026",
            "Favorecido: Imobiliaria Recife Ltda",
        ],
        esperado=(
            "legivel=True, valor~2200.0, data~2026-07-15. Caso A: a única charge aberta é "
            "marcada como 'aguardando_confirmacao'. notificar_fernanda_comprovante chamado "
            "com valor_esperado=2200.0 e SEM nota_deteccao_automatica (não havia ambiguidade)."
        ),
    ),
    CenarioComprovante(
        nome="comprovante_valor_bate_individual",
        descricao=(
            "2 charges em aberto (aluguel 2200 + água 95,30) — o valor do recibo bate só com "
            "o aluguel, não com a soma (2295,30). Deve resolver por valor (Caso B.a), com nota "
            "avisando que foi detecção automática."
        ),
        contract_id="aaaaaaaa-0000-0000-0000-000000000002",
        charges_abertas=[
            {"id": "charge-aluguel-2", "tipo": "aluguel", "valor_esperado": 2200.0},
            {"id": "charge-agua-2", "tipo": "agua", "valor_esperado": 95.30},
        ],
        dados_contrato=DADOS_CONTRATO_PADRAO,
        linhas_recibo=[
            "COMPROVANTE PIX",
            "Valor: R$ 2.200,00",
            "Data: 16/07/2026",
            "Favorecido: Imobiliaria Recife Ltda",
        ],
        esperado=(
            "legivel=True, valor~2200.0. Caso B.a: só a charge de aluguel (2200.0) é marcada "
            "como 'aguardando_confirmacao'; a de água NÃO é tocada. "
            "notificar_fernanda_comprovante chamado COM nota_deteccao_automatica mencionando "
            "'aluguel' e 'valor'."
        ),
    ),
    CenarioComprovante(
        nome="comprovante_pagamento_combinado",
        descricao=(
            "2 charges em aberto (aluguel 2200 + água 100 = soma 2300) — o valor do recibo "
            "bate com a SOMA, não com nenhuma individualmente. Caso B.b: pagamento combinado."
        ),
        contract_id="aaaaaaaa-0000-0000-0000-000000000003",
        charges_abertas=[
            {"id": "charge-aluguel-3", "tipo": "aluguel", "valor_esperado": 2200.0},
            {"id": "charge-agua-3", "tipo": "agua", "valor_esperado": 100.0},
        ],
        dados_contrato=DADOS_CONTRATO_PADRAO,
        linhas_recibo=[
            "COMPROVANTE PIX",
            "Valor: R$ 2.300,00",
            "Data: 17/07/2026",
            "Favorecido: Imobiliaria Recife Ltda",
        ],
        esperado=(
            "legivel=True, valor~2300.0. Caso B.b: AMBAS as charges (aluguel e água) são "
            "marcadas como 'aguardando_confirmacao'. notificar_fernanda_pagamento_combinado "
            "chamado com as 2 charges envolvidas (não notificar_fernanda_comprovante)."
        ),
    ),
    CenarioComprovante(
        nome="comprovante_sem_match",
        descricao=(
            "2 charges em aberto (aluguel 2200 + água 95) — valor do recibo (R$ 500) não bate "
            "com nenhuma individual nem com a soma (2295). Caso B.c: não adivinha nada."
        ),
        contract_id="aaaaaaaa-0000-0000-0000-000000000004",
        charges_abertas=[
            {"id": "charge-aluguel-4", "tipo": "aluguel", "valor_esperado": 2200.0},
            {"id": "charge-agua-4", "tipo": "agua", "valor_esperado": 95.0},
        ],
        dados_contrato=DADOS_CONTRATO_PADRAO,
        linhas_recibo=[
            "COMPROVANTE PIX",
            "Valor: R$ 500,00",
            "Data: 17/07/2026",
            "Favorecido: Loja de Materiais de Construcao",
        ],
        esperado=(
            "legivel=True, valor~500.0. Caso B.c: NENHUMA charge marcada como "
            "'aguardando_confirmacao' (zero updates de status). notificar_fernanda_sem_match "
            "chamado listando as 2 charges em aberto, sem escolher nenhuma."
        ),
    ),
    CenarioComprovante(
        nome="comprovante_ilegivel_foto_errada",
        descricao=(
            "Inquilino manda a foto errada (cartão de aniversário) em vez de um comprovante. "
            "Deve marcar legivel=False e NÃO tocar em nenhuma charge nem notificar a Fernanda."
        ),
        contract_id="aaaaaaaa-0000-0000-0000-000000000005",
        charges_abertas=[{"id": "charge-irrelevante", "tipo": "aluguel", "valor_esperado": 2200.0}],
        dados_contrato=DADOS_CONTRATO_PADRAO,
        linhas_recibo=None,  # sinaliza uso de _gerar_imagem_nao_e_recibo()
        esperado=(
            "legivel=False (observacoes explicando que não parece um comprovante). ZERO "
            "updates de status, ZERO notificações à Fernanda — só um log de warning."
        ),
    ),
]


def _cliente_agente_fake_comprovante(
    dados_contrato: dict, charges_abertas: list, updates_registrados: list
) -> MagicMock:
    client = MagicMock()

    def _rpc(nome_funcao: str, parametros: dict):
        builder = MagicMock()
        if nome_funcao == "buscar_dados_cobranca_contrato":
            builder.execute.return_value = MagicMock(data=dados_contrato)
        elif nome_funcao == "agent_update_charge_status":
            updates_registrados.append(parametros)
            builder.execute.return_value = MagicMock(data=None)
        else:
            raise ValueError(f"RPC não mockada neste teste (client_agente): {nome_funcao}")
        return builder

    client.rpc.side_effect = _rpc

    # client.table("charges").select(...).eq(...).in_(...).execute() -> data=charges_abertas
    tabela_mock = MagicMock()
    tabela_mock.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(
        data=charges_abertas
    )
    client.table.return_value = tabela_mock

    return client


def _rodar_cenario_comprovante(cenario: CenarioComprovante) -> None:
    print(f"\n{'=' * 78}\nCENÁRIO (COMPROVANTE — chamada real à API): {cenario.nome}\n{cenario.descricao}\n{'=' * 78}")

    if cenario.linhas_recibo is not None:
        imagem_base64 = _gerar_imagem_recibo_sintetico(cenario.linhas_recibo)
    else:
        imagem_base64 = _gerar_imagem_nao_e_recibo()

    updates_status: list = []
    notificacoes_comprovante: list = []
    notificacoes_combinado: list = []
    notificacoes_sem_match: list = []

    def _fake_notificar_comprovante(*args, **kwargs) -> None:
        notificacoes_comprovante.append({"args": args, "kwargs": kwargs})

    def _fake_notificar_combinado(*args, **kwargs) -> None:
        notificacoes_combinado.append({"args": args, "kwargs": kwargs})

    def _fake_notificar_sem_match(*args, **kwargs) -> None:
        notificacoes_sem_match.append({"args": args, "kwargs": kwargs})

    client_fake = _cliente_agente_fake_comprovante(
        cenario.dados_contrato, cenario.charges_abertas, updates_status
    )

    with patch(
        "app.agents.a2_cobranca.comprovante.obter_client_agente",
        return_value=client_fake,
    ), patch(
        "app.agents.a2_cobranca.comprovante.notificar_fernanda_comprovante",
        side_effect=_fake_notificar_comprovante,
    ), patch(
        "app.agents.a2_cobranca.comprovante.notificar_fernanda_pagamento_combinado",
        side_effect=_fake_notificar_combinado,
    ), patch(
        "app.agents.a2_cobranca.comprovante.notificar_fernanda_sem_match",
        side_effect=_fake_notificar_sem_match,
    ):
        from app.agents.a2_cobranca.comprovante import processar_comprovante_recebido

        # A chamada real à API da Claude (extrair_dados_comprovante) acontece
        # DENTRO desta função, sem nenhum mock — é aqui que o modelo de
        # verdade tenta ler a imagem sintética gerada acima.
        processar_comprovante_recebido(cenario.contract_id, imagem_base64, "image/png")

    print(f"\n--- ESPERADO ---\n{cenario.esperado}")

    print(f"\n--- UPDATES DE STATUS ({len(updates_status)}) ---")
    for u in updates_status:
        print(u)

    print(f"\n--- notificar_fernanda_comprovante ({len(notificacoes_comprovante)} chamada(s)) ---")
    for n in notificacoes_comprovante:
        print(n["args"], n["kwargs"])

    print(f"\n--- notificar_fernanda_pagamento_combinado ({len(notificacoes_combinado)} chamada(s)) ---")
    for n in notificacoes_combinado:
        print(n["args"], n["kwargs"])

    print(f"\n--- notificar_fernanda_sem_match ({len(notificacoes_sem_match)} chamada(s)) ---")
    for n in notificacoes_sem_match:
        print(n["args"], n["kwargs"])


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    args = sys.argv[1:]

    if "--listar" in args:
        print("Cenários de CRON (sem API):")
        for c in CENARIOS_CRON:
            print(f"  {c.nome}: {c.descricao}")
        print("\nCenários de COMPROVANTE (chamada real à API da Claude):")
        for c in CENARIOS_COMPROVANTE:
            print(f"  {c.nome}: {c.descricao}")
        return

    so_cron = "--so-cron" in args
    so_comprovante = "--so-comprovante" in args
    nomes_pedidos = [a for a in args if not a.startswith("--")]

    rodar_cron = not so_comprovante
    rodar_comprovante = not so_cron

    if rodar_comprovante and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Defina ANTHROPIC_API_KEY antes de rodar os cenários de comprovante "
            "(ou use --so-cron para rodar só os cenários que não chamam a API)."
        )

    cron_a_rodar = (
        [c for c in CENARIOS_CRON if c.nome in nomes_pedidos] if nomes_pedidos else CENARIOS_CRON
    )
    comprovante_a_rodar = (
        [c for c in CENARIOS_COMPROVANTE if c.nome in nomes_pedidos]
        if nomes_pedidos
        else CENARIOS_COMPROVANTE
    )

    if nomes_pedidos and not cron_a_rodar and not comprovante_a_rodar:
        nomes_validos = ", ".join([c.nome for c in CENARIOS_CRON] + [c.nome for c in CENARIOS_COMPROVANTE])
        raise SystemExit(f"Nenhum cenário encontrado para {nomes_pedidos}. Válidos: {nomes_validos}")

    if rodar_cron:
        for cenario in cron_a_rodar:
            _rodar_cenario_cron(cenario)

    if rodar_comprovante:
        for cenario in comprovante_a_rodar:
            _rodar_cenario_comprovante(cenario)


if __name__ == "__main__":
    main()