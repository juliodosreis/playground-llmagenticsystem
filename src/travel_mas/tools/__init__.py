"""Catálogo de ferramentas do sistema, agrupadas por domínio.

`build_toolbox` cria as seis ferramentas ligadas a um workspace e as indexa por nome.
`Toolbox.select` resolve a lista que um agente declara, e um nome fora do conjunto levanta
`KeyError`.

`abuild_toolbox` monta o mesmo conjunto por uma de duas fontes, listadas em `TOOL_SOURCES`:

- `local`: as funções de `search.py` e `bookings.py`, chamadas no processo;
- `mcp`: as ferramentas que o servidor de `server.py` publica, lidas pelo cliente de `remote.py`
  por canais em memória. Os nomes vêm do catálogo do servidor, em tempo de execução.

As duas fontes gravam no banco e no trace do mesmo workspace. `server.py` e `remote.py` importam
o SDK `mcp`, e `abuild_toolbox` os importa só na fonte `mcp`: com a fonte local, o SDK não entra
no processo.

Um agente sem `create_booking` entre as suas ferramentas não tem como escrever no banco.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from ..runtime import Workspace
from .bookings import build_booking_tools
from .search import build_catalog_tools

# Grupos por efeito, para declarar permissões em bloco.
CATALOG_TOOLS = ("search_flights", "search_hotels")
BOOKING_READ_TOOLS = ("get_booking", "list_bookings")
BOOKING_WRITE_TOOLS = ("create_booking", "cancel_booking")

TOOL_SOURCES = ("local", "mcp")
"""Fontes das ferramentas: chamada no processo ou pelo servidor MCP."""


@dataclass(frozen=True)
class Toolbox:
    """As ferramentas de uma execução, indexadas por nome."""

    tools: dict[str, BaseTool]

    def select(self, *names: str) -> list[BaseTool]:
        """Sublista na ordem declarada. Um nome inexistente é erro de configuração."""
        desconhecidos = [name for name in names if name not in self.tools]
        if desconhecidos:
            raise KeyError(
                f"ferramenta inexistente: {', '.join(desconhecidos)}. "
                f"Disponíveis: {', '.join(self.tools)}."
            )
        return [self.tools[name] for name in names]

    def all(self) -> list[BaseTool]:
        return list(self.tools.values())

    @property
    def names(self) -> list[str]:
        return list(self.tools)


def build_toolbox(workspace: Workspace) -> Toolbox:
    """Cria as seis ferramentas ligadas a este workspace."""
    tools = [*build_catalog_tools(workspace), *build_booking_tools(workspace)]
    return Toolbox({tool.name: tool for tool in tools})


async def abuild_toolbox(workspace: Workspace, source: str = "local") -> Toolbox:
    """Cria as ferramentas ligadas a este workspace pela fonte dada.

    Uma fonte fora de `TOOL_SOURCES` levanta `ValueError`.
    """
    if source == "local":
        return build_toolbox(workspace)
    if source == "mcp":
        from .remote import in_memory, load_mcp_tools
        from .server import build_mcp_server

        servidor = build_mcp_server(build_toolbox(workspace).all())
        tools = await load_mcp_tools(in_memory(servidor))
        return Toolbox({tool.name: tool for tool in tools})
    conhecidas = ", ".join(TOOL_SOURCES)
    raise ValueError(f"fonte de ferramentas desconhecida: {source!r}. Use {conhecidas}.")


__all__ = [
    "BOOKING_READ_TOOLS",
    "BOOKING_WRITE_TOOLS",
    "CATALOG_TOOLS",
    "TOOL_SOURCES",
    "Toolbox",
    "abuild_toolbox",
    "build_booking_tools",
    "build_catalog_tools",
    "build_toolbox",
]
