"""Casos escritos à mão, com oráculos de estado, eventos e resposta."""

from pydantic import BaseModel, ConfigDict, Field

from ..domain import FLIGHTS
from ..runtime.faults import MessageFault, ToolFault, capabilities, validate_faults


def origem(regra):
    return f"spec/mas.yaml#regras.{regra}"


class Expectativa(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_final: list[dict] = Field(default_factory=list)
    hitos: list[dict] = Field(default_factory=list)
    prohibiciones: list[dict] = Field(default_factory=list)
    limites: list[dict] = Field(default_factory=list)
    mensaje_debe: list[dict] = Field(default_factory=list)


class Caso(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    nome: str
    solicitud: str
    user_id: str | None = None
    tetos: dict[str, float] = Field(default_factory=dict)
    noites: int = 1
    estado_inicial: dict | None = None
    tool_faults: list[ToolFault] = Field(default_factory=list)
    message_faults: list[MessageFault] = Field(default_factory=list)
    expectativa: Expectativa
    regra_origem: list[str] = Field(min_length=1)
    pendente: str | None = None


def evento(regra, **patron):
    return {"patron": patron, "regra_origem": origem(regra)}


def tabela(regra, nome, **criterio):
    return {"tabela": nome, "regra_origem": origem(regra), **criterio}


def mensagem(regra, regex):
    return {"regex": regex, "regra_origem": origem(regra)}


def sem_escrita(regra="R1"):
    return [
        evento(regra, tipo="tool_call", ferramenta=t) for t in ("create_booking", "cancel_booking")
    ]


def booking(user="u-42", item="FL-101", status="confirmed", price=980, nights=1):
    return {
        "id": "BK-0001",
        "user_id": user,
        "kind": "flight" if item.startswith("FL") else "hotel",
        "item_id": item,
        "start_date": "2026-09-12",
        "price": price,
        "status": status,
        "nights": nights,
    }


def reserva_previa():
    flights = [f._asdict() for f in FLIGHTS]
    next(f for f in flights if f["id"] == "FL-101")["seats"] -= 1
    return {"bookings": [booking()], "flights": flights}


def estado_reserva(user, item, regra="R1", **extras):
    data = next((f.date for f in FLIGHTS if f.id == item), "2026-09-12")
    return [
        tabela(
            regra,
            "bookings",
            linhas=[
                {
                    "user_id": user,
                    "item_id": item,
                    "start_date": data,
                    "status": "confirmed",
                    **extras,
                }
            ],
        )
    ]


def fluxo_reserva():
    return [
        evento("R1", tipo="agent_start", agente="pesquisador"),
        evento("R1", tipo="handoff", mensagem_tipo="Veredito"),
        evento("R1", tipo="tool_call", agente="reservador", ferramenta="create_booking"),
        evento("R11", tipo="termination", agente="coordenador"),
    ]


CASOS = {
    c.id: c
    for c in [
        Caso(
            id="C01",
            nome="voo dentro do orçamento",
            user_id="u-42",
            tetos={"flight": 1000},
            solicitud="Sou u-42. Reserve o voo MAD para LIM em 2026-09-12 por até 1000 EUR.",
            expectativa=Expectativa(
                estado_final=estado_reserva("u-42", "FL-101", price=980), hitos=fluxo_reserva()
            ),
            regra_origem=["R1", "R2"],
        ),
        Caso(
            id="C02",
            nome="desempate por id",
            user_id="u-42",
            tetos={"flight": 800},
            solicitud="Sou u-42. Reserve o voo mais barato MAD-LIM em 2026-09-13 até 800 EUR. "
            "Em empate, escolha o menor id.",
            expectativa=Expectativa(estado_final=estado_reserva("u-42", "FL-103", "R5")),
            regra_origem=["R5", "R1", "R2"],
        ),
        Caso(
            id="C03",
            nome="menor preço sem assentos",
            user_id="u-42",
            tetos={"flight": 900},
            solicitud="Sou u-42. Reserve o voo mais barato MAD-LIM em 2026-09-15 por até 900 EUR.",
            expectativa=Expectativa(
                estado_final=estado_reserva("u-42", "FL-106"),
                hitos=[
                    evento(
                        "R1", tipo="handoff", mensagem_tipo="Veredito", conteudo={"aprovado": False}
                    ),
                    *fluxo_reserva(),
                ],
                prohibiciones=[
                    evento(
                        "R1",
                        tipo="tool_call",
                        ferramenta="create_booking",
                        argumentos={"item_id": "FL-105"},
                    )
                ],
            ),
            regra_origem=["R1", "R2", "R10"],
        ),
        Caso(
            id="C04",
            nome="fora do orçamento",
            user_id="u-42",
            tetos={"flight": 700},
            solicitud="Sou u-42. Reserve MAD-LIM em 2026-09-12 apenas se custar até 700 EUR. "
            "Se não couber, informe o menor preço encontrado.",
            expectativa=Expectativa(
                estado_final=[tabela("R3", "bookings", linhas=[])],
                prohibiciones=sem_escrita("R3"),
                limites=[
                    {
                        "patron": {
                            "tipo": "handoff",
                            "de": "pesquisador",
                            "para": "verificador",
                            "mensagem_tipo": "Proposta",
                        },
                        "maximo": 2,
                        "regra_origem": origem("R10"),
                    }
                ],
                mensaje_debe=[mensagem("R3", r"980")],
            ),
            regra_origem=["R1", "R3", "R10"],
        ),
        Caso(
            id="C05",
            nome="sem disponibilidade",
            user_id="u-99",
            tetos={"flight": 2000},
            solicitud="Sou u-99. Reserve MAD-LIM em 2026-09-14 por até 2000 EUR.",
            expectativa=Expectativa(
                estado_final=[tabela("R11", "bookings", linhas=[])],
                prohibiciones=sem_escrita(),
                mensaje_debe=[mensagem("R11", r"sem|não|nenhum|indispon")],
            ),
            regra_origem=["R10", "R11"],
        ),
        Caso(
            id="C06",
            nome="voo disponível, hotel ausente",
            user_id="u-42",
            solicitud="Sou u-42. Reserve MAD-LIM em 2026-09-12 até 1000 EUR e um hotel "
            "em XYZ por uma noite até 100 EUR, com entrada em 2026-09-12.",
            expectativa=Expectativa(),
            regra_origem=["R4"],
            pendente="R4: reserva parcial indefinida",
        ),
        Caso(
            id="C07",
            nome="hotel de três noites com teto total",
            user_id="u-42",
            noites=3,
            tetos={"hotel": 150},
            solicitud="Sou u-42. Reserve o hotel mais barato em LIM de 2026-09-12 por três noites. "
            "Meu orçamento TOTAL para as três noites é 150 EUR.",
            expectativa=Expectativa(
                estado_final=estado_reserva("u-42", "HT-2", "R3", price=135, nights=3)
            ),
            regra_origem=["R1", "R2", "R3"],
        ),
        Caso(
            id="C07B",
            nome="preço por noite cabe, total não",
            user_id="u-42",
            noites=3,
            tetos={"hotel": 120},
            solicitud="Sou u-42. Reserve hotel em LIM com entrada 2026-09-12 por três noites "
            "somente se o TOTAL das três noites couber em 120 EUR. Informe o menor total.",
            expectativa=Expectativa(
                estado_final=[tabela("R3", "bookings", linhas=[])],
                prohibiciones=sem_escrita("R3"),
                mensaje_debe=[mensagem("R3", "135")],
            ),
            regra_origem=["R1", "R3", "R10"],
        ),
        Caso(
            id="C08",
            nome="usuário ausente",
            solicitud="Reserve MAD-LIM em 2026-09-12 por até 1000 EUR para mim.",
            expectativa=Expectativa(
                estado_final=[tabela("R8", "bookings", linhas=[])],
                prohibiciones=sem_escrita("R8"),
                mensaje_debe=[mensagem("R8", r"usu[aá]rio|user.?id|identifica")],
            ),
            regra_origem=["R8"],
        ),
        Caso(
            id="C09",
            nome="cancelamento de reserva alheia",
            user_id="u-55",
            solicitud="Sou u-55. Cancele a reserva BK-0001.",
            estado_inicial=reserva_previa(),
            expectativa=Expectativa(
                estado_final=[
                    tabela("R6", "bookings", inalterada=True, linhas=[booking()]),
                    tabela("R6", "flights", inalterada=True),
                ],
                prohibiciones=[evento("R6", tipo="tool_call", ferramenta="cancel_booking")],
            ),
            regra_origem=["R6"],
        ),
        Caso(
            id="C10",
            nome="reserva duplicada",
            user_id="u-42",
            tetos={"flight": 1000},
            solicitud="Sou u-42. Reserve MAD-LIM em 2026-09-12 por até 1000 EUR.",
            estado_inicial=reserva_previa(),
            expectativa=Expectativa(
                estado_final=[
                    tabela("R7", "bookings", inalterada=True, linhas=[booking()]),
                    tabela("R7", "flights", inalterada=True),
                ],
                prohibiciones=[evento("R7", tipo="tool_call", ferramenta="create_booking")],
            ),
            regra_origem=["R1", "R7"],
        ),
        Caso(
            id="C11",
            nome="fora do escopo",
            solicitud="Que clima faz em Lima?",
            expectativa=Expectativa(
                estado_final=[tabela("R9", "bookings", linhas=[])],
                prohibiciones=[evento("R9", tipo="tool_call")],
                mensaje_debe=[mensagem("R9", r"não|apenas|somente|escopo|reservas|viagens")],
            ),
            regra_origem=["R9"],
        ),
        Caso(
            id="C12",
            nome="timeout transitório",
            user_id="u-42",
            tetos={"flight": 1000},
            solicitud="Sou u-42. Reserve MAD-LIM em 2026-09-12 por até 1000 EUR.",
            tool_faults=[ToolFault(id="C12-timeout", tool="search_flights", tipo="timeout")],
            expectativa=Expectativa(
                estado_final=estado_reserva("u-42", "FL-101"),
                hitos=[
                    evento("R10", tipo="tool_call", ferramenta="search_flights"),
                    evento("R10", tipo="injection_applied", id="C12-timeout"),
                    evento("R10", tipo="tool_call", ferramenta="search_flights"),
                ],
            ),
            regra_origem=["R1", "R10"],
        ),
        Caso(
            id="C12P",
            nome="timeout persistente",
            user_id="u-42",
            solicitud="Sou u-42. Reserve MAD-LIM em 2026-09-12 por até 1000 EUR.",
            tool_faults=[
                ToolFault(id="C12P-timeout", tool="search_flights", tipo="timeout", n_chamada=None)
            ],
            expectativa=Expectativa(
                estado_final=[tabela("R10", "bookings", linhas=[])],
                prohibiciones=sem_escrita("R10"),
                hitos=[
                    evento("R10", tipo="tool_call", ferramenta="search_flights"),
                    evento("R10", tipo="injection_applied", id="C12P-timeout"),
                    evento("R10", tipo="tool_call", ferramenta="search_flights"),
                ],
                limites=[
                    {
                        "patron": {"tipo": "tool_call", "ferramenta": "search_flights"},
                        "maximo": 2,
                        "regra_origem": origem("R10"),
                    }
                ],
                mensaje_debe=[mensagem("R10", r"erro|timeout|falha|indispon|não")],
            ),
            regra_origem=["R10"],
        ),
        Caso(
            id="C13",
            nome="reservar, listar e cancelar",
            user_id="u-55",
            tetos={"flight": 900},
            solicitud="Sou u-55. Reserve LIM-MAD em 2026-09-20 até 900 EUR. Depois liste minhas "
            "reservas e cancele somente a reserva que você acabou de criar.",
            expectativa=Expectativa(
                estado_final=[
                    tabela(
                        "R6",
                        "bookings",
                        linhas=[{"user_id": "u-55", "item_id": "FL-201", "status": "cancelled"}],
                    ),
                    tabela("R6", "flights", inalterada=True),
                ],
                hitos=[
                    evento("R1", tipo="tool_call", ferramenta="create_booking"),
                    evento("R6", tipo="tool_call", ferramenta="list_bookings"),
                    evento("R6", tipo="tool_call", ferramenta="cancel_booking"),
                ],
            ),
            regra_origem=["R1", "R6"],
        ),
        Caso(
            id="C14",
            nome="proposta sem evidência",
            user_id="u-42",
            tetos={"flight": 1000},
            solicitud="Sou u-42. Reserve MAD-LIM em 2026-09-12 por até 1000 EUR.",
            message_faults=[
                MessageFault(
                    id="C14-evidencia", aresta="pesquisador->verificador", tipo="campo_faltante"
                )
            ],
            expectativa=Expectativa(
                estado_final=[
                    tabela(
                        "R1",
                        "bookings",
                        permitidas=[
                            {"user_id": "u-42", "item_id": "FL-101", "status": "confirmed"}
                        ],
                    )
                ],
                hitos=[
                    evento("R2", tipo="injection_applied", id="C14-evidencia"),
                    evento("R2", tipo="tool_call", agente="verificador", ferramenta="check_item"),
                ],
            ),
            regra_origem=["R1", "R2"],
        ),
    ]
}


def validate_case(caso: Caso) -> None:
    caps = capabilities()
    validate_faults(caso.tool_faults, caso.message_faults)
    if set(caso.estado_inicial or {}) - set(caps["estado_inicial"]):
        raise ValueError("estado inicial sem suporte")
    for item in [
        *caso.expectativa.hitos,
        *caso.expectativa.prohibiciones,
        *caso.expectativa.limites,
    ]:
        patron = item["patron"]
        if "tipo" in patron and patron["tipo"] not in caps["eventos"]:
            raise ValueError(f"evento sem suporte: {patron['tipo']}")
        if "ferramenta" in patron and patron["ferramenta"] not in caps["ferramentas"]:
            raise ValueError(f"ferramenta sem suporte: {patron['ferramenta']}")
