import base64
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from app.models.contract import ExtracaoContratoResult
from app.tools.anthropic_helpers import extrair_bloco_tool_use

load_dotenv()

MODEL = "claude-sonnet-5"

# Contratos PJ com cláusulas de compliance extensas (LGPD, anticorrupção) podem passar de
# 16000 tokens de saída ao transcrever tudo verbatim — visto na prática com o contrato ARCO,
# que truncava e resultava em 'clausulas' ausente/vazia (stop_reason='max_tokens').
MAX_TOKENS = 32000

# Fora do git (coberto pelo mesmo .gitignore de data/) — resultados de extração
# contêm PII real (CPF, nomes de inquilino/fiador) e não devem ser versionados.
DIRETORIO_EXTRACOES = Path("data/extracoes")

SYSTEM_PROMPT = (
    "Você é um assistente especializado em extrair dados estruturados de contratos "
    "de aluguel residencial brasileiros. Leia o PDF do contrato e extraia todos os "
    "campos solicitados com a maior precisão possível. Se um campo não estiver "
    "presente no contrato, deixe-o como null em vez de inventar um valor. "
    "Para as cláusulas: percorra o contrato cláusula por cláusula, na ordem em que "
    "aparecem, e inclua TODAS elas na lista — mesmo que pareçam redundantes, "
    "genéricas ou de baixo impacto, e mesmo que o conteúdo não se encaixe bem em "
    "nenhuma categoria disponível (escolha a categoria mais próxima nesse caso). "
    "Não pule nenhuma cláusula. Transcreva o texto original — não resuma nem "
    "parafraseie. Se uma cláusula numerada tiver sub-itens com numeração ou "
    "lettering próprios (ex: 1.1, 1.2, 1.3 dentro da cláusula 1; ou alíneas a), "
    "b), c) dentro de uma cláusula), trate CADA sub-item como uma cláusula "
    "separada na lista, com seu próprio numero_clausula (ex: '1.1', '1.2', ou "
    "'15.a', '15.b' para alíneas sem numeração própria) e sua própria categoria — "
    "não agrupe vários sub-itens sob o número da cláusula-mãe, mesmo que "
    "compartilhem um título ou introdução comuns."
)

TOOL_NAME = "registrar_dados_contrato"


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Registra os dados estruturados extraídos do contrato de aluguel.",
        "input_schema": ExtracaoContratoResult.model_json_schema(),
    }


def _extrair_payload(entrada_bruta: dict) -> dict:
    """Isola o payload esperado ({'contrato': ..., 'clausulas': ...}) mesmo se a Claude
    embrulhar a resposta numa chave extra não prevista no schema (schema não é 'strict'
    porque o schema completo excede o limite de complexidade da API para strict mode)."""
    if "contrato" in entrada_bruta:
        return entrada_bruta
    for valor in entrada_bruta.values():
        if isinstance(valor, dict) and "contrato" in valor:
            return valor
    raise RuntimeError(
        f"Formato de resposta inesperado da Claude, chaves recebidas: {list(entrada_bruta.keys())}"
    )


def extrair_dados_contrato(
    caminho_pdf: str, model: str = MODEL, max_tentativas: int = 2
) -> ExtracaoContratoResult:
    pdf_base64 = base64.standard_b64encode(Path(caminho_pdf).read_bytes()).decode("ascii")
    client = anthropic.Anthropic()

    for _ in range(max_tentativas):
        # MAX_TOKENS=32000 ultrapassa o limite que a SDK aceita em chamada
        # não-streaming (risco de timeout em requests longas) — precisa streaming.
        with client.messages.stream(
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
                            "text": "Extraia os dados estruturados deste contrato de aluguel.",
                        },
                    ],
                }
            ],
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude recusou a extração para {caminho_pdf}: {response.stop_details}")

        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"Resposta truncada por atingir MAX_TOKENS={MAX_TOKENS} para {caminho_pdf} "
                f"({response.usage.output_tokens} tokens de saída gerados) — contrato provavelmente "
                "extenso demais para o limite atual. Não adianta tentar de novo sem aumentar "
                "MAX_TOKENS; o truncamento é determinístico para o mesmo PDF."
            )

        tool_use = extrair_bloco_tool_use(response)
        if tool_use is None:
            raise RuntimeError(f"Claude não retornou dados estruturados para {caminho_pdf}")

        resultado = ExtracaoContratoResult.model_validate(_extrair_payload(tool_use.input))

        # Um contrato de aluguel real sempre tem cláusulas. Já observamos a Claude
        # retornar 'clausulas: []' de forma não-determinística (mesmo prompt, mesmo
        # PDF, chamada em separado) — tratamos isso como resposta suspeita e tentamos
        # de novo antes de aceitar o resultado.
        if resultado.clausulas:
            return resultado

    raise RuntimeError(
        f"Claude retornou zero cláusulas para {caminho_pdf} após {max_tentativas} tentativa(s) — "
        "resultado suspeito para um contrato de aluguel real."
    )


if __name__ == "__main__":
    # No Windows, print() usa o codepage do console (ex: cp1252) em vez de UTF-8
    # quando a saída é redirecionada — sem isso, acentos são gravados incorretamente.
    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) != 2:
        print("Uso: python -m app.tools.contract_extraction <caminho_do_pdf>")
        sys.exit(1)

    caminho_pdf = Path(sys.argv[1])
    resultado = extrair_dados_contrato(str(caminho_pdf))

    DIRETORIO_EXTRACOES.mkdir(parents=True, exist_ok=True)
    caminho_saida = DIRETORIO_EXTRACOES / f"{caminho_pdf.stem}.json"
    caminho_saida.write_text(
        resultado.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
    )
    print(f"Extração salva em: {caminho_saida}")
