"""Skills: procedimentos em texto, lidos pelo agente quando o pedido corresponde a um deles.

Uma skill é um diretório com o arquivo `SKILL.md`. O arquivo abre com um frontmatter YAML com os
campos `name` e `description`, e o restante é o corpo em markdown, com os passos do procedimento.
O campo `name` repete o nome do diretório.

`SkillCatalog` lê um diretório de skills em dois níveis: `discover` devolve nome e descrição de
cada skill, e `activate` devolve o corpo de uma delas. Os dois leem o disco a cada chamada, e uma
edição do corpo alcança a ativação seguinte. Um nome fora do catálogo devolve um objeto JSON com
o campo `error` e os nomes aceitos, no lugar de uma exceção. `build_read_skill` expõe `activate`
ao modelo como a ferramenta `read_skill`, que registra a chamada no trace do workspace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from langchain_core.tools import BaseTool, tool

from .workspace import Workspace

PROCEDURES = ("prompt", "skills")
"""Origem do procedimento do agente: o prompt de sistema ou as skills lidas por `read_skill`."""

READ_SKILL = "read_skill"
"""Nome da ferramenta que devolve o corpo de uma skill."""


@dataclass(frozen=True)
class Skill:
    """Os campos de um `SKILL.md`: nome e descrição do frontmatter, e o corpo."""

    name: str
    description: str
    body: str


def load_skill(path: Path) -> Skill:
    """Lê um `SKILL.md`.

    O corpo começa na primeira linha com texto depois do frontmatter. Um arquivo sem frontmatter,
    com frontmatter que não é um mapeamento YAML, sem `name` ou `description`, ou com `name`
    diferente do diretório levanta `ValueError`.
    """
    texto = path.read_text(encoding="utf-8")
    if not texto.startswith("---\n"):
        raise ValueError(f"{path}: o arquivo não abre com o frontmatter")
    frontmatter, separador, corpo = texto.removeprefix("---\n").partition("\n---\n")
    if not separador:
        raise ValueError(f"{path}: o frontmatter não tem a linha de fechamento")

    campos = yaml.safe_load(frontmatter) or {}
    if not isinstance(campos, dict):
        raise ValueError(f"{path}: o frontmatter não é um mapeamento YAML")
    ausentes = [campo for campo in ("name", "description") if not campos.get(campo)]
    if ausentes:
        raise ValueError(f"{path}: frontmatter sem {', '.join(ausentes)}")
    if campos["name"] != path.parent.name:
        raise ValueError(
            f"{path}: name {campos['name']!r} difere do diretório {path.parent.name!r}"
        )
    return Skill(str(campos["name"]), str(campos["description"]).strip(), corpo.lstrip("\n"))


@dataclass(frozen=True)
class SkillCatalog:
    """As skills de um diretório, uma por subdiretório com `SKILL.md`."""

    directory: Path

    def names(self) -> list[str]:
        """Nomes das skills, em ordem alfabética."""
        return sorted(path.parent.name for path in self.directory.glob("*/SKILL.md"))

    def get(self, name: str) -> Skill:
        """A skill de nome dado. Um nome fora do catálogo levanta `KeyError`."""
        if name not in self.names():
            raise KeyError(f"skill inexistente: {name!r}. Disponíveis: {', '.join(self.names())}.")
        return load_skill(self.directory / name / "SKILL.md")

    def discover(self) -> list[dict[str, str]]:
        """Nível de descoberta: nome e descrição de cada skill."""
        return [
            {"name": skill.name, "description": skill.description}
            for skill in (self.get(name) for name in self.names())
        ]

    def activate(self, name: str) -> str:
        """Nível de ativação: o corpo da skill, ou o objeto de erro com os nomes aceitos."""
        try:
            return self.get(name).body
        except KeyError:
            erro = {"error": "unknown_skill", "skill": name, "available": self.names()}
            return json.dumps(erro, ensure_ascii=False)


def build_read_skill(catalog: SkillCatalog, workspace: Workspace) -> BaseTool:
    """A ferramenta `read_skill` sobre este catálogo, com a chamada registrada no trace."""

    @tool(READ_SKILL)
    def read_skill(name: str) -> str:
        """Lê o procedimento completo de uma skill, pelo nome da lista de skills disponíveis."""
        corpo = catalog.activate(name)
        workspace.record(READ_SKILL, {"name": name}, corpo)
        return corpo

    return read_skill
