from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

from skywave.mixer._process import drain_stderr

_CHUNK_SIZE = 4096


class Decoder:
    """Decodifica un archivo de audio a PCM crudo (s16le, 44100Hz, estéreo)
    a ritmo real.

    `-re` hace que ffmpeg mismo pace la lectura del archivo a velocidad de
    reproducción — la alternativa sería leer todo lo más rápido posible y
    dormir a mano entre writes calculando bytes-por-segundo, más frágil.
    `-vn` es explícito aunque el output PCM crudo no puede llevar video de
    todos modos: mejor no depender de que ffmpeg lo ignore solo.

    A diferencia del Encoder (persistente, vive toda la sesión), un
    Decoder vive solo mientras dura esa pista.
    """

    def __init__(self, path: Path) -> None:
        self._process = subprocess.Popen(
            [
                "ffmpeg",
                "-loglevel",
                "warning",
                "-re",
                "-i",
                str(path),
                "-vn",
                "-f",
                "s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stdout = self._process.stdout
        self._stderr_thread = threading.Thread(
            target=drain_stderr, args=(self._process.stderr,), daemon=True
        )
        self._stderr_thread.start()

    def chunks(self) -> Iterator[bytes]:
        """Itera los chunks de PCM a medida que ffmpeg los decodifica."""
        try:
            while True:
                chunk = self._stdout.read(_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            self._process.terminate()
            self._process.wait()
            self._stderr_thread.join(timeout=5)
