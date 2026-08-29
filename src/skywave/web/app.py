import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from skywave.library import db

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


@app.get("/", response_class=HTMLResponse)
def index(request: Request, stream_url: str = Depends(get_stream_url)) -> HTMLResponse:
    """Página con el reproductor. El "sonando ahora" no se rellena acá
    server-side -- se pide async a `/now-playing` desde JS (ver
    templates/index.html) para poder refrescarlo sin recargar la
    página."""
    return templates.TemplateResponse(request, "index.html", {"stream_url": stream_url})


@app.get("/now-playing")
def now_playing(db_path: Path = Depends(get_db_path)) -> NowPlayingOut | None:
    """Qué está sonando ahora mismo, o `null` si la radio está apagada (o
    la biblioteca todavía está vacía) -- nunca un 500 por no tener nada
    que mostrar, mismo principio del resto del proyecto."""
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
