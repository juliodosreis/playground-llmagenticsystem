"""Banco em memória e serialização canônica do estado.

Cada execução recebe seu próprio `TravelDB`, semeado com o catálogo e sem reservas.

`snapshot()` serializa as tabelas mutáveis em ordem fixa e `state_hash()` fecha o JSON com chaves
ordenadas, então dois estados equivalentes produzem o mesmo hash independentemente da ordem das
escritas.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from typing import Any

from .catalog import FLIGHTS, HOTELS, MUTABLE_TABLES, SCHEMA

# Estado mutável em forma canônica: nome da tabela -> linhas ordenadas por id.
Snapshot = dict[str, list[dict[str, Any]]]


class TravelDB:
    """SQLite em memória com o catálogo semeado e zero reservas.

    As ferramentas do LangChain rodam em um thread pool, então a conexão é criada com
    `check_same_thread=False` e toda escrita passa por um `RLock`.
    """

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.executemany("INSERT INTO flights VALUES (?,?,?,?,?,?,?)", FLIGHTS)
        self._conn.executemany("INSERT INTO hotels  VALUES (?,?,?,?,?)", HOTELS)
        self._conn.commit()

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def snapshot(self) -> Snapshot:
        """Estado mutável em ordem determinística."""
        return {
            table: self.query(f"SELECT * FROM {table} ORDER BY id")  # noqa: S608 - nomes fixos
            for table in MUTABLE_TABLES
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> TravelDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def state_hash(state: Snapshot) -> str:
    """Hash estável de um snapshot: mesmo estado, mesmo hash, qualquer que seja o caminho."""
    payload = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def diff_state(before: Snapshot, after: Snapshot) -> dict[str, dict[str, list]]:
    """O que mudou entre dois snapshots, por tabela.

    Linhas novas em `added`, removidas em `removed`, e alteradas em `changed` com o valor antes e
    depois. Uma tabela sem mudança fica fora do resultado.

    O hash indica se o estado mudou. Este diff indica quais linhas mudaram.
    """
    out: dict[str, dict[str, list]] = {}
    for table in before:
        antes = {row["id"]: row for row in before[table]}
        depois = {row["id"]: row for row in after[table]}
        added = [depois[k] for k in depois if k not in antes]
        removed = [antes[k] for k in antes if k not in depois]
        changed = [
            {"id": k, "antes": antes[k], "depois": depois[k]}
            for k in depois
            if k in antes and antes[k] != depois[k]
        ]
        if added or removed or changed:
            out[table] = {"added": added, "removed": removed, "changed": changed}
    return out
