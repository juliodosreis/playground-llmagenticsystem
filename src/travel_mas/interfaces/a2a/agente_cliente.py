"""Agente cliente que delega pedidos de viagem ao MAS por A2A.

O agente é um `create_agent` com uma ferramenta. A ferramenta é montada a partir do agent card do
servidor: o nome vem de `card["name"]`, e a descrição reúne a descrição do card e a das skills. A
chamada da ferramenta envia o pedido por `message/send` e devolve ao modelo o estado da task, a
mensagem e o `relatorio.json`. O `contextId` da primeira resposta é reenviado nas chamadas
seguintes da mesma ferramenta, então as tasks de uma conversa compartilham o banco do servidor.
"""

from __future__ import annotations

import json
import re

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ...runtime import Context, load_chat_model
from .cliente import ClienteA2A

SYSTEM_PROMPT = """Você é o assistente de viagens de um usuário.

Você não acessa o sistema de reservas. Buscas, reservas, consultas e cancelamentos são feitos por
um agente remoto, alcançado pela ferramenta {ferramenta}, que usa o protocolo A2A.

- O agente remoto não vê esta conversa. Envie a ele um pedido completo em português, com o id do
  usuário, origem, destino, datas e orçamento que o usuário informou.
- Faça uma chamada por pedido do usuário e não repita um pedido que o agente remoto já atendeu.
- Responda ao usuário com o resultado devolvido, citando os ids de reserva e os preços em EUR.
  Não afirme uma reserva que o agente remoto não informou.
"""


class PedidoRemoto(BaseModel):
    pedido: str = Field(
        description="Pedido completo em português para o agente remoto, com o id do usuário."
    )


def ferramenta_a2a(cliente: ClienteA2A) -> StructuredTool:
    """Ferramenta que envia um pedido ao agent card do servidor e guarda o `contextId`."""
    card = cliente.card()
    nome = "a2a_" + re.sub(r"[^a-zA-Z0-9_-]", "_", card["name"])
    skills = "; ".join(s.get("description", "") for s in card.get("skills", []))
    descricao = f"Agente remoto A2A {card['name']}: {card.get('description', '')}"
    if skills and skills != card.get("description"):
        descricao += f" Skills: {skills}"
    contexto: dict[str, str | None] = {"id": None}

    def delegar(pedido: str) -> str:
        resposta = cliente.enviar(pedido, contexto["id"])
        contexto["id"] = resposta.context_id
        dados = {"estado": resposta.estado, "mensagem": resposta.texto}
        if resposta.relatorio is not None:
            dados["relatorio"] = resposta.relatorio
        return json.dumps(dados, ensure_ascii=False)

    return StructuredTool.from_function(
        func=delegar, name=nome, description=descricao, args_schema=PedidoRemoto
    )


def build_agente_cliente(cliente: ClienteA2A, context: Context | None = None, model=None):
    """Compila o agente cliente sobre o card lido de `cliente`."""
    ferramenta = ferramenta_a2a(cliente)
    model = model if model is not None else load_chat_model(context or Context())
    return create_agent(
        model,
        tools=[ferramenta],
        system_prompt=SYSTEM_PROMPT.format(ferramenta=ferramenta.name),
        name="agente-cliente-a2a",
    )
