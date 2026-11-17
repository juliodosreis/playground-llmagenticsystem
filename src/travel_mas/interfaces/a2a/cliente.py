"""Cliente A2A sobre JSON-RPC para o endpoint do Agent Server.

Uma conversa com o servidor passa por três chamadas HTTP:

1. `POST /assistants/search` com o `graph_id` de `langgraph.json` e `created_by=system` devolve o
   `assistant_id`, um UUID. O endpoint A2A do Agent Server recusa o `graph_id` no lugar do UUID;
2. `GET /.well-known/agent-card.json?assistant_id=...` devolve o agent card: nome, descrição,
   skills, modos de entrada e saída e a URL do endpoint;
3. `POST /a2a/{assistant_id}` com o método `message/send` e `blocking: true` envia uma mensagem e
   devolve a task terminada, com `id`, `contextId`, `status.state` e os artifacts da resposta.

O cliente usa os nomes de método da versão 0.3 do protocolo, que o servidor aceita junto com os
da 1.0; com eles, os estados chegam em minúsculas (`completed`, `failed`). Uma mensagem sem
`contextId` abre um contexto novo. Repetir o `contextId` devolvido abre uma task nova no mesmo
contexto, e o adaptador do MAS mantém o banco do contexto entre as tasks.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx

from .servidor import ARQUIVO_RELATORIO

URL_PADRAO = "http://127.0.0.1:2024"
GRAFO_PADRAO = "travel_mas_a2a"

Observador = Callable[[str, str, Any], None]
"""Recebe a direção (`->` ou `<-`), o método e a rota HTTP e o corpo JSON de cada troca."""


class ErroA2A(RuntimeError):
    """Erro JSON-RPC devolvido pelo servidor ou resposta sem task."""


@dataclass
class RespostaA2A:
    """Task devolvida por `message/send`, com o texto e o relatório extraídos dos artifacts."""

    task_id: str
    context_id: str
    estado: str
    texto: str
    relatorio: dict | None = None
    bruto: dict = field(default_factory=dict, repr=False)


def _verificar_erro(corpo: dict) -> None:
    if "error" in corpo:
        erro = corpo["error"]
        raise ErroA2A(f"JSON-RPC {erro.get('code')}: {erro.get('message')}")


def ler_task(corpo: dict) -> RespostaA2A:
    """Extrai estado, texto e `relatorio.json` de uma resposta JSON-RPC."""
    _verificar_erro(corpo)
    task = corpo.get("result")
    if not isinstance(task, dict) or "id" not in task:
        raise ErroA2A("a resposta não contém uma task")
    status = task.get("status") or {}
    partes = [parte for artifact in task.get("artifacts") or [] for parte in artifact["parts"]]
    if not partes:
        # Uma task `failed` não tem artifacts; o motivo vem em `status.message`.
        partes = (status.get("message") or {}).get("parts", [])
    textos: list[str] = []
    relatorio = None
    for parte in partes:
        if parte.get("kind") == "text":
            textos.append(parte["text"])
        arquivo = parte.get("file") or {}
        if parte.get("kind") == "file" and arquivo.get("name") == ARQUIVO_RELATORIO:
            relatorio = json.loads(base64.b64decode(arquivo["bytes"]))
    return RespostaA2A(
        task_id=task["id"],
        context_id=task.get("contextId", ""),
        estado=status.get("state", ""),
        texto="\n".join(textos).strip(),
        relatorio=relatorio,
        bruto=corpo,
    )


class ClienteA2A:
    """Descobre o assistant de um grafo, lê o agent card e envia mensagens A2A."""

    def __init__(
        self,
        url: str = URL_PADRAO,
        grafo: str = GRAFO_PADRAO,
        *,
        timeout: float = 900.0,
        transport: httpx.BaseTransport | None = None,
        observador: Observador | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.grafo = grafo
        self.observador = observador
        self.http = httpx.Client(base_url=self.url, timeout=timeout, transport=transport)
        self._assistant_id: str | None = None

    def _trocar(self, metodo: str, rota: str, *, corpo: Any = None, params=None) -> Any:
        if self.observador and corpo is not None:
            self.observador("->", f"{metodo} {rota}", corpo)
        resposta = self.http.request(
            metodo, rota, json=corpo, params=params, headers={"Accept": "application/json"}
        )
        resposta.raise_for_status()
        dados = resposta.json()
        if self.observador:
            self.observador("<-", f"{metodo} {rota}", dados)
        return dados

    def assistant_id(self) -> str:
        """UUID do assistant que o servidor criou para o grafo, buscado uma vez.

        O filtro `created_by=system` exclui os assistants criados depois, por exemplo no Studio,
        que a busca devolveria primeiro.
        """
        if self._assistant_id is None:
            corpo = {"graph_id": self.grafo, "metadata": {"created_by": "system"}, "limit": 1}
            encontrados = self._trocar("POST", "/assistants/search", corpo=corpo)
            if not encontrados:
                raise ErroA2A(f"o servidor não tem assistant para o grafo {self.grafo!r}")
            self._assistant_id = encontrados[0]["assistant_id"]
        return self._assistant_id

    def card(self) -> dict:
        """Agent card do assistant."""
        dados = self._trocar(
            "GET",
            "/.well-known/agent-card.json",
            params={"assistant_id": self.assistant_id()},
        )
        _verificar_erro(dados)
        return dados

    def enviar(self, texto: str, context_id: str | None = None) -> RespostaA2A:
        """Envia `texto` por `message/send` e espera a task terminar."""
        mensagem: dict[str, Any] = {
            "role": "user",
            "parts": [{"kind": "text", "text": texto}],
            "messageId": uuid4().hex,
        }
        if context_id:
            mensagem["contextId"] = context_id
        envelope = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "message/send",
            "params": {
                "message": mensagem,
                "configuration": {"blocking": True, "historyLength": 0},
            },
        }
        return ler_task(self._trocar("POST", f"/a2a/{self.assistant_id()}", corpo=envelope))

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> ClienteA2A:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
