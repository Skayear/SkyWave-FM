from __future__ import annotations

import logging
import subprocess
import threading
from typing import IO

logger = logging.getLogger(__name__)


def _drain_stderr(stderr: IO[bytes]) -> None:
    """Lee y loggea el stderr de un proceso ffmpeg hasta que se cierra.

    No es opcional: el pipe de stderr tiene un buffer chico (~64KB en
    Linux). Si nadie lo lee mientras el proceso vive, ffmpeg se bloquea
    escribiendo ahí en cuanto se llena — un deadlock silencioso que solo
    aparece con streams largos, no en una prueba rápida.
    """
    for line in stderr:
        logger.debug("ffmpeg: %s", line.decode(errors="replace").rstrip())


class Encoder:
    """Proceso ffmpeg de larga duración: recibe PCM crudo (s16le, 44100Hz,
    estéreo) por stdin y lo empuja a Icecast como un source en vivo.

    Vive durante toda la sesión de radio — no es un proceso por pista, eso
    es el Decoder (issue #8). Por eso la conexión a Icecast no se corta al
    pasar de un tema al siguiente: seguimos escribiéndole al mismo proceso.
    """

    def __init__(self, icecast_url: str) -> None:
        self._process = subprocess.Popen(
            [
                "ffmpeg",
                "-loglevel",
                "warning",
                "-f",
                "s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-i",
                "pipe:0",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-content_type",
                "audio/mpeg",
                "-f",
                "mp3",
                icecast_url,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert self._process.stdin is not None
        assert self._process.stderr is not None
        self._stdin = self._process.stdin
        self._stderr_thread = threading.Thread(
            target=_drain_stderr, args=(self._process.stderr,), daemon=True
        )
        self._stderr_thread.start()

    def write(self, pcm: bytes) -> None:
        self._stdin.write(pcm)

    def close(self) -> None:
        self._stdin.close()
        self._process.wait()
        self._stderr_thread.join(timeout=5)

    def __enter__(self) -> Encoder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
