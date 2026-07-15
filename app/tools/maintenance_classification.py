import anthropic
from dotenv import load_dotenv

from app.models.maintenance import ClassificacaoManutencao
from app.tools.anthropic_helpers import extrair_bloco_tool_use
from app.tools.text_matching import contem_palavra

load_dotenv()

# Sonnet 5: mesmo modelo já usado em contract_extraction.py — mantém consistência
# no projeto. Classificação de texto curto num enum pequeno não exige Opus, mas
# Haiku tem menos margem em casos ambíguos (ex: "fiação perto do chuveiro" —
# hidráulica ou elétrica?), que são justamente os que a checagem de confiança
# (ver docs/specs/agente-manutencao.md) precisa pegar corretamente.
MODEL = "claude-sonnet-5"

MAX_TOKENS = 2048

# Sinais que, se presentes na descrição do inquilino, indicam risco imediato à
# vida (gás, fumaça, incêndio, choque) — checados por palavra-chave além do LLM,
# porque para esse caso específico não vale confiar só na extração semântica do
# modelo: um falso negativo aqui significa não orientar o inquilino a acionar
# emergência (bombeiros/193). contem_palavra normaliza acento/caixa e casa só
# palavra inteira, então uma forma canônica sem acento já cobre a acentuada.
_PALAVRAS_EMERGENCIA_REAL = ("gas", "fumaca", "incendio", "choque")

_MARCADOR_EMERGENCIA = "sinal de emergência (gás/fumaça/incêndio/choque) detectado por palavra-chave"

SYSTEM_PROMPT = (
    "Você classifica relatos de problemas de manutenção enviados por inquilinos de imóveis "
    "residenciais alugados. Categorias possíveis: hidraulica, eletrica, pintura, estrutural, "
    "outros. Urgência: alta (risco à segurança ou ao imóvel — ex: vazamento grande, fiação "
    "exposta, porta/fechadura quebrada), media (afeta o uso mas sem risco — ex: chuveiro não "
    "esquenta, torneira pingando), baixa (estético — ex: pintura descascando, rejunte). "
    "Urgência ALTA exige risco explícito de segurança/dano ao imóvel, não apenas a categoria. "
    "Na dúvida entre dois níveis de urgência, classifique como o nível mais alto plausível."
)

TOOL_NAME = "classificar_manutencao"


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Registra a classificação de categoria e urgência do chamado de manutenção.",
        "input_schema": ClassificacaoManutencao.model_json_schema(),
    }


_SYSTEM_PROMPT_ESCLARECIMENTO = (
    "Você ajuda a esclarecer relatos ambíguos de manutenção residencial. Dado o relato do "
    "inquilino e a classificação incerta do sistema, escreva UMA pergunta curta, objetiva e "
    "específica ao caso, mirando só no que gerou a dúvida — não repita o relato, não faça mais "
    "de uma pergunta, não peça informações que o relato já deixou claras."
)


def gerar_pergunta_esclarecimento(
    descricao_livre: str, classificacao: ClassificacaoManutencao, model: str = MODEL
) -> str:
    client = anthropic.Anthropic()

    dimensao_incerta = (
        "categoria" if classificacao.categoria_confidence <= classificacao.urgencia_confidence else "urgência"
    )

    response = client.messages.create(
        model=model,
        max_tokens=256,
        system=_SYSTEM_PROMPT_ESCLARECIMENTO,
        messages=[
            {
                "role": "user",
                "content": (
                    f'Relato do inquilino: "{descricao_livre}"\n'
                    f"Classificação incerta na dimensão: {dimensao_incerta}\n"
                    f"Categoria sugerida: {classificacao.categoria} (confiança {classificacao.categoria_confidence})\n"
                    f"Urgência sugerida: {classificacao.urgencia} (confiança {classificacao.urgencia_confidence})\n"
                    f"Justificativa do sistema: {classificacao.justificativa}\n\n"
                    "Escreva a pergunta de esclarecimento."
                ),
            }
        ],
    )

    texto = next((block.text for block in response.content if block.type == "text"), "").strip()
    if not texto:
        raise RuntimeError("Claude não retornou uma pergunta de esclarecimento")
    return texto


def classificar_manutencao(descricao_livre: str, model: str = MODEL) -> ClassificacaoManutencao:
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[_tool_schema()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": f'Relato do inquilino: "{descricao_livre}"',
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude recusou a classificação: {response.stop_reason}")

    tool_use = extrair_bloco_tool_use(response)
    if tool_use is None:
        raise RuntimeError("Claude não retornou uma classificação estruturada")

    resultado = ClassificacaoManutencao.model_validate(tool_use.input)

    # Rede de segurança determinística: nunca confiar só no LLM para a exceção de
    # emergência real (gás, fumaça, incêndio, choque) — ver docs/specs/agente-manutencao.md.
    # Também registra o gatilho em sinais_risco: sem isso, a notificação da gestora
    # mostrava "Sinais de risco: nenhum" ao lado de "Urgência: alta", sem justificativa.
    if contem_palavra(descricao_livre, _PALAVRAS_EMERGENCIA_REAL):
        sinais_risco = resultado.sinais_risco
        if _MARCADOR_EMERGENCIA not in sinais_risco:
            sinais_risco = [*sinais_risco, _MARCADOR_EMERGENCIA]
        resultado = resultado.model_copy(update={"urgencia": "alta", "sinais_risco": sinais_risco})

    return resultado
