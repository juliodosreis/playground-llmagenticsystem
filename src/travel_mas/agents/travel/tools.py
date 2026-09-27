"""Ferramentas que este agente recebe.

`TOOL_NAMES` lista as ferramentas do agente, e `build_agent_tools` as resolve sobre um workspace,
pela fonte que `Context.tool_source` nomeia. O agente de viagens recebe as seis, com os mesmos
nomes nas duas fontes.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import BaseTool

from ...runtime import Workspace
from ...tools import (
    BOOKING_READ_TOOLS,
    BOOKING_WRITE_TOOLS,
    CATALOG_TOOLS,
    abuild_toolbox,
    build_toolbox,
)

TOOL_NAMES = (*CATALOG_TOOLS, *BOOKING_WRITE_TOOLS, *BOOKING_READ_TOOLS)


async def abuild_agent_tools(workspace: Workspace, source: str = "local") -> list[BaseTool]:
    """Resolve as ferramentas declaradas em `TOOL_NAMES` sobre este workspace, pela fonte dada."""
    return (await abuild_toolbox(workspace, source)).select(*TOOL_NAMES)


def build_agent_tools(workspace: Workspace, source: str = "local") -> list[BaseTool]:
    """Envoltório sincrônico de `abuild_agent_tools`.

    A fonte `mcp` lê o catálogo do servidor em um laço de eventos próprio, por `asyncio.run`. Com
    um laço já em execução no thread, levanta `RuntimeError`, e o chamador usa
    `abuild_agent_tools` com `await`.
    """
    if source == "local":
        return build_toolbox(workspace).select(*TOOL_NAMES)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(abuild_agent_tools(workspace, source))
    raise RuntimeError(
        "há um laço de eventos em execução neste thread. Use `await abuild_agent_tools(...)` ou "
        "`await abuild_graph(...)`."
    )
