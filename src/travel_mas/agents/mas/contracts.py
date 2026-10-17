"""Contratos públicos; nenhum contrato inclui o histórico privado de um agente."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Agente = Literal["coordenador", "pesquisador", "verificador", "reservador"]


class Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemPedido(Contrato):
    kind: Literal["flight", "hotel"]
    data: str
    origem: str | None = None
    destino: str | None = None
    cidade: str | None = None
    noites: int = Field(default=1, ge=1)
    teto: float | None = Field(default=None, ge=0)


class Pedido(Contrato):
    tarefa_id: str
    user_id: str | None
    itens: list[ItemPedido]
    acao: Literal["reservar", "listar", "cancelar"]
    booking_id: str | None = None
    listar_depois: bool = False
    cancelar_depois: bool = False


class Proposta(Contrato):
    tarefa_id: str
    proposta_id: str
    kind: Literal["flight", "hotel"]
    # As descrições chegam ao modelo no esquema da ferramenta de saída.
    item_id: str = Field(
        description="Valor literal do campo id de uma linha da busca, como FL-101 ou HT-2; "
        "nunca posição, índice ou rótulo."
    )
    price_total: float = Field(
        ge=0, description="Voo: price da linha. Hotel: price_per_night vezes noites."
    )
    date: str
    evidencia: str = Field(
        description="Valor do campo evidencia do retorno da busca que contém a linha do item."
    )
    noites: int = Field(default=1, ge=1)


class Veredito(Contrato):
    tarefa_id: str
    proposta_id: str
    aprovado: bool
    motivo: str


class Ordem(Contrato):
    tarefa_id: str
    proposta_id: str | None = None
    user_id: str
    acao: Literal["reservar", "listar", "cancelar"] = "reservar"
    booking_id: str | None = None
    listar_depois: bool = False
    cancelar_depois: bool = False


class Relatorio(Contrato):
    tarefa_id: str
    booking_ids: list[str] = Field(default_factory=list)
    erros: list[str] = Field(default_factory=list)
    mensagem: str = ""


class ResultadoPesquisa(Contrato):
    propostas: list[Proposta]
    motivo: str = ""


class ResultadoVerificacao(Contrato):
    vereditos: list[Veredito]


class Decisao(Contrato):
    """Saída do Coordenador: normalizar, autorizar a execução ou concluir."""

    proximo: Literal["pesquisador", "verificador", "reservador", "fim"]
    pedido: Pedido | None = None
    ordens: list[Ordem] = Field(default_factory=list)
    relatorio: Relatorio | None = None


TRANSFERENCIAS = {cls.__name__: cls for cls in (Pedido, Proposta, Veredito, Ordem, Relatorio)}
