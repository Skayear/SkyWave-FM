from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from skywave.library import db
from skywave.library.track import Track
from skywave.web.app import app, get_db_path, get_poll_interval

QUEEN = Track(
    path=Path("/music/Queen - Sheer Heart Attack/01 - Brighton Rock.flac"),
    artist="Queen",
    title="Brighton Rock",
    album="Sheer Heart Attack",
    year=1974,
    duration_seconds=311.2,
)

BOWIE = Track(
    path=Path("/music/Bowie - Hunky Dory/01 - Changes.flac"),
    artist="David Bowie",
    title="Changes",
    album="Hunky Dory",
    year=1971,
    duration_seconds=222.0,
)

ACDC = Track(
    path=Path("/music/AC-DC - Back In Black/01 - Hells Bells.flac"),
    artist="AC/DC",
    title="Hells Bells",
    album="Back In Black",
    year=1980,
    duration_seconds=312.0,
)


def _client(db_path: Path, poll_interval: float = 0.05) -> TestClient:
    """Cliente de pruebas con las dependencias overrideadas -- así cada
    test apunta a su propio `tmp_path` en vez de tocar `skywave.db` de
    verdad, y `/ws` no hace esperar segundos reales entre polls."""
    app.dependency_overrides[get_db_path] = lambda: db_path
    app.dependency_overrides[get_poll_interval] = lambda: poll_interval
    return TestClient(app)


def test_index_sirve_html_con_el_reproductor(tmp_path: Path) -> None:
    response = _client(tmp_path / "library.db").get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<audio" in response.text
    assert "/ws" in response.text  # el JS se conecta acá para el "sonando ahora"
    assert "saludo-form" in response.text  # el textbox de saludos (#31)
    assert "queue-list" in response.text  # "a continuación" (#38, #40)


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


def test_queue_sin_nada_planificado_es_vacio(tmp_path: Path) -> None:
    # skywave play no está corriendo (o no llenó la cola todavía): la
    # web no simula nada, solo lee lo que hay -- issue #40.
    response = _client(tmp_path / "library.db").get("/queue")

    assert response.status_code == 200
    assert response.json() == {"upcoming": []}


def test_queue_devuelve_lo_que_skywave_play_encolo(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = db.connect(db_path)
    with conn:
        for track in (QUEEN, BOWIE, ACDC):
            db.upsert_track(conn, track)
        db.enqueue_track(conn, BOWIE)
        db.enqueue_track(conn, ACDC)

    response = _client(db_path).get("/queue")

    assert response.status_code == 200
    upcoming = response.json()["upcoming"]
    # Orden garantizado (FIFO), no un pool al azar: el primer ítem es el
    # próximo tema real, no una aproximación.
    assert [t["title"] for t in upcoming] == ["Changes", "Hells Bells"]


def test_queue_no_saca_temas_al_leerla(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = db.connect(db_path)
    with conn:
        db.upsert_track(conn, QUEEN)
        db.enqueue_track(conn, QUEEN)

    client = _client(db_path)
    first = client.get("/queue").json()
    second = client.get("/queue").json()

    assert first == second
    assert [t["title"] for t in first["upcoming"]] == ["Brighton Rock"]


def test_ws_primer_mensaje_es_null_si_no_suena_nada(tmp_path: Path) -> None:
    client = _client(tmp_path / "library.db")

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() is None


def test_ws_primer_mensaje_es_el_tema_sonando(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = db.connect(db_path)
    with conn:
        db.upsert_track(conn, QUEEN)
        db.set_now_playing(conn, QUEEN, started_at=datetime(2026, 8, 28, 15, 0, 0, tzinfo=UTC))

    with _client(db_path).websocket_connect("/ws") as ws:
        data = ws.receive_json()

    assert data["track"]["title"] == "Brighton Rock"


def test_ws_empuja_actualizacion_cuando_cambia_el_tema(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = db.connect(db_path)
    with conn:
        db.upsert_track(conn, QUEEN)
        db.upsert_track(conn, BOWIE)
        db.set_now_playing(conn, QUEEN, started_at=datetime(2026, 8, 28, 15, 0, 0, tzinfo=UTC))

    with _client(db_path).websocket_connect("/ws") as ws:
        primero = ws.receive_json()
        assert primero["track"]["title"] == "Brighton Rock"

        with conn:
            db.set_now_playing(conn, BOWIE, started_at=datetime(2026, 8, 28, 15, 3, 0, tzinfo=UTC))

        segundo = ws.receive_json()
        assert segundo["track"]["title"] == "Changes"
