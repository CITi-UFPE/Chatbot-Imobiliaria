import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.contract import ExtracaoContratoResult
from app.tools.contract_extraction import extrair_dados_contrato

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.post("/extrair")
def extrair_contrato(arquivo: UploadFile = File(...)) -> ExtracaoContratoResult:
    """Recebe o PDF de um contrato, extrai os dados via Claude e devolve o JSON.
    Não grava nada no Supabase — quem grava é o frontend, com a sessão da própria
    gestora logada (RLS staff_full_access já dá acesso total pra staff)."""
    if arquivo.content_type != "application/pdf":
        raise HTTPException(
            status_code=415, detail="Arquivo deve ser um PDF (application/pdf)."
        )

    pdf_bytes = arquivo.file.read()

    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Arquivo deve ser um PDF válido.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        resultado = extrair_dados_contrato(tmp_path)
    except RuntimeError as e:
        raise HTTPException(
            status_code=422, detail=f"Falha ao extrair dados do contrato: {e}"
        ) from e
    finally:
        os.unlink(tmp_path)

    return resultado
