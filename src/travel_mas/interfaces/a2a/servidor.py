"""Grafo adaptador que expõe o MAS pelo endpoint A2A do Agent Server.

O endpoint `/a2a/{assistant_id}` do Agent Server converte a parte de texto de uma mensagem A2A em
um `HumanMessage` na chave `messages` do estado e devolve as partes do último `AIMessage` como o
artifact da task. O `MASState` não tem `messages`. Este grafo recebe a conversa, entrega o texto
da última mensagem do usuário ao MAS como `pedido_usuario` e responde com o `Relatorio`: o campo
`mensagem` em uma parte de texto e o relatório inteiro, com o motivo de terminação, em uma parte de
arquivo `relatorio.json` (`application/json`).

O `contextId` da A2A chega ao grafo como `thread_id`. Cada contexto recebe um ambiente próprio,
com banco e MAS compilado, mantido entre as tasks do contexto: uma reserva criada em uma task
aparece na seguinte. Os ambientes ficam fora do estado do grafo, em `AMBIENTES`, e se perdem quando
o processo do servidor termina. `AMBIENTES` guarda os `MAX_CONTEXTOS` contextos usados por último.
Uma execução sem `thread_id` recebe um ambiente que não é guardado.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from ...agents.mas.graph import abuild_graph as abuild_mas
from ...runtime import Context, Workspace, load_chat_model

ARQUIVO_RELATORIO = "relatorio.json"
MAX_CONTEXTOS = 32


class A2AState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    relatorio: dict
    motivo_terminacao: str


@dataclass
class Ambiente:
    """Banco e MAS compilado de um contexto A2A."""

    workspace: Workspace
    grafo: Any


AMBIENTES: dict[str, Ambiente] = {}


def resposta_a2a(relatorio: dict, motivo: str) -> AIMessage:
    """`AIMessage` com a mensagem do relatório em texto e o relatório em `relatorio.json`."""
    dados = {**relatorio, "motivo_terminacao": motivo}
    arquivo = base64.b64encode(json.dumps(dados, ensure_ascii=False).encode()).decode("ascii")
    return AIMessage(
        [
            {"type": "text", "text": relatorio.get("mensagem", "")},
            {
                "type": "file",
                "base64": arquivo,
                "mime_type": "application/json",
                "filename": ARQUIVO_RELATORIO,
            },
        ]
    )


def build_graph(
    context=None,
    model=None,
    ambientes: dict[str, Ambiente] | None = None,
    max_contextos: int = MAX_CONTEXTOS,
):
    """Compila o adaptador; o modelo e cada MAS são criados na primeira task que os usa."""
    context = context or Context()
    ambientes = AMBIENTES if ambientes is None else ambientes
    modelo = model

    async def ambiente_de(config: RunnableConfig) -> Ambiente:
        nonlocal modelo
        chave = (config.get("configurable") or {}).get("thread_id")
        if chave is not None and chave in ambientes:
            ambientes[chave] = ambientes.pop(chave)  # o contexto usado vai para o fim da ordem
            return ambientes[chave]
        if modelo is None:
            modelo = await asyncio.to_thread(load_chat_model, context)
        # O Agent Server recusa I/O bloqueante no laço: o SQLite nasce em um thread.
        workspace = await asyncio.to_thread(Workspace)
        ambiente = Ambiente(workspace, await abuild_mas(workspace, context, modelo))
        if chave is not None:
            ambientes[chave] = ambiente
            while len(ambientes) > max_contextos:
                del ambientes[next(iter(ambientes))]
        return ambiente

    async def atender(state: A2AState, config: RunnableConfig) -> dict:
        humanas = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
        pedido = humanas[-1].text.strip() if humanas else ""
        if not pedido:
            raise ValueError("a mensagem A2A não tem uma parte de texto com o pedido")
        ambiente = await ambiente_de(config)
        # O banco continua; o trace e os eventos da task anterior não entram nesta (R10).
        ambiente.workspace.reset_registros()
        final = await ambiente.grafo.ainvoke(
            {"pedido_usuario": pedido}, {"recursion_limit": context.recursion_limit}
        )
        relatorio = final.get("relatorio") or {}
        motivo = final.get("motivo_terminacao", "")
        return {
            "messages": [resposta_a2a(relatorio, motivo)],
            "relatorio": relatorio,
            "motivo_terminacao": motivo,
        }

    builder = StateGraph(A2AState)
    builder.add_node("atender", atender)
    builder.add_edge(START, "atender")
    builder.add_edge("atender", END)
    return builder.compile(name="travel-mas-a2a")


async def make_graph():
    """Agent Server: o adaptador com os ambientes de `AMBIENTES`."""
    return build_graph()
