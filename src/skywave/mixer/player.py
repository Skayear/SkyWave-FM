from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator
from pathlib import Path

from skywave.mixer.audio import bytes_to_samples, fade_in, fade_out, mix, samples_to_bytes
from skywave.mixer.decoder import Decoder
from skywave.mixer.encoder import Encoder

_SAMPLE_RATE = 44100
_FRAME_BYTES = 4  # s16le estéreo: 2 canales * 2 bytes/muestra

#: Default razonable para crossfade entre temas (issue #22). 3-5s es lo
#: habitual en radio; más largo y se pisan las letras de dos temas.
DEFAULT_CROSSFADE_SECONDS = 4.0


def crossfade_window_bytes(seconds: float) -> int:
    """Cuántos bytes de PCM ocupan `seconds` de audio (s16le, 44100Hz, estéreo)."""
    return int(_SAMPLE_RATE * seconds) * _FRAME_BYTES


def _crossfade(tail: bytes, head: bytes) -> bytes:
    """Funde la cola saliente (fade-out) con el arranque entrante (fade-in),
    mezclando ambas señales. Si difieren en largo (un tema más corto que la
    ventana de crossfade), usa el menor de los dos."""
    frames = min(len(tail), len(head)) // _FRAME_BYTES * _FRAME_BYTES
    faded_tail = fade_out(bytes_to_samples(tail[:frames]))
    faded_head = fade_in(bytes_to_samples(head[:frames]))
    return samples_to_bytes(mix(faded_tail, faded_head))


def _take(chunks: Iterator[bytes], count: int) -> tuple[bytes, Iterator[bytes]]:
    """Consume de `chunks` hasta juntar `count` bytes (menos si el stream
    termina antes) y devuelve lo juntado más un iterador para seguir
    consumiendo el resto sin perder lo que sobró de más."""
    collected = b""
    for chunk in chunks:
        collected += chunk
        if len(collected) >= count:
            leftover = collected[count:]
            rest = itertools.chain([leftover] if leftover else [], chunks)
            return collected[:count], rest
    return collected, chunks


def play_track(
    encoder: Encoder,
    path: Path,
    *,
    crossfade_seconds: float = 0.0,
    incoming_tail: bytes = b"",
) -> bytes:
    """Reproduce una pista completa contra `encoder`, que sigue vivo al
    terminar — la conexión a Icecast no se toca entre pistas, solo cambia
    el Decoder que la alimenta.

    Si `incoming_tail` no está vacío (la cola retenida del tema anterior),
    se funde con el arranque de esta pista en vez de escribirse en seco.

    Si `crossfade_seconds` > 0, retiene esa cantidad final de PCM sin
    escribirla y la devuelve — el llamador se la pasa como `incoming_tail`
    al siguiente `play_track` para encadenar el fundido. Si no la usa (por
    ejemplo porque el locutor habla antes del siguiente tema), tiene que
    escribirla él mismo o esos últimos segundos no suenan.
    """
    decoder = Decoder(path)
    chunks = decoder.chunks()

    if incoming_tail:
        head, chunks = _take(chunks, len(incoming_tail))
        encoder.write(_crossfade(incoming_tail, head))

    hold_bytes = crossfade_window_bytes(crossfade_seconds)
    buffer = b""
    for chunk in chunks:
        buffer += chunk
        if len(buffer) > hold_bytes:
            overflow = len(buffer) - hold_bytes
            encoder.write(buffer[:overflow])
            buffer = buffer[overflow:]
    return buffer


def play_tracks(encoder: Encoder, paths: Iterable[Path], *, crossfade_seconds: float = 0.0) -> None:
    """Reproduce `paths` en secuencia contra el mismo `encoder`, fundiendo
    la cola de cada tema con el arranque del siguiente si `crossfade_seconds` > 0.
    """
    tail = b""
    for path in paths:
        tail = play_track(encoder, path, crossfade_seconds=crossfade_seconds, incoming_tail=tail)
    if tail:
        encoder.write(tail)
