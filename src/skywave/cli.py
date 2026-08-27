import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from skywave.ads.jingle import produce_ad
from skywave.ads.render import list_ads, render_ads
from skywave.host.cache import VoiceCache
from skywave.host.scripts import OllamaGenerator, ResilientScriptWriter, TemplateGenerator
from skywave.host.tts import DEFAULT_VOICE, Synthesizer
from skywave.library import db
from skywave.library.scanner import find_audio_files
from skywave.library.tags import read_tags
from skywave.library.track import Track
from skywave.mixer.encoder import Encoder
from skywave.mixer.player import DEFAULT_CROSSFADE_SECONDS, play_ducked, play_track
from skywave.scheduler.ads import pick_next_ad, should_play_ad
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
_AdsScriptsDirOption = typer.Option(
    Path("assets/ads/scripts"), "--scripts-dir", help="Carpeta con los guiones .txt curados."
)
_AdsOutDirOption = typer.Option(
    Path("assets/ads"), "--out-dir", help="Carpeta donde se escriben los WAV renderizados."
)
DEFAULT_ADS_DIR = Path("assets/ads")


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
            track = Track.from_tags(path, read_tags(path), root=carpeta)
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


@app.command(name="render-ads")
def render_ads_command(
    scripts_dir: Path = _AdsScriptsDirOption,
    out_dir: Path = _AdsOutDirOption,
) -> None:
    """Sintetiza a WAV las publicidades curadas a mano en --scripts-dir.

    Paso manual: se corre cuando se agrega o edita una publicidad, no es
    parte del loop de la radio en vivo — las publicidades nunca se generan
    en vivo.
    """
    try:
        synthesizer = Synthesizer()
    except FileNotFoundError as error:
        console.print(f"[bold red]Sin voz para el locutor:[/bold red] {error}")
        raise typer.Exit(code=1) from error

    if not scripts_dir.exists():
        console.print(f"No hay guiones en [bold]{scripts_dir}[/bold] todavía.")
        raise typer.Exit()

    rendered = render_ads(scripts_dir, out_dir, synthesizer.synthesize, produce=produce_ad)
    if not rendered:
        console.print(f"Ningún guion [bold].txt[/bold] en [bold]{scripts_dir}[/bold].")
        raise typer.Exit()
    console.print(f"{len(rendered)} publicidades renderizadas en [bold]{out_dir}[/bold]")


def _icecast_url(mount: str) -> str:
    load_dotenv()
    password = os.environ.get("ICECAST_SOURCE_PASSWORD")
    if password is None:
        console.print("[bold red]Falta ICECAST_SOURCE_PASSWORD[/bold red] (¿existe el .env?).")
        raise typer.Exit(code=1)
    host = os.environ.get("ICECAST_SERVER_HOST", "localhost")
    port = os.environ.get("ICECAST_SOURCE_PORT", "8010")
    return f"icecast://source:{password}@{host}:{port}/{mount}"


@dataclass(frozen=True, slots=True)
class _Prepared:
    """Un tema ya elegido, con su intervención del locutor lista (guion +
    WAV sintetizado) para que entre al toque cuando termine el anterior.

    `script`/`wav_path` quedan en None si el locutor está apagado o falló
    generando/sintetizando — la radio sigue igual, sin voz para ese tema.
    """

    track: Track
    script: str | None
    wav_path: Path | None
    error: str | None


def _ad_display_name(ad_path: Path) -> str:
    """ "mate-turbo.wav" -> "Mate Turbo", para la consola."""
    return ad_path.stem.replace("-", " ").replace("_", " ").title()


