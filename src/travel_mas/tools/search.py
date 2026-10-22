"""Ferramentas de leitura do catálogo.

`search_flights` e `search_hotels` consultam `flights` e `hotels`; `check_item` lê o estado atual
de um voo ou hotel pelo id. Nenhuma das três altera o estado.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from ..domain import operations
from ..runtime import Workspace


def build_catalog_tools(workspace: Workspace) -> list[BaseTool]:
    """Cria as ferramentas de busca ligadas a este workspace."""

    @tool
    def search_flights(
        origin: str,
        destination: str,
        date: str,
        max_price: float = 1e9,
    ) -> str:
        """Busca voos. origin/destination são códigos IATA (MAD, LIM).

        date no formato YYYY-MM-DD.
        """
        return workspace.call(
            operations.search_flights,
            origin=origin,
            destination=destination,
            date=date,
            max_price=max_price,
        )

    @tool
    def search_hotels(city: str, max_price_per_night: float = 1e9) -> str:
        """Busca hotéis em uma cidade (código IATA) abaixo de um preço por noite."""
        return workspace.call(
            operations.search_hotels,
            city=city,
            max_price_per_night=max_price_per_night,
        )

    @tool
    def check_item(kind: str, item_id: str) -> str:
        """Consulta preço, data e assentos atuais de flight/hotel, ou devolve not_found."""
        return workspace.call(operations.check_item, kind=kind, item_id=item_id)

    return [search_flights, search_hotels, check_item]
