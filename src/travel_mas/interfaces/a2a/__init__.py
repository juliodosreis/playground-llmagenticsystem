"""Transporte A2A do MAS: grafo adaptador no Agent Server, cliente JSON-RPC e agente cliente."""

from .agente_cliente import build_agente_cliente, ferramenta_a2a
from .cliente import ClienteA2A, ErroA2A, RespostaA2A, ler_task
from .servidor import AMBIENTES, A2AState, build_graph, make_graph

__all__ = [
    "AMBIENTES",
    "A2AState",
    "ClienteA2A",
    "ErroA2A",
    "RespostaA2A",
    "build_agente_cliente",
    "build_graph",
    "ferramenta_a2a",
    "ler_task",
    "make_graph",
]
