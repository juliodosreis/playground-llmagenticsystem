"""Catálogo de ferramentas do sistema, agrupadas por domínio.

`build_toolbox` cria as seis ferramentas ligadas a um workspace e as indexa por nome.
`Toolbox.select` resolve a lista que um agente declara, e um nome fora do conjunto levanta
`KeyError`.

Um agente sem `create_booking` entre as suas ferramentas não tem como escrever no banco.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from ..runtime import Workspace
from .bookings import build_booking_tools
from .search import build_catalog_tools

# Grupos por efeito, para quem precisa declarar permissões em bloco.
CATALOG_TOOLS = ("search_flights", "search_hotels")
BOOKING_READ_TOOLS = ("get_booking", "list_bookings")
BOOKING_WRITE_TOOLS = ("create_booking", "cancel_booking")


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


__all__ = [
    "BOOKING_READ_TOOLS",
    "BOOKING_WRITE_TOOLS",
    "CATALOG_TOOLS",
    "Toolbox",
    "build_booking_tools",
    "build_catalog_tools",
    "build_toolbox",
]
