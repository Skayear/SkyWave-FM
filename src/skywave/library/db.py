import sqlite3
from pathlib import Path

from skywave.library.track import Track

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    path TEXT PRIMARY KEY,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    year INTEGER,
    duration_seconds REAL NOT NULL
)
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
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


def list_tracks(conn: sqlite3.Connection) -> list[Track]:
    rows = conn.execute(
        "SELECT path, artist, title, album, year, duration_seconds "
        "FROM tracks ORDER BY artist, album, path"
    ).fetchall()
    return [
        Track(
            path=Path(row["path"]),
            artist=row["artist"],
            title=row["title"],
            album=row["album"],
            year=row["year"],
            duration_seconds=row["duration_seconds"],
        )
        for row in rows
    ]
