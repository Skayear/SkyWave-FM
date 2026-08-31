import os
import sqlite3
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
from skywave.host.scripts import (
    OllamaGenerator,
    ResilientScriptWriter,
    TemplateGenerator,
    english_terms_for,
)
from skywave.host.templates import render_greeting_script
from skywave.host.tts import DEFAULT_VOICE, Synthesizer
from skywave.library import db
from skywave.library.scanner import find_audio_files
from skywave.library.tags import read_tags
from skywave.library.track import Track
from skywave.mixer.encoder import Encoder
from skywave.mixer.player import DEFAULT_CROSSFADE_SECONDS, play_ducked, play_track
from skywave.scheduler.ads import pick_next_ad, should_play_ad
from skywave.scheduler.greetings import should_read_greeting
from skywave.scheduler.selector import plan_queue
from skywave.web import greetings as web_greetings

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
#: Cuántos temas planifica por adelantado `upcoming_queue` (issue #40)
#: -- mismo número que mostraba "a continuación" en la web desde #38.
QUEUE_DEPTH = 5


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


_ArtistArgument = typer.Argument(
    ..., help="Nombre exacto del artista, como aparece en `skywave list`."
)


@app.command()
def exclude(artist: str = _ArtistArgument, db_path: Path = _DbOption) -> None:
    """Excluye un artista de la rotación de `skywave play` (issue #41).
    No borra nada de la biblioteca -- `skywave list`/`scan` lo siguen
    mostrando, solo la radio lo salta."""
    conn = db.connect(db_path)
    with conn:
        db.exclude_artist(conn, artist)
    console.print(f"[bold]{artist}[/bold] excluido de la rotación.")


