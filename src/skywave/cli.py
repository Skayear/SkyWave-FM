import os
from datetime import datetime
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from skywave.host.cache import VoiceCache
from skywave.host.scripts import OllamaGenerator, ResilientScriptWriter, TemplateGenerator
from skywave.host.tts import DEFAULT_VOICE, Synthesizer
from skywave.library import db
from skywave.library.scanner import find_audio_files
from skywave.library.tags import read_tags
from skywave.library.track import Track
from skywave.mixer.encoder import Encoder
from skywave.mixer.player import DEFAULT_CROSSFADE_SECONDS, play_ducked, play_track
from skywave.scheduler.selector import pick_next

app = typer.Typer()
console = Console()

# Sin config.toml todavía (llega más adelante en el roadmap) — por ahora
# cada comando recibe --db, con este valor por default en el cwd.
DEFAULT_DB_PATH = Path("skywave.db")

_DbOption = typer.Option(DEFAULT_DB_PATH, "--db", help="Archivo SQLite de la biblioteca.")
_CarpetaArgument = typer.Argument(
    ..., exists=True, file_okay=False, help="Carpeta de música a escanear recursivamente."
)
_MountOption = typer.Option("sky.mp3", "--mount", help="Punto de montaje en Icecast.")


@app.command()
def scan(
    carpeta: Path = _CarpetaArgument,
    db_path: Path = _DbOption,
) -> None:
    """Escanea CARPETA y guarda los tracks encontrados en la biblioteca."""
    conn = db.connect(db_path)
    encontrados = 0
    with conn:
        for path in find_audio_files(carpeta):
            track = Track.from_tags(path, read_tags(path))
            db.upsert_track(conn, track)
            encontrados += 1
    console.print(f"{encontrados} tracks escaneados en [bold]{db_path}[/bold]")


@app.command(name="list")
def list_tracks(db_path: Path = _DbOption) -> None:
    """Lista los tracks guardados en la biblioteca."""
    conn = db.connect(db_path)
    tracks = db.list_tracks(conn)

    if not tracks:
        console.print(
            "La biblioteca está vacía. Corré [bold]skywave scan <carpeta>[/bold] primero."
        )
        raise typer.Exit()

    table = Table()
    table.add_column("Artista")
    table.add_column("Título")
    table.add_column("Año", justify="right")
    table.add_column("Álbum")
    for track in tracks:
        table.add_row(
            track.artist,
            track.title,
            str(track.year) if track.year is not None else "-",
            track.album or "-",
        )
    console.print(table)


def _icecast_url(mount: str) -> str:
    load_dotenv()
    password = os.environ.get("ICECAST_SOURCE_PASSWORD")
    if password is None:
        console.print("[bold red]Falta ICECAST_SOURCE_PASSWORD[/bold red] (¿existe el .env?).")
        raise typer.Exit(code=1)
    host = os.environ.get("ICECAST_SERVER_HOST", "localhost")
    port = os.environ.get("ICECAST_SOURCE_PORT", "8010")
    return f"icecast://source:{password}@{host}:{port}/{mount}"


def _build_locutor() -> tuple[ResilientScriptWriter, VoiceCache] | None:
    """Arma el pipeline del locutor (guiones + voz + cache). Si falta la voz
    de Piper, avisa y devuelve None: la radio sale igual, sin locutor."""
    try:
        synthesizer = Synthesizer()
    except FileNotFoundError as error:
        console.print(f"[yellow]Sin locutor:[/yellow] {error}")
        return None
    writer = ResilientScriptWriter(OllamaGenerator(), TemplateGenerator())
    cache = VoiceCache(synthesizer.synthesize, voice_id=DEFAULT_VOICE.stem)
    return writer, cache


@app.command()
def play(
    db_path: Path = _DbOption,
    mount: str = _MountOption,
    no_repeat_artist: int = typer.Option(
        3, "--no-repeat-artist", help="Ventana de temas sin repetir artista."
    ),
    locutor: bool = typer.Option(
        True, "--locutor/--sin-locutor", help="Presentar los temas con voz entre tema y tema."
    ),
) -> None:
    """Sale al aire en modo radio: suena indefinidamente hasta Ctrl+C."""
    conn = db.connect(db_path)
    catalog = db.list_tracks(conn)

    if not catalog:
        console.print(
            "La biblioteca está vacía. Corré [bold]skywave scan <carpeta>[/bold] primero."
        )
        raise typer.Exit()

    host = _build_locutor() if locutor else None
    icecast_url = _icecast_url(mount)
    console.print(f"Al aire con {len(catalog)} tracks -> [bold]{mount}[/bold] (Ctrl+C para cortar)")
    history: list[Track] = []
    previous: Track | None = None
    # Cola retenida del tema anterior, para fundirla con el arranque del
    # siguiente (crossfade). Si el locutor habla en el medio, se escribe
    # tal cual antes de que arranque el colchón (ducking) del próximo
    # tema: la voz funde con la música entrante, no con la saliente.
    pending_tail = b""
    try:
        with Encoder(icecast_url) as encoder:
            while True:
                track = pick_next(catalog, history, no_repeat_artist=no_repeat_artist)
                history.append(track)
                # El historial solo alimenta la ventana de no-repetición:
                # con quedarnos los últimos temas alcanza, no crece infinito.
                del history[:-20]
                with conn:
                    db.set_now_playing(conn, track)
                # Nada del locutor puede voltear la música: si el guion, la
                # síntesis o el cache fallan, el tema entra igual (sin voz).
                track_played = False
                if host is not None:
                    try:
                        writer, cache = host
                        script = writer.generate(previous, track, datetime.now())
                        console.print(f"🎙 {script}")
                        if pending_tail:
                            encoder.write(pending_tail)
                            pending_tail = b""
                        console.print(f"♪ {track.artist} — {track.title}")
                        # La voz suena sobre el arranque de este tema como
                        # colchón atenuado (ducking) en vez de en seco.
                        pending_tail = play_ducked(
                            encoder,
                            cache.wav_for(script),
                            track.path,
                            crossfade_seconds=DEFAULT_CROSSFADE_SECONDS,
                        )
                        track_played = True
                    except Exception as error:
                        console.print(f"[yellow]Locutor falló ({error}), sigue la música.[/yellow]")
                if not track_played:
                    console.print(f"♪ {track.artist} — {track.title}")
                    pending_tail = play_track(
                        encoder,
                        track.path,
                        crossfade_seconds=DEFAULT_CROSSFADE_SECONDS,
                        incoming_tail=pending_tail,
                    )
                previous = track
    except KeyboardInterrupt:
        console.print("\nCortando la radio.")
    finally:
        with conn:
            db.clear_now_playing(conn)
