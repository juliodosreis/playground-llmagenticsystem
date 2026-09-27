"""Publicação das seis ferramentas por stdio, pelo servidor de `tools.server.build_mcp_server`.

O servidor roda sobre um workspace próprio, criado na partida do processo. As reservas feitas por
um host ficam nesse banco até o processo terminar, e o banco do agente em outro processo não as
vê.
"""

from __future__ import annotations

from ...runtime import Workspace
from ...tools import build_toolbox
from ...tools.server import build_mcp_server


def serve() -> None:
    """Roda o servidor por stdio até o host fechar a conexão."""
    build_mcp_server(build_toolbox(Workspace()).all()).run("stdio")
