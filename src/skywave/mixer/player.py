from collections.abc import Iterable
from pathlib import Path

from skywave.mixer.decoder import Decoder
from skywave.mixer.encoder import Encoder


def play_tracks(encoder: Encoder, paths: Iterable[Path]) -> None:
    """Reproduce `paths` en secuencia contra `encoder`, ya abierto y vivo
    durante toda la secuencia: solo cambia el Decoder de una pista a la
    siguiente, la conexión a Icecast no se toca entre temas.

    No gapless a nivel milisegundo todavía (cada Decoder arranca su propio
    proceso ffmpeg, que tarda un poco en levantar) — alcanza con que el
    encoder no se reconecte entre pistas. Afinar el gap queda para más
    adelante si hace falta.
    """
    for path in paths:
        decoder = Decoder(path)
        for chunk in decoder.chunks():
            encoder.write(chunk)
