import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from skywave.web.greetings import (
    ensure_schema,
    insert_greeting,
    is_appropriate,
    is_within_rate_limit,
    recent_sends,
)


def test_is_appropriate_con_texto_limpio() -> None:
    assert is_appropriate("Hola, saludos desde Rosario!")


def test_is_appropriate_rechaza_palabra_prohibida() -> None:
    assert not is_appropriate("sos un boludo")


def test_is_appropriate_no_rechaza_por_substring() -> None:
    # "pelotudos" contiene "pelotudo" como substring, pero es otra palabra
    assert is_appropriate("los pelotudos no somos nosotros")


def test_is_appropriate_ignora_mayusculas() -> None:
    assert not is_appropriate("PUTO el que lee")


def test_is_within_rate_limit_bajo_el_limite() -> None:
    now = datetime(2026, 8, 29, 12, 0, 0)
    previous = [now - timedelta(minutes=1)]

    assert is_within_rate_limit(previous, now=now, max_messages=3)


def test_is_within_rate_limit_en_el_limite_lo_bloquea() -> None:
    now = datetime(2026, 8, 29, 12, 0, 0)
    previous = [
        now - timedelta(minutes=1),
        now - timedelta(minutes=2),
        now - timedelta(minutes=3),
    ]

    assert not is_within_rate_limit(previous, now=now, max_messages=3)


def test_is_within_rate_limit_ignora_envios_fuera_de_la_ventana() -> None:
    now = datetime(2026, 8, 29, 12, 0, 0)
    previous = [now - timedelta(minutes=10), now - timedelta(minutes=8)]

    assert is_within_rate_limit(previous, now=now, max_messages=1, window=timedelta(minutes=5))


def test_is_within_rate_limit_sin_envios_previos() -> None:
    assert is_within_rate_limit([], max_messages=1)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "greetings.db")
    ensure_schema(conn)
    return conn


def test_insert_y_recent_sends(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    sent_at = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
    with conn:
        insert_greeting(conn, "hola!", identifier="1.2.3.4", created_at=sent_at)

    assert recent_sends(conn, "1.2.3.4") == [sent_at]


def test_recent_sends_no_mezcla_identificadores(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    with conn:
        insert_greeting(conn, "hola!", identifier="1.2.3.4")

    assert recent_sends(conn, "9.9.9.9") == []


def test_ensure_schema_es_idempotente(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    ensure_schema(conn)  # no debe romper si la tabla ya existe

    assert recent_sends(conn, "1.2.3.4") == []
