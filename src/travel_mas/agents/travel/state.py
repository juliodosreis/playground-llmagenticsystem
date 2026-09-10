"""Estado do grafo.

Dois campos. `messages` acumula o histórico pelo reducer `add_messages`, que anexa as mensagens
novas em vez de substituir a lista. `passos` conta as chamadas ao modelo e entra na condição de
parada da rota.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class TravelState(TypedDict):
    """Histórico da conversa e contador de passos do laço."""

    messages: Annotated[list[AnyMessage], add_messages]
    passos: int
