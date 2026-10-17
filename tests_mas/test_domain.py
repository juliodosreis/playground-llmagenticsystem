"""Integridade de reservas e assentos, inclusive com estado inicial e falhas de escrita."""

import json
import sqlite3

import pytest

from travel_mas.domain import TravelDB, operations
from travel_mas.evaluation.casos import booking


def reservar(db):
    return json.loads(
        operations.create_booking(
            db, user_id="u-42", kind="flight", item_id="FL-101",
            start_date="2026-09-12", price=980,
        )
    )


@pytest.mark.parametrize(
    "ids,esperado",
    [
        (["BK-0002"], "BK-0003"),
        (["BK-9999", "BK-10000"], "BK-10001"),
        (["importada", "BK-0007", "BK-9000x"], "BK-0008"),
    ],
)
def test_reserva_usa_maior_sufixo_numerico_sem_colidir_com_estado_inicial(ids, esperado):
    with TravelDB({"bookings": [{**booking(), "id": id_} for id_ in ids]}) as db:
        antes = db.snapshot()
        resultado = reservar(db)
        assert resultado["booking_id"] == esperado
        assert len(db.snapshot()["bookings"]) == len(ids) + 1
        assert db.query_one("SELECT seats FROM flights WHERE id='FL-101'")["seats"] == (
            antes["flights"][0]["seats"] - 1
        )


def test_falha_na_insercao_nao_desconta_assento_e_permite_reserva_seguinte():
    with TravelDB() as db:
        db.execute(
            "CREATE TRIGGER falhar_reserva BEFORE INSERT ON bookings "
            "BEGIN SELECT RAISE(ABORT, 'falha de teste'); END"
        )
        antes = db.snapshot()
        with pytest.raises(sqlite3.IntegrityError, match="falha de teste"):
            reservar(db)
        assert db.snapshot() == antes
        db.execute("DROP TRIGGER falhar_reserva")
        assert reservar(db)["booking_id"] == "BK-0001"
        assert db.query_one("SELECT seats FROM flights WHERE id='FL-101'")["seats"] == 3


@pytest.mark.parametrize("kind,item,price", [("flight", "FL-101", 980), ("hotel", "HT-2", 45)])
def test_segunda_cancelacao_retorna_estado_sem_alterar_banco(kind, item, price):
    with TravelDB() as db:
        operations.create_booking(
            db, user_id="u-42", kind=kind, item_id=item, start_date="2026-09-12", price=price
        )
        primeira = json.loads(operations.cancel_booking(db, "BK-0001"))
        antes = db.snapshot()
        segunda = json.loads(operations.cancel_booking(db, "BK-0001"))
        assert primeira == {"booking_id": "BK-0001", "status": "cancelled"}
        assert segunda == {**primeira, "ja_cancelada": True}
        assert db.snapshot() == antes


def test_falha_ao_devolver_assento_nao_confirma_cancelamento_parcial():
    with TravelDB() as db:
        reservar(db)
        db.execute(
            "CREATE TRIGGER falhar_assento BEFORE UPDATE ON flights "
            "BEGIN SELECT RAISE(ABORT, 'falha de teste'); END"
        )
        antes = db.snapshot()
        with pytest.raises(sqlite3.IntegrityError, match="falha de teste"):
            operations.cancel_booking(db, "BK-0001")
        assert db.snapshot() == antes


def test_transacao_externa_desfaz_reserva_com_transacao_interna():
    with TravelDB() as db:
        antes = db.snapshot()
        with pytest.raises(RuntimeError, match="cancelar grupo"):
            with db.transaction():
                reservar(db)
                raise RuntimeError("cancelar grupo")
        assert db.snapshot() == antes
        assert reservar(db)["booking_id"] == "BK-0001"
