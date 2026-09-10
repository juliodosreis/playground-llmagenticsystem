"""Catálogo do ambiente: esquema SQL e linhas semeadas em cada execução.

As tabelas `flights` e `hotels` são de leitura. O estado mutável são as reservas em `bookings` e a
coluna `flights.seats`, decrementada a cada reserva de voo.

`MUTABLE_TABLES` define quais tabelas entram no snapshot, no hash e no diff do estado.
"""

from __future__ import annotations

from typing import NamedTuple

SCHEMA = """
CREATE TABLE flights (
    id TEXT PRIMARY KEY, origin TEXT, destination TEXT, date TEXT,
    price REAL, airline TEXT, seats INTEGER
);
CREATE TABLE hotels (
    id TEXT PRIMARY KEY, city TEXT, name TEXT, stars INTEGER, price_per_night REAL
);
CREATE TABLE bookings (
    id TEXT PRIMARY KEY, user_id TEXT, kind TEXT, item_id TEXT,
    start_date TEXT, price REAL, status TEXT
);
"""


class Flight(NamedTuple):
    id: str
    origin: str
    destination: str
    date: str
    price: float
    airline: str
    seats: int


class Hotel(NamedTuple):
    id: str
    city: str
    name: str
    stars: int
    price_per_night: float


FLIGHTS: tuple[Flight, ...] = (
    Flight("FL-101", "MAD", "LIM", "2026-09-12", 980.0, "Iberia", 4),
    Flight("FL-102", "MAD", "LIM", "2026-09-12", 1240.0, "LATAM", 9),
    Flight("FL-103", "MAD", "LIM", "2026-09-13", 760.0, "Air France", 2),
    Flight("FL-201", "LIM", "MAD", "2026-09-20", 890.0, "Iberia", 6),
)

HOTELS: tuple[Hotel, ...] = (
    Hotel("HT-1", "LIM", "Miraflores Suites", 4, 120.0),
    Hotel("HT-2", "LIM", "Barranco Hostal", 2, 45.0),
    Hotel("HT-3", "LIM", "Surco Business", 3, 58.0),
)

# Tabelas que o agente pode modificar, e portanto as que compõem o estado observado.
MUTABLE_TABLES: tuple[str, ...] = ("bookings", "flights")

# Ids que existem de fato. Um item_id fora deste conjunto é invenção do modelo.
CATALOG_IDS: frozenset[str] = frozenset(f.id for f in FLIGHTS) | frozenset(h.id for h in HOTELS)
