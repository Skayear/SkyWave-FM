import sqlite3
from pathlib import Path

from skywave.library import db
from skywave.library.track import Track


def _track(**overrides: object) -> Track:
    base = dict(
        path=Path("/music/Queen - Sheer Heart Attack/01 - Brighton Rock.flac"),
        artist="Queen",
        title="Brighton Rock",
        album="Sheer Heart Attack",
        year=1974,
        duration_seconds=311.2,
    )
    return Track(**{**base, **overrides})


def test_connect_creates_schema(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")

    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

    assert [row["name"] for row in tables] == ["tracks"]


def test_connect_twice_on_same_file_does_not_fail(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"

    db.connect(db_path)
    db.connect(db_path)  # CREATE TABLE IF NOT EXISTS: no debe romper


def test_upsert_then_list_roundtrips_the_track(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")
    track = _track()

    with conn:
        db.upsert_track(conn, track)

    assert db.list_tracks(conn) == [track]


def test_upsert_same_path_updates_instead_of_duplicating(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")
    path = Path("/music/a/01 - x.mp3")
    original = _track(path=path, title="Título viejo", year=None)
    rescanned = _track(path=path, title="Título nuevo", year=2020)

    with conn:
        db.upsert_track(conn, original)
    with conn:
        db.upsert_track(conn, rescanned)

    tracks = db.list_tracks(conn)

    assert len(tracks) == 1
    assert tracks[0].title == "Título nuevo"
    assert tracks[0].year == 2020


def test_upsert_without_commit_is_not_visible_on_a_fresh_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = db.connect(db_path)

    db.upsert_track(conn, _track())  # sin `with conn:` -> no commitea

    other_conn = sqlite3.connect(db_path)
    other_conn.row_factory = sqlite3.Row
    assert db.list_tracks(other_conn) == []


def test_list_tracks_on_empty_db_is_empty_list(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")

    assert db.list_tracks(conn) == []
