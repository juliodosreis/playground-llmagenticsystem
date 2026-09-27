"""Cliente MCP: as ferramentas de um servidor, adaptadas a ferramentas do LangChain.

Uma `Connection` abre uma sessão MCP já inicializada. `load_mcp_tools` abre uma sessão, lê o
catálogo por `list_tools` e devolve uma `StructuredTool` por ferramenta publicada, com o nome, a
descrição e o schema de entrada que o servidor declara.

A ferramenta adaptada é assíncrona. Cada chamada abre uma sessão pela `Connection`, envia
`call_tool` e devolve o texto do resultado. Um resultado com `isError` vira `ToolException`, e a
ferramenta devolve o texto do servidor no campo `error` de um JSON, o formato dos erros das
operações do domínio. O retorno chega ao modelo como `ToolMessage` com status `error`, e o
executor do Plan-and-Execute o lê como desvio.

`in_memory` conecta a um servidor do mesmo processo por canais em memória, sem subprocesso. O
banco e o trace do servidor ficam no workspace do processo, e o harness os lê como lê os das
ferramentas locais.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, Implementation, TextContent, Tool

Connection = Callable[[], AbstractAsyncContextManager[ClientSession]]
"""Abre uma sessão MCP inicializada, fechada ao sair do bloco `async with`."""

CLIENT_INFO = Implementation(name="travel-mas-agent", version="1.0")


def in_memory(servidor: FastMCP) -> Connection:
    """Conexão com um servidor do mesmo processo, por canais em memória."""

    def conectar() -> AbstractAsyncContextManager[ClientSession]:
        return create_connected_server_and_client_session(servidor, client_info=CLIENT_INFO)

    return conectar


def result_text(resultado: CallToolResult) -> str:
    """Os blocos de texto do resultado, unidos por quebra de linha."""
    return "\n".join(bloco.text for bloco in resultado.content if isinstance(bloco, TextContent))


def error_payload(erro: ToolException) -> str:
    """O texto do erro do servidor no campo `error`, como as operações do domínio o devolvem."""
    return json.dumps({"error": str(erro)}, ensure_ascii=False)


def adapt_tool(conectar: Connection, ferramenta: Tool) -> StructuredTool:
    """Converte uma ferramenta MCP em ferramenta do LangChain que chama o servidor."""

    async def executar(**argumentos) -> str:
        async with conectar() as sessao:
            resultado = await sessao.call_tool(ferramenta.name, argumentos)
        texto = result_text(resultado)
        if resultado.isError:
            raise ToolException(texto)
        return texto

    return StructuredTool(
        name=ferramenta.name,
        description=ferramenta.description or "",
        args_schema=ferramenta.inputSchema,
        coroutine=executar,
        handle_tool_error=error_payload,
    )


async def load_mcp_tools(conectar: Connection) -> list[BaseTool]:
    """Lê o catálogo do servidor e adapta cada ferramenta, na ordem que o servidor publica."""
    async with conectar() as sessao:
        catalogo = await sessao.list_tools()
    return [adapt_tool(conectar, ferramenta) for ferramenta in catalogo.tools]
