import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.models.charge import ContratoParaMatch, ExtracaoContaAguaResult
from app.tools.water_bill_extraction import extrair_e_identificar_conta_agua

router = APIRouter(prefix="/charges", tags=["charges"])

_contratos_adapter = TypeAdapter(list[ContratoParaMatch])


@router.post("/agua/extrair")
def extrair_conta_agua(
    arquivo: UploadFile = File(...),
    contratos: str = Form(...),
) -> ExtracaoContaAguaResult:
    """Recebe o PDF de uma conta de água + a lista de contratos ativos
    (enviada pelo frontend, campo `contratos` como JSON), extrai os dados
    do documento via Claude e devolve, no mesmo passo, os contratos
    candidatos com grau de confiança e justificativa. Não grava nada no
    Supabase — quem grava em `charges` é o frontend, só depois da
    confirmação humana na tela de conferência."""
    if arquivo.content_type != "application/pdf":
        raise HTTPException(
            status_code=415, detail="Arquivo deve ser um PDF (application/pdf)."
        )

    pdf_bytes = arquivo.file.read()

    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Arquivo deve ser um PDF válido.")

    try:
        contratos_ativos = _contratos_adapter.validate_json(contratos)
    except ValidationError as e:
        raise HTTPException(
            status_code=422, detail=f"Lista de contratos inválida: {e}"
        ) from e

    if not contratos_ativos:
        raise HTTPException(
            status_code=422,
            detail="Nenhum contrato ativo foi enviado para correspondência.",
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        resultado = extrair_e_identificar_conta_agua(tmp_path, contratos_ativos)
    except RuntimeError as e:
        raise HTTPException(
            status_code=422, detail=f"Falha ao processar a conta de água: {e}"
        ) from e
    finally:
        os.unlink(tmp_path)

    return resultado