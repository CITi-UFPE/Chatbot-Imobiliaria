import base64
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

from app.models.charge import ContratoParaMatch, ExtracaoContaAguaResult
from app.tools.anthropic_helpers import extrair_bloco_tool_use

load_dotenv()

MODEL = "claude-sonnet-5"

# Conta de água é um documento curto (1-2 páginas) e a saída é um objeto
# pequeno, sem transcrição extensa como as cláusulas de contrato — não há
# risco de estourar em max_tokens nem necessidade de streaming aqui.
MAX_TOKENS = 2000

SYSTEM_PROMPT = (
    "Você é um assistente especializado em ler contas de água de condomínios "
    "brasileiros e identificar a qual contrato de aluguel cadastrado o imóvel "
    "do documento corresponde. Extraia os campos solicitados com a maior "
    "precisão possível; se um campo não estiver presente no documento, deixe-o "
    "como null em vez de inventar um valor. "
    "Nomes de condomínio podem aparecer com abreviações, ordem de palavras ou "
    "grafia diferentes entre o documento e o cadastro de contratos — raciocine "
    "sobre isso em vez de exigir correspondência exata de texto. Nunca invente "
    "um contract_id que não esteja na lista de contratos recebida. Se nenhum "
    "contrato corresponder com confiança razoável, devolva a lista de "
    "candidatos vazia em vez de forçar uma correspondência. "
    "Para mes_referencia: preencha esse campo SOMENTE se o documento trouxer "
    "o mês de referência escrito explicitamente (ex: 'Referência: Julho/2025', "
    "'Competência 07/2025', 'Mês de consumo: Julho'), no formato 'YYYY-MM'. "
    "Não deduza o mês a partir do período de leitura (periodo_inicio/"
    "periodo_fim) nem da data de emissão/vencimento — se não houver texto "
    "explícito indicando o mês de referência, deixe null; a decisão de qual "
    "mês usar nesse caso é feita por outra etapa do sistema."
)

TOOL_NAME = "registrar_leitura_conta_agua"


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": (
            "Registra os dados extraídos da conta de água e os contratos "
            "candidatos correspondentes ao imóvel do documento."
        ),
        "input_schema": ExtracaoContaAguaResult.model_json_schema(),
    }


def _extrair_payload(entrada_bruta: dict) -> dict:
    """Isola o payload esperado mesmo se a Claude embrulhar a resposta numa
    chave extra não prevista no schema — mesma cautela de contract_extraction.py."""
    if "condominio" in entrada_bruta:
        return entrada_bruta
    for valor in entrada_bruta.values():
        if isinstance(valor, dict) and "condominio" in valor:
            return valor
    raise RuntimeError(
        f"Formato de resposta inesperado da Claude, chaves recebidas: {list(entrada_bruta.keys())}"
    )


def extrair_e_identificar_conta_agua(
    caminho_pdf: str,
    contratos_ativos: list[ContratoParaMatch],
    model: str = MODEL,
) -> ExtracaoContaAguaResult:
    pdf_base64 = base64.standard_b64encode(Path(caminho_pdf).read_bytes()).decode("ascii")
    contratos_json = json.dumps([c.model_dump() for c in contratos_ativos], ensure_ascii=False)
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
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Este é o PDF de uma conta de água de um condomínio. "
                            "Extraia os campos pedidos e compare o imóvel do "
                            "documento com esta lista de contratos ativos "
                            "cadastrados:\n\n"
                            f"{contratos_json}\n\n"
                            "Aponte o(s) contrato(s) mais prováveis usando o "
                            "contract_id exatamente como aparece na lista acima."
                        ),
                    },
                ],
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude recusou a extração para {caminho_pdf}: {response.stop_reason}")

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Resposta truncada por atingir MAX_TOKENS={MAX_TOKENS} para {caminho_pdf} "
            f"({response.usage.output_tokens} tokens de saída gerados)."
        )

    tool_use = extrair_bloco_tool_use(response)
    if tool_use is None:
        raise RuntimeError(f"Claude não retornou dados estruturados para {caminho_pdf}")

    try:
        return ExtracaoContaAguaResult.model_validate(_extrair_payload(tool_use.input))
    except ValidationError as e:
        # Acontece quando o documento não é uma conta de água de verdade (ex:
        # usuário sobe o PDF errado por engano) — a tool é forçada
        # (tool_choice explícito), então mesmo sem conseguir extrair nada
        # coerente, a Claude ainda tenta preencher os campos obrigatórios do
        # schema e às vezes devolve um placeholder tipo "<UNKNOWN>" em vez de
        # um valor real, que não bate com o tipo esperado (ex: Decimal). Sem
        # este catch, isso sobe como ValidationError pro chamador — o router
        # (app/api/routers/charges.py) só sabe traduzir RuntimeError em erro
        # HTTP 422 "educado", então um ValidationError cru vira 500.
        raise RuntimeError(
            f"Claude devolveu dados que não correspondem ao formato esperado de uma conta "
            f"de água para {caminho_pdf} — provavelmente o documento não é uma conta de "
            f"água: {e}"
        ) from e