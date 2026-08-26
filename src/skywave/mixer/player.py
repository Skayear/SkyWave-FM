from collections.abc import Iterable
from pathlib import Path

from skywave.mixer.decoder import Decoder
from skywave.mixer.encoder import Encoder


def play_track(encoder: Encoder, path: Path) -> None:
    """Reproduce una pista completa contra `encoder`, que sigue vivo al
    terminar — la conexión a Icecast no se toca entre pistas, solo cambia
    el Decoder que la alimenta."""
    decoder = Decoder(path)
    for chunk in decoder.chunks():
        encoder.write(chunk)


def play_tracks(encoder: Encoder, paths: Iterable[Path]) -> None:
    """Reproduce `paths` en secuencia contra el mismo `encoder`.

    No gapless a nivel milisegundo todavía (cada Decoder arranca su propio
    proceso ffmpeg, que tarda un poco en levantar) — alcanza con que el
    encoder no se reconecte entre pistas. Afinar el gap queda para más
    adelante si hace falta.
    """
    for path in paths:
        play_track(encoder, path)
