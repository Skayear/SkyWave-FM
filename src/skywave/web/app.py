import asyncio
import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from skywave.library import db
from skywave.web import greetings

#: Cuántos temas adelante muestra GET /queue -- tope de lectura sobre
#: la cola real que mantiene `skywave play` (issue #40), no un límite
#: de cuántos hay planificados.
_QUEUE_SIZE = 5

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


class QueueOut(BaseModel):
    upcoming: list[TrackOut]


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


class ArtistIn(BaseModel):
    artist: str = Field(min_length=1, max_length=200)

    @field_validator("artist")
    @classmethod
    def _no_solo_espacios(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("el artista no puede estar vacío")
        return stripped


class ArtistStatusOut(BaseModel):
    name: str
    excluded: bool
    track_count: int


class ArtistsOut(BaseModel):
    artists: list[ArtistStatusOut]


def get_stream_url() -> str:
    """URL pública del mount de Icecast -- sin password: es la URL que
    escucha un navegador, no la del source que empuja el mixer.

    `ICECAST_PUBLIC_HOST`/`ICECAST_PUBLIC_PORT` son opcionales, pensadas
    para Docker (issue #39): ahí `skywave play` y este server viven en
    el mismo contenedor y comparten entorno, pero necesitan hablarle a
    Icecast por caminos distintos -- el mixer empuja por la red interna
    de compose (`ICECAST_SERVER_HOST=icecast`, puerto del contenedor),
    mientras que esta URL la abre un navegador de afuera (la IP/puerto
    público). Sin Docker, ninguna de las dos está seteada y todo cae a
    `ICECAST_SERVER_HOST`/`ICECAST_SOURCE_PORT` como siempre."""
    host = os.environ.get("ICECAST_PUBLIC_HOST") or os.environ.get(
        "ICECAST_SERVER_HOST", "localhost"
    )
    port = os.environ.get("ICECAST_PUBLIC_PORT") or os.environ.get("ICECAST_SOURCE_PORT", "8010")
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


@app.get("/queue")
def queue(db_path: Path = Depends(get_db_path)) -> QueueOut:
    """Los próximos temas que `skywave play` ya planificó (issue #40) --
    lee `upcoming_queue` directo, no simula nada: el primer ítem es
    garantizado ser el próximo tema real (si `skywave play` está
    corriendo y mantuvo la cola llena; si no, vacío -- ver #38 para el
    enfoque anterior por simulación, que este issue reemplazó)."""
    conn = db.connect(db_path)
    upcoming = db.peek_queue(conn, limit=_QUEUE_SIZE)
    return QueueOut(
        upcoming=[
            TrackOut(artist=t.artist, title=t.title, album=t.album, year=t.year) for t in upcoming
        ]
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


@app.get("/artists")
def get_artists(db_path: Path = Depends(get_db_path)) -> ArtistsOut:
    """Todos los artistas de la biblioteca, marcando cuáles están
    excluidos de la rotación (issue #41) -- la web arma un checkbox por
    artista con esto, en vez de un textbox de nombre libre que puede
    tener un typo y no coincidir con nada."""
    conn = db.connect(db_path)
    excluded = db.excluded_artists(conn)
    return ArtistsOut(
        artists=[
            ArtistStatusOut(
                name=artist.name, excluded=artist.name in excluded, track_count=artist.track_count
            )
            for artist in db.list_artists(conn)
        ]
    )


@app.post("/exclude-artist", status_code=201)
def post_exclude_artist(body: ArtistIn, db_path: Path = Depends(get_db_path)) -> dict[str, str]:
    """Espejo web de `skywave exclude`: no toca la biblioteca, `skywave
    play` recién lo ve en su próximo arranque (el catálogo se carga una
    sola vez al inicio, no en vivo)."""
    conn = db.connect(db_path)
    with conn:
        db.exclude_artist(conn, body.artist)
    return {"status": "ok"}


@app.post("/include-artist")
def post_include_artist(body: ArtistIn, db_path: Path = Depends(get_db_path)) -> dict[str, str]:
    """Espejo web de `skywave include`."""
    conn = db.connect(db_path)
    with conn:
        db.include_artist(conn, body.artist)
    return {"status": "ok"}


@app.get("/now-playing")
def now_playing(db_path: Path = Depends(get_db_path)) -> NowPlayingOut | None:
    """Qué está sonando ahora mismo, o `null` si la radio está apagada (o
    la biblioteca todavía está vacía) -- nunca un 500 por no tener nada
    que mostrar, mismo principio del resto del proyecto."""
    return _now_playing_payload(db_path)


async def _push_now_playing(websocket: WebSocket, db_path: Path, poll_interval: float) -> None:
    last_sent: NowPlayingOut | None | object = object()  # nunca == al primer payload real
    while True:
        payload = _now_playing_payload(db_path)
        if payload != last_sent:
            await websocket.send_json(payload.model_dump(mode="json") if payload else None)
            last_sent = payload
        await asyncio.sleep(poll_interval)


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    # Este endpoint solo empuja datos, no le importa lo que mande el
    # cliente -- pero *tiene* que llamar a receive() igual: es la única
    # forma de que Starlette entregue el mensaje "websocket.disconnect"
    # (cliente cerró la pestaña, o el propio server lo cierra en un
    # shutdown). Sin esto, _push_now_playing nunca se entera y el
    # server queda esperando esta conexión para siempre en cada
    # `--reload` o Ctrl+C -- encontrado a mano: el reload se quedaba
    # colgado en "Waiting for background tasks to complete" con
    # cualquier pestaña abierta.
    while True:
        await websocket.receive_text()


@app.websocket("/ws")
async def now_playing_ws(
    websocket: WebSocket,
    db_path: Path = Depends(get_db_path),
    poll_interval: float = Depends(get_poll_interval),
) -> None:
    """Empuja el "sonando ahora" apenas cambia, para que la página no
    tenga que hacer polling HTTP por su cuenta. SQLite no tiene pub/sub
    nativo -- un loop hace el polling del lado del servidor sobre
    `now_playing`, un solo lugar leyendo la base cada `poll_interval`
    en vez de una consulta HTTP por cada pestaña abierta.

    Corre ese loop junto a otro que solo escucha la desconexión
    (`_wait_for_disconnect`): el primero que termina cancela al otro."""
    await websocket.accept()
    push_task = asyncio.create_task(_push_now_playing(websocket, db_path, poll_interval))
    disconnect_task = asyncio.create_task(_wait_for_disconnect(websocket))
    done, pending = await asyncio.wait(
        {push_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    # asyncio.wait no propaga la excepción del que terminó primero (p.ej.
    # WebSocketDisconnect) -- hay que recuperarla acá, aunque no haga
    # falta hacer nada con ella, o queda un "exception never retrieved"
    # cuando el garbage collector se lleve la Task.
    for task in done | pending:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await task
