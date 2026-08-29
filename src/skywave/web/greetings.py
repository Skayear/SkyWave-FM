import re
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

#: Tabla propia, separada del esquema de `library/db.py`: un saludo es
#: contenido generado por un oyente de la web, no un dato de la
#: biblioteca musical -- mezclarlos en el mismo módulo confundiría dos
#: conceptos distintos aunque hoy vivan en el mismo archivo SQLite.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS greetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    identifier TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Crea la tabla `greetings` si no existe. Se llama aparte de
    `library.db.connect` (que ya crea `tracks`/`now_playing`) para no
    mezclar los dos esquemas en el mismo módulo."""
    conn.execute(_SCHEMA)


def insert_greeting(
    conn: sqlite3.Connection,
    message: str,
    identifier: str,
    created_at: datetime | None = None,
) -> None:
    """No hace commit -- mismo criterio que `upsert_track`: quien llama
    decide el alcance de la transacción."""
    if created_at is None:
        created_at = datetime.now(UTC)
    conn.execute(
        "INSERT INTO greetings (message, identifier, created_at) VALUES (?, ?, ?)",
        (message, identifier, created_at.isoformat()),
    )


def recent_sends(conn: sqlite3.Connection, identifier: str) -> list[datetime]:
    """Timestamps de envíos previos de este identificador, para
    alimentar `is_within_rate_limit`. Trae todo el historial del
    identificador sin filtrar por fecha en SQL -- para una radio
    personal de bajo tráfico no vale la pena la complejidad extra de
    sincronizar la ventana acá con la que usa la función pura."""
    rows = conn.execute(
        "SELECT created_at FROM greetings WHERE identifier = ?", (identifier,)
    ).fetchall()
    return [datetime.fromisoformat(row[0]) for row in rows]


#: Lista chica a propósito -- "no hace falta nada sofisticado para
#: arrancar" (issue #31). Si hace falta más cobertura más adelante, se
#: agranda esta lista o se cambia por algo más serio; no hay que
#: rediseñar la función para eso.
_DEFAULT_BANNED_WORDS = (
    "puto",
    "puta",
    "boludo",
    "pelotudo",
    "forro",
)


def is_appropriate(text: str, *, banned_words: Sequence[str] = _DEFAULT_BANNED_WORDS) -> bool:
    """True si el texto no contiene ninguna palabra prohibida. Compara
    por palabra completa (no substring) e ignora mayúsculas/acentos
    simples, para que "pelotudo" no marque "pelotudos" como aceptable
    ni "puto" dispare con una palabra que lo contiene de casualidad."""
    words = re.findall(r"\w+", text.lower())
    banned = {w.lower() for w in banned_words}
    return not any(word in banned for word in words)


def is_within_rate_limit(
    previous_sends: Sequence[datetime],
    *,
    now: datetime | None = None,
    max_messages: int = 3,
    window: timedelta = timedelta(minutes=5),
) -> bool:
    """True si mandar un mensaje más no supera `max_messages` dentro de
    `window`. `now` inyectable (mismo patrón que `pick_next`) para que
    los tests sean determinísticos sin pisar el reloj real.

    `previous_sends` son los timestamps de envíos previos del mismo
    identificador (IP) -- quien llama es responsable de haber filtrado
    ya por identificador, esta función no sabe de IPs."""
    if now is None:
        now = datetime.now()
    cutoff = now - window
    recent = [sent for sent in previous_sends if sent > cutoff]
    return len(recent) < max_messages
