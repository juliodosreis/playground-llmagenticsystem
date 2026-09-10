"""Ferramentas de reserva: as que leem o estado mutável e as que o alteram.

`create_booking` e `cancel_booking` alteram o estado. `get_booking` e `list_bookings` o leem.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from ..domain import operations
from ..runtime import Workspace


def build_booking_tools(workspace: Workspace) -> list[BaseTool]:
    """Cria as ferramentas de reserva ligadas a este workspace."""

    @tool
    def create_booking(
        user_id: str,
        kind: str,
        item_id: str,
        start_date: str,
        price: float,
    ) -> str:
        """Cria uma reserva REAL no banco de dados. kind é 'flight' ou 'hotel'.

        Devolve o booking_id.
        """
        return workspace.call(
            operations.create_booking,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            start_date=start_date,
            price=price,
        )

    @tool
    def get_booking(booking_id: str) -> str:
        """Consulta uma reserva específica pelo seu id (por exemplo BK-0001)."""
        return workspace.call(operations.get_booking, booking_id=booking_id)

    @tool
    def list_bookings(user_id: str) -> str:
        """Lista todas as reservas de um usuário."""
        return workspace.call(operations.list_bookings, user_id=user_id)

    @tool
    def cancel_booking(booking_id: str) -> str:
        """Cancela uma reserva existente (status -> 'cancelled').

        Libera o assento se for um voo.
        """
        return workspace.call(operations.cancel_booking, booking_id=booking_id)

    return [create_booking, get_booking, list_bookings, cancel_booking]
