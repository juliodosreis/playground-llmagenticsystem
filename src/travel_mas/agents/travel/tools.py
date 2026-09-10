"""Ferramentas que este agente recebe.

`TOOL_NAMES` lista as ferramentas do agente, e `build_agent_tools` as resolve sobre um workspace. O
agente de viagens recebe as seis.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from ...runtime import Workspace
from ...tools import BOOKING_READ_TOOLS, BOOKING_WRITE_TOOLS, CATALOG_TOOLS, build_toolbox

TOOL_NAMES = (*CATALOG_TOOLS, *BOOKING_WRITE_TOOLS, *BOOKING_READ_TOOLS)


def build_agent_tools(workspace: Workspace) -> list[BaseTool]:
    """Resolve as ferramentas declaradas em `TOOL_NAMES` sobre este workspace."""
    return build_toolbox(workspace).select(*TOOL_NAMES)
