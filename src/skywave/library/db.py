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
    """
    CREATE TABLE IF NOT EXISTS play_history (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL,
        played_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS upcoming_queue (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS excluded_artists (
        artist TEXT PRIMARY KEY
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


def clear_now_playing(conn: sqlite3.Connection) -> None:
    """La radio dejó de sonar: mejor ninguna fila que una fila vieja
    mintiendo qué suena."""
    conn.execute("DELETE FROM now_playing")


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


def record_play_history(
    conn: sqlite3.Connection, track: Track, played_at: datetime | None = None
) -> None:
    """Registra que este track empezó a sonar. Deliberadamente **no se
    poda**: sirve de log para debuguear repeticiones. No hace commit,
    mismo criterio que `upsert_track`."""
    if played_at is None:
        played_at = datetime.now(UTC)
    conn.execute(
        "INSERT INTO play_history (path, played_at) VALUES (?, ?)",
        (str(track.path), played_at.isoformat()),
    )


def enqueue_track(conn: sqlite3.Connection, track: Track) -> None:
    """Agrega un tema al final de la cola planificada (issue #40). No
    hace commit, mismo criterio que el resto del módulo."""
    conn.execute("INSERT INTO upcoming_queue (path) VALUES (?)", (str(track.path),))


def dequeue_next(conn: sqlite3.Connection) -> Track | None:
    """Saca y devuelve el primer tema de la cola planificada (FIFO), o
    `None` si está vacía. No hace commit -- quien llama decide el
    alcance de la transacción, igual que el resto del módulo."""
    row = conn.execute(
        """
        SELECT q.id, t.path, t.artist, t.title, t.album, t.year, t.duration_seconds
        FROM upcoming_queue q JOIN tracks t ON t.path = q.path
        ORDER BY q.id ASC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM upcoming_queue WHERE id = ?", (row["id"],))
    return _track_from_row(row)


def peek_queue(conn: sqlite3.Connection, limit: int = 5) -> list[Track]:
    """Los próximos `limit` temas planificados, sin sacarlos de la cola
    -- lo que lee `GET /queue` para mostrar "a continuación" (issue
    #40): el primer ítem es garantizado ser el próximo tema real."""
    rows = conn.execute(
        """
        SELECT t.path, t.artist, t.title, t.album, t.year, t.duration_seconds
        FROM upcoming_queue q JOIN tracks t ON t.path = q.path
        ORDER BY q.id ASC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_track_from_row(row) for row in rows]


def clear_upcoming_queue(conn: sqlite3.Connection) -> None:
    """Vacía la cola planificada -- se llama al arrancar y al cortar
    `skywave play`, mismo criterio que `clear_now_playing`: mejor
    ninguna fila que un plan viejo de una corrida anterior."""
    conn.execute("DELETE FROM upcoming_queue")


def exclude_artist(conn: sqlite3.Connection, artist: str) -> None:
    """Marca un artista como excluido de la rotación (issue #41). No
    toca la biblioteca (`tracks`): `skywave list`/`scan` lo siguen
    mostrando, solo `skywave play` lo salta. `INSERT OR IGNORE` porque
    excluir dos veces al mismo artista no es un error, es un no-op."""
    conn.execute("INSERT OR IGNORE INTO excluded_artists (artist) VALUES (?)", (artist,))


def include_artist(conn: sqlite3.Connection, artist: str) -> None:
    """Saca a un artista de la lista de excluidos. No falla si no
    estaba excluido -- mismo espíritu no-op que `exclude_artist`."""
    conn.execute("DELETE FROM excluded_artists WHERE artist = ?", (artist,))


def excluded_artists(conn: sqlite3.Connection) -> set[str]:
    """Nombres de artista excluidos, para filtrar el catálogo en
    `cli.py` antes de pasarlo a `pick_next`/`plan_queue`."""
    rows = conn.execute("SELECT artist FROM excluded_artists").fetchall()
    return {row["artist"] for row in rows}
