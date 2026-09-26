"""Estado dos grafos do agente, um por estratégia.

`TravelState` é o estado do laço ReAct, com dois campos. `messages` acumula o histórico pelo
reducer `add_messages`, que anexa as mensagens novas em vez de substituir a lista. `passos` conta as
chamadas ao modelo e entra na condição de parada da rota.

`PlanState` estende `TravelState` com os campos da estratégia Plan-and-Execute. `messages` e
`passos` mantêm o papel que têm no laço, e o harness lê a mensagem final de `messages` nas duas
estratégias.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class TravelState(TypedDict):
    """Histórico da conversa e contador de passos do laço."""

    messages: Annotated[list[AnyMessage], add_messages]
    passos: int


class PlanState(TravelState):
    """Plano, passos executados e evidências de uma execução Plan-and-Execute.

    As listas não têm reducer: cada nó devolve a lista inteira, e o planejador as recomeça
    vazias a cada pedido. `passos_feitos` e `evidencias` andam em par, um item por passo
    executado.
    """

    plano: list[str]
    """Passos em ordem. O replanejador troca os pendentes e mantém os já executados."""

    passos_feitos: list[str]
    evidencias: list[str]
    """O que cada passo executado devolveu: o retorno das ferramentas, ou o texto do executor."""

    recusadas: list[str]
    """Pedidos de chamada que o executor não rodou, com os argumentos e o código da recusa."""

    desvio: bool
    """Verdadeiro quando o último passo trouxe uma busca vazia ou um erro de ferramenta."""

    replanejado: bool
    """Verdadeiro depois da primeira revisão do plano. A rota desvia ao replanejador uma vez."""
