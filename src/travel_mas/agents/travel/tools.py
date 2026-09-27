"""Ferramentas que este agente recebe.

`TOOL_NAMES` lista as ferramentas do sistema que o agente recebe, e `build_agent_tools` as resolve
sobre um workspace, pela fonte que `Context.tool_source` nomeia. O agente de viagens recebe as
seis, com os mesmos nomes nas duas fontes.

Com `Context.procedure` em `skills`, o agente recebe também `read_skill`, sobre as skills de
`prompts.SKILLS`. A ferramenta roda no processo com as duas fontes, porque as skills são do agente
e o servidor MCP publica as ferramentas do sistema.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import BaseTool

from ...runtime import Workspace, build_read_skill
from ...tools import (
    BOOKING_READ_TOOLS,
    BOOKING_WRITE_TOOLS,
    CATALOG_TOOLS,
    abuild_toolbox,
    build_toolbox,
)
from .prompts import SKILLS

TOOL_NAMES = (*CATALOG_TOOLS, *BOOKING_WRITE_TOOLS, *BOOKING_READ_TOOLS)


def skill_tools(workspace: Workspace, procedure: str) -> list[BaseTool]:
    """`read_skill` quando o procedimento é `skills`, e nenhuma ferramenta em `prompt`."""
    return [build_read_skill(SKILLS, workspace)] if procedure == "skills" else []


async def abuild_agent_tools(
    workspace: Workspace,
    source: str = "local",
    procedure: str = "prompt",
) -> list[BaseTool]:
    """Resolve as ferramentas do agente sobre este workspace, pela fonte e pelo procedimento."""
    tools = (await abuild_toolbox(workspace, source)).select(*TOOL_NAMES)
    return [*tools, *skill_tools(workspace, procedure)]


def build_agent_tools(
    workspace: Workspace,
    source: str = "local",
    procedure: str = "prompt",
) -> list[BaseTool]:
    """Envoltório sincrônico de `abuild_agent_tools`.

    A fonte `mcp` lê o catálogo do servidor em um laço de eventos próprio, por `asyncio.run`. Com
    um laço já em execução no thread, levanta `RuntimeError`, e o chamador usa
    `abuild_agent_tools` com `await`.
    """
    if source == "local":
        tools = build_toolbox(workspace).select(*TOOL_NAMES)
        return [*tools, *skill_tools(workspace, procedure)]
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(abuild_agent_tools(workspace, source, procedure))
    raise RuntimeError(
        "há um laço de eventos em execução neste thread. Use `await abuild_agent_tools(...)` ou "
        "`await abuild_graph(...)`."
    )