def _build_locutor() -> tuple[ResilientScriptWriter, VoiceCache] | None:
    """Arma el pipeline del locutor (guiones + voz + cache). Si no se pudo
    cargar la voz (sin red la primera vez, por ejemplo), avisa y devuelve
    None: la radio sale igual, sin locutor."""
    try:
        synthesizer = Synthesizer()
    except FileNotFoundError as error:
        console.print(f"[yellow]Sin locutor:[/yellow] {error}")
        return None
    writer = ResilientScriptWriter(OllamaGenerator(), TemplateGenerator())
    cache = VoiceCache(synthesizer.synthesize, voice_id=DEFAULT_VOICE)
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
    publicidades: bool = typer.Option(
        True, "--publicidades/--sin-publicidades", help="Intercalar publicidades entre temas."
    ),
    ads_every: int = typer.Option(
        8, "--ads-every", help="Cada cuántos temas suena una publicidad."
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
    # Publicidades pre-renderizadas (issue #25/#26): si no hay ninguna
    # (todavía no se corrió `skywave render-ads`), la radio sigue igual,
    # sin publicidades — mismo principio de siempre, nunca se queda muda
    # por falta de una pieza opcional.
    ads = list_ads(DEFAULT_ADS_DIR) if publicidades else []
    icecast_url = _icecast_url(mount)
    console.print(f"Al aire con {len(catalog)} tracks -> [bold]{mount}[/bold] (Ctrl+C para cortar)")
    history: list[Track] = []

    def _prepare_next(previous_track: Track | None) -> _Prepared:
        """Elige el próximo tema y le arma la intervención (guion + WAV).
        Corre en el hilo de fondo mientras suena el tema actual — issue
        #20: para cuando termine ese tema, esta ya está lista y entra sin
        aire muerto."""
        track = pick_next(catalog, history, no_repeat_artist=no_repeat_artist)
        history.append(track)
        # El historial solo alimenta la ventana de no-repetición: con
        # quedarnos los últimos temas alcanza, no crece infinito.
        del history[:-20]
        if host is None:
            return _Prepared(track, None, None, None)
        try:
            writer, cache = host
            script = writer.generate(previous_track, track, datetime.now())
            wav_path = cache.wav_for(script)
            return _Prepared(track, script, wav_path, None)
        except Exception as error:
            # Nada del locutor puede voltear la música: si el guion, la
            # síntesis o el cache fallan, el tema entra igual (sin voz).
            return _Prepared(track, None, None, str(error))

    # Cola retenida del tema anterior, para fundirla con el arranque del
    # siguiente (crossfade). Si el locutor habla en el medio, se escribe
    # tal cual antes de que arranque el colchón (ducking) del próximo
    # tema: la voz funde con la música entrante, no con la saliente.
    pending_tail = b""
    # Un solo worker: la preparación del siguiente tema es estrictamente
    # secuencial (depende del historial que dejó la anterior), no hay nada
    # que paralelizar entre sí — el paralelismo es contra la música sonando.
    prep_pool = ThreadPoolExecutor(max_workers=1)
    tracks_since_ad = 0
    ad_history: list[Path] = []
    try:
        current = _prepare_next(None)
        with Encoder(icecast_url) as encoder:
            while True:
                with conn:
                    db.set_now_playing(conn, current.track)
                # El tema de acá suena en tiempo real (Decoder -re): de
                # sobra para que este hilo tenga listo el siguiente
                # guion+WAV antes de que haga falta.
                next_future = prep_pool.submit(_prepare_next, current.track)

                if current.error is not None:
                    console.print(
                        f"[yellow]Locutor falló ({current.error}), sigue la música.[/yellow]"
                    )

                track_played = False
                if current.script is not None and current.wav_path is not None:
                    console.print(f"🎙 {current.script}")
                    if pending_tail:
                        encoder.write(pending_tail)
                        pending_tail = b""
                    console.print(f"♪ {current.track.artist} — {current.track.title}")
                    # La voz suena sobre el arranque de este tema como
                    # colchón atenuado (ducking) en vez de en seco.
                    pending_tail = play_ducked(
                        encoder,
                        current.wav_path,
                        current.track.path,
                        crossfade_seconds=DEFAULT_CROSSFADE_SECONDS,
                    )
                    track_played = True
                if not track_played:
                    console.print(f"♪ {current.track.artist} — {current.track.title}")
                    pending_tail = play_track(
                        encoder,
                        current.track.path,
                        crossfade_seconds=DEFAULT_CROSSFADE_SECONDS,
                        incoming_tail=pending_tail,
                    )

                tracks_since_ad += 1
                if ads and should_play_ad(tracks_since_ad, every=ads_every):
                    tracks_since_ad = 0
                    ad_path = pick_next_ad(ads, ad_history)
                    ad_history.append(ad_path)
                    del ad_history[:-5]
                    # now_playing NO se toca acá a propósito: sigue
                    # reflejando el último tema real. Una publicidad dura
                    # segundos y no es "programación" — la futura web de
                    # Fase 7 no necesita saber que hay una sonando, solo
                    # qué tema sigue en pie.
                    if pending_tail:
                        # La publicidad ya viene con sus propios fades
                        # (issue #26): no se funde con la cola del tema,
                        # se escribe tal cual y arranca la publicidad limpia.
                        encoder.write(pending_tail)
                        pending_tail = b""
                    console.print(f"📢 {_ad_display_name(ad_path)}")
                    play_track(encoder, ad_path)

                current = next_future.result()
    except KeyboardInterrupt:
        console.print("\nCortando la radio.")
    finally:
        # wait=False: no tiene sentido esperar a que termine una preparación
        # en curso (puede estar en medio del timeout de 30s de Ollama) solo
        # para tirarla — Ctrl+C corta ya.
        prep_pool.shutdown(wait=False, cancel_futures=True)
        with conn:
            db.clear_now_playing(conn)
