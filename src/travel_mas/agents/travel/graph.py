"""Topologia do agente: o laço de ferramentas escrito como grafo do LangGraph.

    START -> chamar_modelo -> decidir_proximo_no
                                 |-- há pedidos e passos < limite -> executar_ferramentas
                                 |                                        |
                                 |                                        +-> chamar_modelo
                                 +-- caso contrário --------------------------> END

`chamar_modelo` acrescenta o prompt de sistema ao histórico e chama o modelo com as ferramentas
ligadas. `executar_ferramentas` roda os pedidos da última mensagem e devolve uma `ToolMessage` por
pedido. A rota lê a última mensagem e o contador de passos.

O nó do modelo é assíncrono, então o grafo se invoca por `ainvoke`. Uma ferramenta sincrônica roda
nesse grafo sem alteração, e o caminho aceita ferramenta assíncrona, como a de um servidor MCP.

O nó de ferramentas é um `ToolNode`, que devolve o erro da ferramenta como `ToolMessage`. A falha
entra no histórico e o modelo a recebe na chamada seguinte.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from ...runtime import Context, Workspace, load_chat_model, with_transient_retry
from .prompts import SYSTEM_PROMPT
from .state import TravelState
from .tools import build_agent_tools


def build_graph(
    workspace: Workspace | None = None,
    context: Context | None = None,
    model: BaseChatModel | None = None,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    """Compila o agente sobre um workspace.

    O workspace é o banco desta execução. As ferramentas fecham sobre ele, então trocar o banco
    entre execuções é chamar `Workspace.reset()`, sem reconstruir o grafo.
    """
    workspace = workspace if workspace is not None else Workspace()
    context = context or Context()
    model = model if model is not None else load_chat_model(context)
    tools = tools if tools is not None else build_agent_tools(workspace)

    model_with_tools = with_transient_retry(model.bind_tools(tools), context.retry_attempts)
    limite = context.max_steps

    async def chamar_modelo(state: TravelState) -> dict:
        """Chama o modelo com o prompt de sistema e o histórico, e conta o passo."""
        historico = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        resposta = await model_with_tools.ainvoke(historico)
        return {"messages": [resposta], "passos": state.get("passos", 0) + 1}

    def decidir_proximo_no(state: TravelState) -> Literal["executar", "fim"]:
        """Continua enquanto houver pedido de chamada e o limite de passos não for atingido."""
        ultima = state["messages"][-1]
        if getattr(ultima, "tool_calls", None) and state.get("passos", 0) < limite:
            return "executar"
        return "fim"

    builder = StateGraph(TravelState)
    builder.add_node("chamar_modelo", chamar_modelo)
    builder.add_node("executar_ferramentas", ToolNode(tools))

    builder.add_edge(START, "chamar_modelo")
    builder.add_conditional_edges(
        "chamar_modelo",
        decidir_proximo_no,
        {"executar": "executar_ferramentas", "fim": END},
    )
    builder.add_edge("executar_ferramentas", "chamar_modelo")

    return builder.compile(name="travel-agent")


async def make_graph() -> CompiledStateGraph:
    """Grafo para o LangGraph Studio, sobre um workspace novo.

    O banco fica no processo do servidor: as reservas de uma sessão do Studio continuam visíveis na
    seguinte. `runtime.run_task` parte de um banco limpo a cada execução.

    O servidor do Studio chama esta função no laço de eventos, e `Workspace()` abre SQLite de forma
    sincrônica. `asyncio.to_thread` roda a montagem em um thread, e o servidor monta o grafo sem
    `--allow-blocking`.
    """
    return await asyncio.to_thread(build_graph)
