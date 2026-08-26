import logging
from typing import IO

logger = logging.getLogger(__name__)


def drain_stderr(stderr: IO[bytes]) -> None:
    """Lee y loggea el stderr de un proceso ffmpeg hasta que se cierra.

    No es opcional: el pipe de stderr tiene un buffer chico (~64KB en
    Linux). Si nadie lo lee mientras el proceso vive, ffmpeg se bloquea
    escribiendo ahí en cuanto se llena — un deadlock silencioso que solo
    aparece con streams largos, no en una prueba rápida. Usado tanto por
    el Encoder (persistente) como por el Decoder (uno por pista).
    """
    for line in stderr:
        logger.debug("ffmpeg: %s", line.decode(errors="replace").rstrip())