@app.command(name="include")
def include_artist_command(artist: str = _ArtistArgument, db_path: Path = _DbOption) -> None:
    """Vuelve a incluir un artista excluido con `skywave exclude`."""
    conn = db.connect(db_path)
    with conn:
        db.include_artist(conn, artist)
    console.print(f"[bold]{artist}[/bold] vuelve a sonar.")


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
    saludos: bool = typer.Option(
        True, "--saludos/--sin-saludos", help="Leer al aire los saludos que llegan por la web."
    ),
    saludos_every: int = typer.Option(
        5, "--saludos-every", help="Cada cuántos temas se lee un saludo pendiente."
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

    def _effective_catalog(exclusion_conn: sqlite3.Connection) -> list[Track]:
        """Catálogo real disponible para `pick_next`/`plan_queue`,
        filtrando artistas excluidos (issue #41). Se recalcula en cada
        llamada (no una vez al arrancar) para que excluir/incluir por
        CLI o por la web se note sin reiniciar `skywave play`. Si
        excluir dejaría el pool vacío, se ignora la exclusión -- mismo
        principio que el resto del scheduler: la radio nunca se queda
        muda por una regla, ni siquiera esta."""
        excluded = db.excluded_artists(exclusion_conn)
        if not excluded:
            return catalog
        filtered = [track for track in catalog if track.artist not in excluded]
        return filtered or catalog

    host = _build_locutor() if locutor else None
    # Publicidades pre-renderizadas (issue #25/#26): si no hay ninguna
    # (todavía no se corrió `skywave render-ads`), la radio sigue igual,
    # sin publicidades — mismo principio de siempre, nunca se queda muda
    # por falta de una pieza opcional.
    ads = list_ads(DEFAULT_ADS_DIR) if publicidades else []
    # Los saludos necesitan la misma voz que el locutor (Kokoro) para
    # sintetizarse en vivo -- si el locutor está apagado o sin voz
    # disponible, no hay forma de leerlos al aire.
    leer_saludos = saludos and host is not None
    if leer_saludos:
        with conn:
            web_greetings.ensure_schema(conn)
    # Estado de una corrida anterior que no cerró limpio (crash, un
    # `docker stop` que escaló a SIGKILL porque el cleanup del `finally`
    # no llegó a correr -- ver docker-entrypoint.sh) puede dejar
    # `now_playing` mintiendo un tema viejo y `upcoming_queue` con un
    # plan que ya no corresponde (por ejemplo si cambió
    # --no-repeat-artist). Mejor arrancar en blanco que arrastrar
    # cualquiera de los dos.
    with conn:
        db.clear_now_playing(conn)
        db.clear_upcoming_queue(conn)
    icecast_url = _icecast_url(mount)
    console.print(
        f"Al aire con {len(_effective_catalog(conn))} tracks "
        f"-> [bold]{mount}[/bold] (Ctrl+C para cortar)"
    )
    history: list[Track] = []

    def _prepare_next(previous_track: Track | None) -> _Prepared:
        """Planifica hasta `QUEUE_DEPTH` en `upcoming_queue` (issue #40)
        si hace falta y arma la intervención (guion + WAV) del primero
        de la cola. Corre en el hilo de fondo mientras suena el tema
        actual — issue #20: para cuando termine ese tema, esta ya está
        lista y entra sin aire muerto.

        Ojo: solo **mira** el primero de la cola (`peek_queue`), no lo
        saca todavía. Esta función corre un paso adelantada a lo que
        efectivamente está sonando -- si sacara el tema acá, `GET
        /queue` mostraría el que viene *después* del próximo real (el
        próximo real ya estaría afuera de la tabla, resuelto en este
        `Future` pero sin sonar todavía). Quien saca de la cola es el
        loop principal, recién cuando este resultado pasa a ser
        `current` de verdad (ver más abajo).

        Conexión propia a la base (`db.connect`, no el `conn` del hilo
        principal): esta función corre en el hilo de fondo de
        `prep_pool`, y `sqlite3.Connection` no es segura para compartir
        entre threads -- mismo criterio que `web/app.py`, que abre una
        conexión nueva por request en vez de compartir una global."""
        queue_conn = db.connect(db_path)
        with queue_conn:
            already_queued = db.peek_queue(queue_conn, limit=QUEUE_DEPTH)
            nuevos = plan_queue(
                _effective_catalog(queue_conn),
                history,
                already_queued,
                target_depth=QUEUE_DEPTH,
                no_repeat_artist=no_repeat_artist,
            )
            for nuevo in nuevos:
                db.enqueue_track(queue_conn, nuevo)
        planned = db.peek_queue(queue_conn, limit=1)
        assert planned  # target_depth >= 1 garantiza al menos un tema planeado
        track = planned[0]
        history.append(track)
        # El historial solo alimenta la ventana de no-repetición: con
        # quedarnos los últimos temas alcanza, no crece infinito.
        del history[:-20]
        if host is None:
            return _Prepared(track, None, None, None)
        try:
            writer, cache = host
            script = writer.generate(previous_track, track, datetime.now())
            # Títulos/artistas se fonemizan con el motor de inglés en vez
            # del de español (host/tts.py) para que se pronuncien bien.
            english_terms = english_terms_for(previous_track, track)
            wav_path = cache.wav_for(script, english_terms=english_terms)
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
    tracks_since_greeting = 0
    try:
        current = _prepare_next(None)
        with Encoder(icecast_url) as encoder:
            while True:
                with conn:
                    db.set_now_playing(conn, current.track)
                    db.record_play_history(conn, current.track)
                    # Recién ahora `current` deja de ser una vista previa y
                    # pasa a sonar de verdad -- se saca de upcoming_queue
                    # en este momento, no antes (ver el comentario en
                    # _prepare_next sobre por qué no se saca ahí).
                    db.dequeue_next(conn)
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

                tracks_since_greeting += 1
                if leer_saludos and should_read_greeting(
                    tracks_since_greeting, every=saludos_every
                ):
                    pendientes = web_greetings.unread_greetings(conn)
                    if pendientes:
                        tracks_since_greeting = 0
                        greeting = pendientes[0]
                        try:
                            assert host is not None  # leer_saludos ya lo garantiza
                            _, cache = host
                            script = render_greeting_script(greeting.message)
                            wav_path = cache.wav_for(script)
                            if pending_tail:
                                encoder.write(pending_tail)
                                pending_tail = b""
                            console.print(f"💬 {script}")
                            play_track(encoder, wav_path)
                            with conn:
                                web_greetings.mark_greeting_read(conn, greeting.id)
                        except Exception as error:
                            console.print(
                                f"[yellow]No se pudo leer el saludo ({error}), "
                                "sigue la música.[/yellow]"
                            )

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
            db.clear_upcoming_queue(conn)
