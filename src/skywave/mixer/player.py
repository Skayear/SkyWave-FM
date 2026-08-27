from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

from skywave.mixer.audio import (
    apply_envelope,
    bytes_to_samples,
    fade_in,
    fade_out,
    mix,
    samples_to_bytes,
)
from skywave.mixer.decoder import Decoder
from skywave.mixer.encoder import Encoder

_SAMPLE_RATE = 44100
_FRAME_BYTES = 4  # s16le estéreo: 2 canales * 2 bytes/muestra

#: Default razonable para crossfade entre temas (issue #22). 3-5s es lo
#: habitual en radio; más largo y se pisan las letras de dos temas.
DEFAULT_CROSSFADE_SECONDS = 4.0

#: Factor de atenuación de la música de colchón mientras habla el locutor
#: (issue #23) y cuánto tardan las rampas de bajada/subida.
DEFAULT_DUCK_GAIN = 0.25
DEFAULT_DUCK_RAMP_SECONDS = 0.5


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


def _duck_envelope(frame_count: int, *, duck_gain: float, ramp_frames: int) -> np.ndarray:
    """Envolvente de tres tramos: baja de 1.0 a `duck_gain`, sostiene, sube
    de vuelta a 1.0. Si el segmento es más corto que dos rampas, las recorta
    a la mitad cada una — nunca se solapan."""
    ramp_frames = min(ramp_frames, frame_count // 2)
    hold_frames = frame_count - 2 * ramp_frames
    down = np.linspace(1.0, duck_gain, num=ramp_frames, endpoint=False)
    up = np.linspace(duck_gain, 1.0, num=ramp_frames)
    hold = np.full(hold_frames, duck_gain)
    return np.concatenate([down, hold, up])


def _duck_mix(speech: bytes, music: bytes, *, duck_gain: float, ramp_seconds: float) -> bytes:
    """Mezcla la voz (a volumen pleno) con la música (atenuada como
    colchón, con rampas suaves de bajada y subida). Si difieren en largo,
    usa el menor de los dos."""
    frames = min(len(speech), len(music)) // _FRAME_BYTES * _FRAME_BYTES
    speech_samples = bytes_to_samples(speech[:frames])
    music_samples = bytes_to_samples(music[:frames])
    envelope = _duck_envelope(
        len(music_samples), duck_gain=duck_gain, ramp_frames=int(_SAMPLE_RATE * ramp_seconds)
    )
    ducked_music = apply_envelope(music_samples, envelope)
    return samples_to_bytes(mix(speech_samples, ducked_music))


def _stream_with_held_tail(encoder: Encoder, chunks: Iterator[bytes], hold_bytes: int) -> bytes:
    """Escribe `chunks` a `encoder`, reteniendo los últimos `hold_bytes` sin
    escribir, y los devuelve (para crossfade con lo próximo a sonar)."""
    buffer = b""
    for chunk in chunks:
        buffer += chunk
        if len(buffer) > hold_bytes:
            overflow = len(buffer) - hold_bytes
            encoder.write(buffer[:overflow])
            buffer = buffer[overflow:]
    return buffer


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

    return _stream_with_held_tail(encoder, chunks, crossfade_window_bytes(crossfade_seconds))


def play_ducked(
    encoder: Encoder,
    speech_path: Path,
    music_path: Path,
    *,
    crossfade_seconds: float = 0.0,
    duck_gain: float = DEFAULT_DUCK_GAIN,
    ramp_seconds: float = DEFAULT_DUCK_RAMP_SECONDS,
) -> bytes:
    """Reproduce el locutor (`speech_path`) sobre el arranque de la próxima
    pista (`music_path`) como colchón atenuado, y sigue con el resto de la
    pista a volumen normal — reemplaza la voz en seco de Fase 4.

    La música de colchón es el arranque del tema *entrante*, no la cola del
    saliente (issue #23): es lo que un locutor de radio real hace. Si el
    tema que sale dejó una cola pendiente de crossfade (#22), el llamador
    tiene que escribirla aparte antes de esta llamada — acá no se mezcla.

    Igual que `play_track`, si `crossfade_seconds` > 0 retiene esa cola
    final del tema (después del segmento con colchón) y la devuelve.
    """
    speech = b"".join(Decoder(speech_path).chunks())
    music_chunks = Decoder(music_path).chunks()
    bed, rest = _take(music_chunks, len(speech))
    encoder.write(_duck_mix(speech, bed, duck_gain=duck_gain, ramp_seconds=ramp_seconds))
    return _stream_with_held_tail(encoder, rest, crossfade_window_bytes(crossfade_seconds))


def play_tracks(encoder: Encoder, paths: Iterable[Path], *, crossfade_seconds: float = 0.0) -> None:
    """Reproduce `paths` en secuencia contra el mismo `encoder`, fundiendo
    la cola de cada tema con el arranque del siguiente si `crossfade_seconds` > 0.
    """
    tail = b""
    for path in paths:
        tail = play_track(encoder, path, crossfade_seconds=crossfade_seconds, incoming_tail=tail)
    if tail:
        encoder.write(tail)
