from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from skywave.library import db
from skywave.library.track import Track
from skywave.web.app import app, get_db_path

QUEEN = Track(
    path=Path("/music/Queen - Sheer Heart Attack/01 - Brighton Rock.flac"),
    artist="Queen",
    title="Brighton Rock",
    album="Sheer Heart Attack",
    year=1974,
    duration_seconds=311.2,
)


def _client(db_path: Path) -> TestClient:
    """Cliente de pruebas con la dependencia de la base overrideada -- así
    cada test apunta a su propio `tmp_path` en vez de tocar `skywave.db`
    de verdad o pisarse entre tests."""
    app.dependency_overrides[get_db_path] = lambda: db_path
    return TestClient(app)


def test_now_playing_con_biblioteca_vacia_devuelve_null(tmp_path: Path) -> None:
    client = _client(tmp_path / "library.db")

    response = client.get("/now-playing")

    assert response.status_code == 200
    assert response.json() is None


def test_now_playing_con_tema_sonando(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = db.connect(db_path)
    started = datetime(2026, 8, 28, 15, 0, 0, tzinfo=UTC)
    with conn:
        db.upsert_track(conn, QUEEN)
        db.set_now_playing(conn, QUEEN, started_at=started)

    response = _client(db_path).get("/now-playing")

    assert response.status_code == 200
    body = response.json()
    assert body["track"] == {
        "artist": "Queen",
        "title": "Brighton Rock",
        "album": "Sheer Heart Attack",
        "year": 1974,
    }
    assert body["started_at"] == "2026-08-28T15:00:00Z"


def test_now_playing_sin_nada_sonando_devuelve_null(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = db.connect(db_path)
    with conn:
        db.upsert_track(conn, QUEEN)  # biblioteca con temas, pero radio apagada

    response = _client(db_path).get("/now-playing")

    assert response.status_code == 200
    assert response.json() is None
