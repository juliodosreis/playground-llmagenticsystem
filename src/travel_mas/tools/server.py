"""Servidor MCP que publica ferramentas locais.

`build_mcp_server` registra no servidor a função de cada ferramenta dada, com o mesmo nome e a
mesma descrição. O servidor deriva o schema de entrada da assinatura da função, como faz o `@tool`
do LangChain. As ferramentas de `build_toolbox` fecham sobre um workspace, e a chamada pelo
servidor grava no banco e no trace desse workspace.

O `FastMCP` chama uma função sincrônica no thread do laço de eventos, e a operação sobre o SQLite
bloquearia o laço durante a consulta. `in_worker_thread` registra no lugar dela uma corrotina que
a roda em um thread de trabalho, como o `ToolNode` roda a ferramenta local. Uma ferramenta
assíncrona tem `func` vazio, e o servidor registra a corrotina dela sem envoltório.

O construtor do `FastMCP` chama `logging.basicConfig` no logger raiz. Num processo sem handler
configurado, como a CLI, a chamada fixaria o nível em `ERROR` e esconderia os avisos das demais
bibliotecas. `root_logging_preserved` devolve ao logger raiz o nível e os handlers de antes.

O servidor não abre transporte. `tools/remote.py` o conecta ao agente por canais em memória, no
mesmo processo, e `interfaces/mcp/` o publica por stdio.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from langchain_core.tools import StructuredTool
from mcp.server.fastmcp import FastMCP

SERVER_NAME = "travel-mas"


def in_worker_thread(funcao: Callable[..., str]) -> Callable[..., Awaitable[str]]:
    """Corrotina com a assinatura de `funcao`, que a executa em um thread de trabalho."""

    @functools.wraps(funcao)
    async def executar(**argumentos) -> str:
        return await asyncio.to_thread(funcao, **argumentos)

    return executar


@contextmanager
def root_logging_preserved() -> Iterator[None]:
    """Restaura o nível e os handlers do logger raiz ao sair do bloco."""
    raiz = logging.getLogger()
    nivel, handlers = raiz.level, list(raiz.handlers)
    try:
        yield
    finally:
        raiz.setLevel(nivel)
        for handler in list(raiz.handlers):
            if handler not in handlers:
                raiz.removeHandler(handler)


def build_mcp_server(tools: list[StructuredTool]) -> FastMCP:
    """Servidor MCP com as ferramentas dadas, na ordem da lista."""
    with root_logging_preserved():
        servidor = FastMCP(SERVER_NAME, log_level="ERROR")
    for ferramenta in tools:
        funcao = ferramenta.coroutine or in_worker_thread(ferramenta.func)
        servidor.add_tool(
            funcao,
            name=ferramenta.name,
            description=ferramenta.description,
        )
    return servidor
