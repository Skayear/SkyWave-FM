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


def test_index_sirve_html_con_el_reproductor(tmp_path: Path) -> None:
    response = _client(tmp_path / "library.db").get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<audio" in response.text
    assert "/now-playing" in response.text  # el JS consulta este endpoint
    assert "saludo-form" in response.text  # el textbox de saludos (#31)


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


def test_post_greeting_lo_guarda(tmp_path: Path) -> None:
    response = _client(tmp_path / "library.db").post(
        "/greetings", json={"message": "Hola desde Rosario!"}
    )

    assert response.status_code == 201


def test_post_greeting_vacio_es_422(tmp_path: Path) -> None:
    response = _client(tmp_path / "library.db").post("/greetings", json={"message": "   "})

    assert response.status_code == 422


def test_post_greeting_con_palabra_prohibida_es_422(tmp_path: Path) -> None:
    response = _client(tmp_path / "library.db").post(
        "/greetings", json={"message": "sos un boludo"}
    )

    assert response.status_code == 422


def test_post_greeting_respeta_el_rate_limit(tmp_path: Path) -> None:
    client = _client(tmp_path / "library.db")
    for _ in range(3):
        assert client.post("/greetings", json={"message": "hola!"}).status_code == 201

    response = client.post("/greetings", json={"message": "hola de nuevo!"})

    assert response.status_code == 429
