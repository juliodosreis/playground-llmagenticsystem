"""Intervenções reproduzíveis; nenhuma falha depende de instruir o modelo a errar."""

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

DEFEITOS = ("D1", "D2", "D3", "D4", "D5", "D6")
EVENTOS = (
    "agent_start",
    "agent_end",
    "handoff",
    "tool_call",
    "tool_result",
    "injection_applied",
    "termination",
    "error",
)


class ToolFault(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: "tool:" + uuid4().hex)
    tool: str
    tipo: Literal["error", "timeout", "vazia", "inconsistente"]
    n_chamada: int | None = Field(default=1, ge=1)
    resultado: Any = None


class MessageFault(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: "message:" + uuid4().hex)
    aresta: str
    tipo: Literal["campo_faltante", "obsoleta", "de_outra_tarefa", "perdida"]
    campo: str = "evidencia"
    mensagem_tipo: str = "Proposta"
    n_mensagem: int | None = Field(default=1, ge=1)


def capabilities() -> dict:
    """Contrato estático do adaptador, consultável sem carregar um LLM."""
    from ..domain import OPERATIONS

    return {
        "estado_inicial": ["flights", "hotels", "bookings"],
        "ferramentas": list(OPERATIONS),
        "condicion_herramienta": ["error", "timeout", "vazia", "inconsistente"],
        "condicion_transferencia": ["campo_faltante", "obsoleta", "de_outra_tarefa", "perdida"],
        "agentes": ["coordenador", "pesquisador", "verificador", "reservador"],
        "transferencias": ["Pedido", "Proposta", "Veredito", "Ordem", "Relatorio"],
        "configuracion": ["provider", "model", "temperature", "topologia", "max_rodadas"],
        "topologias": ["workflow", "supervisor"],
        "defeitos": list(DEFEITOS),
        "eventos": list(EVENTOS),
    }


def validate_faults(tool_faults, message_faults):
    caps = capabilities()
    ids = []
    for fault in tool_faults:
        if fault.tool not in caps["ferramentas"]:
            raise ValueError(f"ferramenta sem suporte: {fault.tool}")
        ids.append(fault.id)
    for fault in message_faults:
        aresta = fault.aresta.replace("→", "->").split("->")
        if len(aresta) != 2 or any(a not in caps["agentes"] for a in aresta):
            raise ValueError(f"aresta sem suporte: {fault.aresta}")
        if fault.mensagem_tipo not in caps["transferencias"]:
            raise ValueError(f"transferência sem suporte: {fault.mensagem_tipo}")
        ids.append(fault.id)
    if len(ids) != len(set(ids)):
        raise ValueError("ids de falhas devem ser únicos")
