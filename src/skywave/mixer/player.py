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
#: (issue #23), afinado a oído por Pablo (2026-08-28). El locutor arranca
#: hablando solo, sin música (`DEFAULT_DUCK_SOLO_RATIO` de su habla es
#: puro silencio de fondo); recién en el 25% restante entra el colchón
#: (fade-in rápido + sostenido bajo), y solo vuelve a subir a volumen
#: pleno en un tramo aparte, después de que el habla ya terminó -- nunca
#: mientras todavía se lo escucha.
DEFAULT_DUCK_GAIN = 0.10
DEFAULT_DUCK_SOLO_RATIO = 0.75
DEFAULT_DUCK_FADE_IN_SECONDS = 0.2
DEFAULT_DUCK_RELEASE_SECONDS = 1.0


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


def _duck_envelope(
    speech_frames: int,
    *,
    duck_gain: float,
    solo_ratio: float,
    fade_in_frames: int,
    release_frames: int,
) -> np.ndarray:
    """Envolvente para el colchón de música bajo la voz, en cuatro tramos:

    1. Silencio total (`solo_ratio` del habla, ej. el primer 75%): el
       locutor arranca hablando solo, sin nada de música de fondo.
    2. Sube como colchón (`fade_in_frames`, recortado al resto del habla
       si no entra entero) hasta `duck_gain`.
    3. Sostiene atenuada el resto del habla.
    4. En un tramo aparte de `release_frames`, ya *después* de
       `speech_frames` (sobre silencio, sin voz), vuelve a subir a 1.0 —
       nunca mientras todavía se escucha al locutor.

    Devuelve `speech_frames + release_frames` valores.
    """
    silence_frames = round(speech_frames * solo_ratio)
    fade_in_frames = min(fade_in_frames, speech_frames - silence_frames)
    hold_frames = speech_frames - silence_frames - fade_in_frames
    silence = np.zeros(silence_frames)
    fade_in_ramp = np.linspace(0.0, duck_gain, num=fade_in_frames, endpoint=False)
    hold = np.full(hold_frames, duck_gain)
    release = np.linspace(duck_gain, 1.0, num=release_frames)
    return np.concatenate([silence, fade_in_ramp, hold, release])


def _duck_chunks(
    music_chunks: Iterator[bytes], padded_speech: bytes, envelope: np.ndarray
) -> Iterator[bytes]:
    """Mezcla `music_chunks` (a medida que van llegando) con `padded_speech`
    según `envelope`, chunk a chunk — no junta el colchón entero antes de
    escribir nada. Eso es lo que evita el aire muerto real que encontró
    Pablo al aire (2026-08-28): antes, `play_ducked` esperaba a tener todo
    el segmento con voz completo (varios segundos, a ritmo real) antes del
    primer `encoder.write()`; acá el primer chunk de música sale ya
    mezclado apenas ffmpeg lo entrega.

    `padded_speech` tiene que cubrir exactamente `len(envelope)` frames
    (la voz más el padding en silencio del release, ver `play_ducked`).
    Una vez que se consumieron esos frames, el resto de `music_chunks` se
    deja pasar sin tocar — ya es la pista sonando sola, sin colchón.
    """
    total_bytes = len(envelope) * _FRAME_BYTES
    offset = 0
    for chunk in music_chunks:
        if offset >= total_bytes:
            yield chunk
            continue
        mixed_len = min(len(chunk), total_bytes - offset)
        mixed_len -= mixed_len % _FRAME_BYTES
        if mixed_len:
            start_frame = offset // _FRAME_BYTES
            end_frame = start_frame + mixed_len // _FRAME_BYTES
            music_samples = bytes_to_samples(chunk[:mixed_len])
            speech_samples = bytes_to_samples(padded_speech[offset : offset + mixed_len])
            ducked_music = apply_envelope(music_samples, envelope[start_frame:end_frame])
            yield samples_to_bytes(mix(speech_samples, ducked_music))
        if mixed_len < len(chunk):
            yield chunk[mixed_len:]
        offset += len(chunk)


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
    solo_ratio: float = DEFAULT_DUCK_SOLO_RATIO,
    fade_in_seconds: float = DEFAULT_DUCK_FADE_IN_SECONDS,
    release_seconds: float = DEFAULT_DUCK_RELEASE_SECONDS,
) -> bytes:
    """Reproduce el locutor (`speech_path`) sobre el arranque de la próxima
    pista (`music_path`) como colchón atenuado, y sigue con el resto de la
    pista a volumen normal — reemplaza la voz en seco de Fase 4.

    La música de colchón es el arranque del tema *entrante*, no la cola del
    saliente (issue #23): es lo que un locutor de radio real hace. Si el
    tema que sale dejó una cola pendiente de crossfade (#22), el llamador
    tiene que escribirla aparte antes de esta llamada — acá no se mezcla.

    El locutor arranca hablando solo (`solo_ratio` de su habla sin nada de
    música), el colchón entra recién en el resto, y el colchón dura el
    habla más `release_seconds` extra de música (ya sin voz encima): recién
    ahí sube de vuelta a volumen pleno, para que nunca le compita en
    volumen a la cola de una frase.

    Igual que `play_track`, si `crossfade_seconds` > 0 retiene esa cola
    final del tema (después del segmento con colchón) y la devuelve.
    """
    # La voz se decodifica sin ritmo real: ya la necesitamos completa en
    # memoria para mezclarla con el colchón, y frenarla a ritmo real acá
    # dejaba el encoder sin nada que escribirle durante toda la duración
    # del guion — varios segundos de aire muerto real cada vez que hablaba
    # el locutor (encontrado por Pablo al aire, 2026-08-28).
    speech = b"".join(Decoder(speech_path, realtime=False).chunks())
    speech_frames = len(speech) // _FRAME_BYTES
    release_frames = int(_SAMPLE_RATE * release_seconds)
    envelope = _duck_envelope(
        speech_frames,
        duck_gain=duck_gain,
        solo_ratio=solo_ratio,
        fade_in_frames=int(_SAMPLE_RATE * fade_in_seconds),
        release_frames=release_frames,
    )
    padded_speech = speech + b"\x00" * (release_frames * _FRAME_BYTES)

    # El colchón sí sigue a ritmo real (es la pista entrante de verdad):
    # `_duck_chunks` lo mezcla chunk a chunk apenas llega, sin esperar a
    # juntar todo el segmento con voz antes de escribir nada.
    music_chunks = Decoder(music_path).chunks()
    ducked_chunks = _duck_chunks(music_chunks, padded_speech, envelope)
    return _stream_with_held_tail(encoder, ducked_chunks, crossfade_window_bytes(crossfade_seconds))


def play_tracks(encoder: Encoder, paths: Iterable[Path], *, crossfade_seconds: float = 0.0) -> None:
    """Reproduce `paths` en secuencia contra el mismo `encoder`, fundiendo
    la cola de cada tema con el arranque del siguiente si `crossfade_seconds` > 0.
    """
    tail = b""
    for path in paths:
        tail = play_track(encoder, path, crossfade_seconds=crossfade_seconds, incoming_tail=tail)
    if tail:
        encoder.write(tail)
