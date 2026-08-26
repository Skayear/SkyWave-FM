import sqlite3
from datetime import UTC, datetime
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

    assert [row["name"] for row in tables] == ["tracks", "now_playing"]


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


def test_now_playing_roundtrip(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")
    track = _track()
    started = datetime(2026, 8, 26, 15, 0, 0, tzinfo=UTC)

    with conn:
        db.upsert_track(conn, track)
        db.set_now_playing(conn, track, started_at=started)

    now = db.get_now_playing(conn)

    assert now is not None
    assert now.track == track
    assert now.started_at == started


def test_set_now_playing_overwrites_previous_state(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")
    first = _track()
    second = _track(path=Path("/music/b/02 - y.flac"), title="Otro tema")

    with conn:
        db.upsert_track(conn, first)
        db.upsert_track(conn, second)
        db.set_now_playing(conn, first)
        db.set_now_playing(conn, second)

    rows = conn.execute("SELECT COUNT(*) AS n FROM now_playing").fetchone()
    now = db.get_now_playing(conn)

    assert rows["n"] == 1
    assert now is not None
    assert now.track == second


def test_get_now_playing_when_nothing_playing_is_none(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")

    assert db.get_now_playing(conn) is None


def test_set_now_playing_defaults_to_current_utc_time(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "library.db")
    track = _track()

    before = datetime.now(UTC)
    with conn:
        db.upsert_track(conn, track)
        db.set_now_playing(conn, track)
    after = datetime.now(UTC)

    now = db.get_now_playing(conn)

    assert now is not None
    assert before <= now.started_at <= after
