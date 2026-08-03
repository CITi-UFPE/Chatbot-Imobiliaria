import base64
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

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
    "candidatos vazia em vez de forçar uma correspondência."
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

    return ExtracaoContaAguaResult.model_validate(_extrair_payload(tool_use.input))