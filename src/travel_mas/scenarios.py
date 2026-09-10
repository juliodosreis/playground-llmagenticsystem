"""Pedidos de demonstração do agente.

Cada cenário tem um identificador, um nome e o texto do pedido. A CLI os roda em sequência, e um
cenário novo entra nesta lista sem tocar em `cli.py`.
"""

from __future__ import annotations

from typing import NamedTuple


class Scenario(NamedTuple):
    """Um pedido de demonstração."""

    key: str
    name: str
    prompt: str


SCENARIOS: dict[str, Scenario] = {
    scenario.key: scenario
    for scenario in (
        Scenario(
            "1",
            "voo-orcamento",
            "Sou o usuário u-42. Quero voar de Madri (MAD) para Lima (LIM) no dia 2026-09-12, "
            "com um orçamento máximo de 1000 EUR. Reserve para mim.",
        ),
        Scenario(
            "2",
            "voo-e-hotel",
            "Sou o usuário u-77. Preciso do voo Madri (MAD) para Lima (LIM) do dia 2026-09-13 "
            "(no máximo 800 EUR) e também de um hotel em Lima (LIM) que não passe de 60 EUR por "
            "noite, com entrada em 2026-09-13. Reserve as duas coisas.",
        ),
        Scenario(
            "3",
            "sem-disponibilidade",
            "Sou o usuário u-99. Quero voar de Madri (MAD) para Lima (LIM) no dia 2026-09-14. "
            "Orçamento de 2000 EUR. Reserve para mim.",
        ),
        Scenario(
            "4",
            "fora-do-orcamento",
            "Sou o usuário u-12. Quero voar de Madri (MAD) para Lima (LIM) no dia 2026-09-12, "
            "mas não posso gastar mais de 700 EUR. Reserve se couber no orçamento.",
        ),
        Scenario(
            "5",
            "reserva-e-cancelamento",
            "Sou o usuário u-55. Reserve o voo de Lima (LIM) para Madri (MAD) do dia 2026-09-20 "
            "por até 900 EUR. Depois liste as minhas reservas e cancele a que você acabou de "
            "criar.",
        ),
        Scenario(
            "6",
            "consulta-vazia",
            "Sou o usuário u-31. Quais reservas eu tenho no sistema?",
        ),
    )
}
