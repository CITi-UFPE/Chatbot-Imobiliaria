from typing import Any, Optional


def extrair_bloco_tool_use(response: Any) -> Optional[Any]:
    """Isola o primeiro bloco tool_use de uma resposta da API Claude, ou None."""
    return next((block for block in response.content if block.type == "tool_use"), None)
