import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from skywave.library.track import Track

# El CHECK (id = 1) fuerza a nivel de esquema que now_playing tenga como
# máximo una fila: cualquier INSERT con otro id falla. Guardamos solo el
# path (la identidad del track, igual que en tracks) — el resto sale con
# un JOIN, sin duplicar datos que podrían quedar desactualizados.
_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS tracks (
        path TEXT PRIMARY KEY,
        artist TEXT NOT NULL,
        title TEXT NOT NULL,
        album TEXT,
        year INTEGER,
        duration_seconds REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS now_playing (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        path TEXT NOT NULL,
        started_at TEXT NOT NULL
    )
    """,
]


@dataclass(frozen=True, slots=True)
class NowPlaying:
    track: Track
    started_at: datetime


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for statement in _SCHEMA:
        conn.execute(statement)
    return conn


def upsert_track(conn: sqlite3.Connection, track: Track) -> None:
    """Inserta o actualiza por `path` (la identidad natural de un Track: el
    archivo en disco). No hace commit — quien llama decide el alcance de la
    transacción, por ejemplo envolviendo un escaneo completo en un solo
    `with conn:` para que sea un commit atómico en vez de uno por archivo."""
    conn.execute(
        """
        INSERT INTO tracks (path, artist, title, album, year, duration_seconds)
        VALUES (:path, :artist, :title, :album, :year, :duration_seconds)
        ON CONFLICT(path) DO UPDATE SET
            artist = excluded.artist,
            title = excluded.title,
            album = excluded.album,
            year = excluded.year,
            duration_seconds = excluded.duration_seconds
        """,
        {
            "path": str(track.path),
            "artist": track.artist,
            "title": track.title,
            "album": track.album,
            "year": track.year,
            "duration_seconds": track.duration_seconds,
        },
    )


def _track_from_row(row: sqlite3.Row) -> Track:
    return Track(
        path=Path(row["path"]),
        artist=row["artist"],
        title=row["title"],
        album=row["album"],
        year=row["year"],
        duration_seconds=row["duration_seconds"],
    )


def list_tracks(conn: sqlite3.Connection) -> list[Track]:
    rows = conn.execute(
        "SELECT path, artist, title, album, year, duration_seconds "
        "FROM tracks ORDER BY artist, album, path"
    ).fetchall()
    return [_track_from_row(row) for row in rows]


def set_now_playing(
    conn: sqlite3.Connection, track: Track, started_at: datetime | None = None
) -> None:
    """Registra qué está sonando. `started_at` inyectable para tests;
    en producción se omite y usa el reloj real. SQLite no tiene tipo de
    fecha nativo: se guarda como texto ISO-8601 en UTC, que ordena bien
    lexicográficamente y se parsea con datetime.fromisoformat()."""
    if started_at is None:
        started_at = datetime.now(UTC)
    conn.execute(
        """
        INSERT INTO now_playing (id, path, started_at) VALUES (1, :path, :started_at)
        ON CONFLICT(id) DO UPDATE SET path = excluded.path, started_at = excluded.started_at
        """,
        {"path": str(track.path), "started_at": started_at.isoformat()},
    )


def get_now_playing(conn: sqlite3.Connection) -> NowPlaying | None:
    row = conn.execute(
        """
        SELECT t.path, t.artist, t.title, t.album, t.year, t.duration_seconds,
               n.started_at
        FROM now_playing n JOIN tracks t ON t.path = n.path
        WHERE n.id = 1
        """
    ).fetchone()
    if row is None:
        return None
    return NowPlaying(
        track=_track_from_row(row),
        started_at=datetime.fromisoformat(row["started_at"]),
    )
