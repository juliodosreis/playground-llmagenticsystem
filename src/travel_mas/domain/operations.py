"""Operações do domínio: as regras de reserva, sem dependência do LangChain.

Cada operação recebe o banco como primeiro argumento e devolve uma string JSON. As ferramentas em
`tools/` fixam o banco da execução e gravam a chamada no trace.

O erro de execução sai como dado (`{"error": ...}`), e não como exceção: `create_booking` devolve
`flight_not_found`, `no_seats_available`, `hotel_not_found` ou `invalid_kind`, e o banco fica
inalterado.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .database import TravelDB

Operation = Callable[..., str]


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- catálogo (leitura)


def search_flights(
    db: TravelDB,
    origin: str,
    destination: str,
    date: str,
    max_price: float = 1e9,
) -> str:
    """Busca voos por origem, destino, data e teto de preço."""
    rows = db.query(
        "SELECT * FROM flights WHERE origin=? AND destination=? AND date=? AND price<=? "
        "ORDER BY price",
        (origin, destination, date, max_price),
    )
    return _dump(rows)


def search_hotels(db: TravelDB, city: str, max_price_per_night: float = 1e9) -> str:
    """Busca hotéis de uma cidade abaixo de um preço por noite."""
    rows = db.query(
        "SELECT * FROM hotels WHERE city=? AND price_per_night<=? ORDER BY price_per_night",
        (city, max_price_per_night),
    )
    return _dump(rows)


# ------------------------------------------------------------------------- estado (escrita)


def create_booking(
    db: TravelDB,
    user_id: str,
    kind: str,
    item_id: str,
    start_date: str,
    price: float,
) -> str:
    """Insere uma reserva e, no caso de voo, decrementa `flights.seats`.

    Uma reserva de voo altera duas tabelas: a linha nova em `bookings` e o assento em
    `flights.seats`.
    """
    with db.lock:
        if kind == "flight":
            row = db.query_one("SELECT * FROM flights WHERE id=?", (item_id,))
            if row is None:
                return _dump({"error": "flight_not_found", "item_id": item_id})
            if row["seats"] <= 0:
                return _dump({"error": "no_seats_available", "item_id": item_id})
            db.execute("UPDATE flights SET seats = seats - 1 WHERE id=?", (item_id,))
        elif kind == "hotel":
            if db.query_one("SELECT 1 FROM hotels WHERE id=?", (item_id,)) is None:
                return _dump({"error": "hotel_not_found", "item_id": item_id})
        else:
            return _dump({"error": "invalid_kind", "kind": kind})

        total = db.query_one("SELECT COUNT(*) AS c FROM bookings")["c"]
        booking_id = f"BK-{total + 1:04d}"
        db.execute(
            "INSERT INTO bookings VALUES (?,?,?,?,?,?,?)",
            (booking_id, user_id, kind, item_id, start_date, price, "confirmed"),
        )
    return _dump({"booking_id": booking_id, "status": "confirmed"})


def get_booking(db: TravelDB, booking_id: str) -> str:
    """Lê uma reserva pelo id."""
    row = db.query_one("SELECT * FROM bookings WHERE id=?", (booking_id,))
    return _dump(row if row else {"error": "not_found", "booking_id": booking_id})


def list_bookings(db: TravelDB, user_id: str) -> str:
    """Lista as reservas de um usuário."""
    return _dump(db.query("SELECT * FROM bookings WHERE user_id=? ORDER BY id", (user_id,)))


def cancel_booking(db: TravelDB, booking_id: str) -> str:
    """Marca a reserva como `cancelled` e devolve o assento quando é voo."""
    with db.lock:
        row = db.query_one("SELECT * FROM bookings WHERE id=?", (booking_id,))
        if row is None:
            return _dump({"error": "not_found", "booking_id": booking_id})
        db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        if row["kind"] == "flight":
            db.execute("UPDATE flights SET seats = seats + 1 WHERE id=?", (row["item_id"],))
    return _dump({"booking_id": booking_id, "status": "cancelled"})


# Registro nome -> operação, para chamar uma operação pelo nome que aparece no trace.
OPERATIONS: dict[str, Operation] = {
    op.__name__: op
    for op in (
        search_flights,
        search_hotels,
        create_booking,
        get_booking,
        list_bookings,
        cancel_booking,
    )
}
