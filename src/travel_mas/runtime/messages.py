"""Leitura das mensagens que um grafo devolve."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


def last_text(messages: Sequence[BaseMessage]) -> str:
    """Última mensagem do assistente com texto.

    Alguns modelos encerram com um `AIMessage` de `content` vazio, com todo o output em
    `reasoning`. Ler `messages[-1].content` devolveria string vazia nesse caso, então a busca recua
    até encontrar conteúdo.
    """
    for message in reversed(list(messages)):
        if not isinstance(message, AIMessage):
            continue
        content: Any = message.content
        if isinstance(content, list):  # blocos de conteúdo: concatena os de texto
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""
