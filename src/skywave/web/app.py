import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from skywave.library import db
from skywave.web import greetings

#: Mismo default que la CLI (`skywave scan`/`skywave play`): el SQLite de
#: la biblioteca en el cwd -- no hay config.toml todavía.
DEFAULT_DB_PATH = Path("skywave.db")

app = FastAPI(title="SkyWave FM")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class TrackOut(BaseModel):
    artist: str
    title: str
    album: str | None
    year: int | None


class NowPlayingOut(BaseModel):
    track: TrackOut
    started_at: datetime


class GreetingIn(BaseModel):
    message: str = Field(min_length=1, max_length=200)

    @field_validator("message")
    @classmethod
    def _no_solo_espacios(cls, value: str) -> str:
        # Field(min_length=1) ya rechaza "" pero no " " -- el validator
        # limpia los espacios antes de decidir si está vacío de verdad.
        stripped = value.strip()
        if not stripped:
            raise ValueError("el mensaje no puede estar vacío")
        return stripped


def get_stream_url() -> str:
    """URL pública del mount de Icecast, con los mismos defaults que
    `cli._icecast_url` (host/puerto por variables de entorno) -- pero acá
    sin password: es la URL que escucha un navegador, no la del source
    que empuja el mixer."""
    host = os.environ.get("ICECAST_SERVER_HOST", "localhost")
    port = os.environ.get("ICECAST_SOURCE_PORT", "8010")
    return f"http://{host}:{port}/sky.mp3"


def get_db_path() -> Path:
    """Dependencia inyectable (no una constante importada a mano): los
    tests la overridean con `app.dependency_overrides` para apuntar a una
    base temporal en vez de tocar `skywave.db` de verdad -- mismo espíritu
    que el `Callable` inyectado de `VoiceCache`, aplicado a la manera de
    FastAPI."""
    return DEFAULT_DB_PATH


def get_poll_interval() -> float:
    """Cada cuántos segundos `/ws` revisa `now_playing` para decidir si
    hay que empujar una actualización. Inyectable para que los tests no
    tengan que esperar segundos reales -- mismo motivo que `get_db_path`."""
    return 2.0


def _now_playing_payload(db_path: Path) -> NowPlayingOut | None:
    """Lectura compartida entre `GET /now-playing` y `GET /ws`: un solo
    lugar que sabe mapear `db.NowPlaying` a la forma que sale por la
    API, para no mantener dos copias de la misma lógica."""
    conn = db.connect(db_path)
    current = db.get_now_playing(conn)
    if current is None:
        return None
    return NowPlayingOut(
        track=TrackOut(
            artist=current.track.artist,
            title=current.track.title,
            album=current.track.album,
            year=current.track.year,
        ),
        started_at=current.started_at,
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, stream_url: str = Depends(get_stream_url)) -> HTMLResponse:
    """Página con el reproductor. El "sonando ahora" no se rellena acá
    server-side -- se pide async a `/now-playing` desde JS (ver
    templates/index.html) para poder refrescarlo sin recargar la
    página."""
    return templates.TemplateResponse(request, "index.html", {"stream_url": stream_url})


@app.post("/greetings", status_code=201)
def post_greeting(
    greeting: GreetingIn, request: Request, db_path: Path = Depends(get_db_path)
) -> dict[str, str]:
    """Guarda un saludo si pasa moderación y rate limit. 422 si tiene
    una palabra prohibida, 429 si el identificador (la IP -- no hay
    login, es lo único que tenemos) mandó demasiados saludos seguidos.
    Rechazar temprano en vez de guardar basura, mismo criterio que
    `_mentions_track` en el locutor."""
    if not greetings.is_appropriate(greeting.message):
        raise HTTPException(status_code=422, detail="mensaje no permitido")

    identifier = request.client.host if request.client else "desconocido"
    conn = db.connect(db_path)
    greetings.ensure_schema(conn)
    # insert_greeting guarda en UTC-aware, hay que comparar en el mismo huso
    now = datetime.now(UTC)
    if not greetings.is_within_rate_limit(greetings.recent_sends(conn, identifier), now=now):
        raise HTTPException(status_code=429, detail="demasiados saludos, esperá un poco")

    with conn:
        greetings.insert_greeting(conn, greeting.message, identifier, created_at=now)
    return {"status": "ok"}


@app.get("/now-playing")
def now_playing(db_path: Path = Depends(get_db_path)) -> NowPlayingOut | None:
    """Qué está sonando ahora mismo, o `null` si la radio está apagada (o
    la biblioteca todavía está vacía) -- nunca un 500 por no tener nada
    que mostrar, mismo principio del resto del proyecto."""
    return _now_playing_payload(db_path)


@app.websocket("/ws")
async def now_playing_ws(
    websocket: WebSocket,
    db_path: Path = Depends(get_db_path),
    poll_interval: float = Depends(get_poll_interval),
) -> None:
    """Empuja el "sonando ahora" apenas cambia, para que la página no
    tenga que hacer polling HTTP por su cuenta. SQLite no tiene pub/sub
    nativo -- este loop hace el polling del lado del servidor sobre
    `now_playing`, un solo lugar leyendo la base cada `poll_interval`
    en vez de una consulta HTTP por cada pestaña abierta."""
    await websocket.accept()
    last_sent: NowPlayingOut | None | object = object()  # nunca == al primer payload real
    try:
        while True:
            payload = _now_playing_payload(db_path)
            if payload != last_sent:
                await websocket.send_json(payload.model_dump(mode="json") if payload else None)
                last_sent = payload
            await asyncio.sleep(poll_interval)
    except WebSocketDisconnect:
        pass
